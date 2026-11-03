# Ngày tạo: 2026-11-03
# Mục đích: Điều phối việc lưu trữ và truy xuất các phiên chạy Backtest (`strategy.backtest_runs`, `strategy.backtest_trades`).

import uuid
from decimal import Decimal
from typing import List

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.engine import run_backtest_simulation
from app.indicators.calculator import OhlcvBar
from app.market_data.models import DailyPrice, Stock
from app.schemas.strategy import (
    BacktestCreateRequest,
    BacktestRunResponse,
    BacktestTradeItemResponse,
)
from app.screening.service import ScannerService
from app.strategies.engine import build_strategy_instance
from app.strategies.models import BacktestRun, BacktestTrade, Strategy, StrategyVersion

logger = structlog.get_logger(__name__)


class BacktestService:
    """Service quản lý chạy Backtest và lưu kết quả vào schema `strategy`."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.scanner_service = ScannerService(session=session)

    def create_and_run_backtest(self, payload: BacktestCreateRequest) -> BacktestRunResponse:
        """Khởi tạo phiên chạy Backtest, chạy mô phỏng chống look-ahead và lưu toàn bộ trades/metrics."""
        if payload.end_date < payload.start_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ngày kết thúc (end_date) phải lớn hơn hoặc bằng ngày bắt đầu (start_date).",
            )

        norm_symbol = payload.symbol.strip().upper()
        stock = self.session.scalar(select(Stock).where(Stock.symbol == norm_symbol))
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy mã cổ phiếu '{norm_symbol}'.",
            )

        strategy, strat_ver = self.scanner_service.get_or_create_strategy_version(
            strategy_type=payload.strategy_type,
            version=payload.strategy_version,
            configuration_override=payload.configuration_override,
        )

        strategy_instance = build_strategy_instance(
            strategy_type=strategy.strategy_type,
            strategy_id=str(strategy.id),
            strategy_version=strat_ver.version,
            configuration=strat_ver.configuration,
        )

        # Lấy toàn bộ lịch sử giá <= end_date để có đủ dữ liệu warm-up trước start_date
        price_rows = self.session.scalars(
            select(DailyPrice)
            .where(
                DailyPrice.stock_id == stock.id,
                DailyPrice.trading_date <= payload.end_date,
            )
            .order_by(DailyPrice.trading_date.asc())
        ).all()

        bars = [
            OhlcvBar(
                trading_date=p.trading_date,
                open=p.open,
                high=p.high,
                low=p.low,
                close=p.close,
                volume=p.volume,
            )
            for p in price_rows
        ]

        sim_result = run_backtest_simulation(
            symbol=stock.symbol,
            bars=bars,
            strategy=strategy_instance,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_capital=payload.initial_capital,
            fee_rate=payload.fee_rate,
            tax_rate=payload.tax_rate,
            slippage_bps=payload.slippage_bps,
            lot_size=payload.lot_size,
        )

        assumptions_with_meta = dict(sim_result.assumptions)
        assumptions_with_meta["symbol"] = stock.symbol
        assumptions_with_meta["strategy_type"] = strategy.strategy_type
        assumptions_with_meta["strategy_version"] = strat_ver.version
        assumptions_with_meta["strategy_configuration"] = strat_ver.configuration

        bt_run = BacktestRun(
            strategy_version_id=strat_ver.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_capital=payload.initial_capital,
            fee_rate=payload.fee_rate,
            tax_rate=payload.tax_rate,
            slippage_bps=payload.slippage_bps,
            assumptions=assumptions_with_meta,
            metrics=sim_result.metrics,
            status="COMPLETED",
        )
        self.session.add(bt_run)
        self.session.flush()

        trade_responses: List[BacktestTradeItemResponse] = []
        for t in sim_result.trades:
            db_trade = BacktestTrade(
                backtest_run_id=bt_run.id,
                stock_id=stock.id,
                entry_date=t.entry_date,
                exit_date=t.exit_date,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                quantity=t.quantity,
                fees=t.fees,
                taxes=t.taxes,
                pnl=t.pnl,
                exit_reason=t.exit_reason,
            )
            self.session.add(db_trade)
            self.session.flush()

            trade_responses.append(
                BacktestTradeItemResponse(
                    id=db_trade.id,
                    symbol=stock.symbol,
                    signal_date=t.signal_date,
                    entry_date=t.entry_date,
                    exit_date=t.exit_date,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    quantity=t.quantity,
                    fees=t.fees,
                    taxes=t.taxes,
                    pnl=t.pnl,
                    exit_reason=t.exit_reason,
                )
            )

        self.session.commit()
        self.session.refresh(bt_run)

        logger.info(
            "backtest_run_completed",
            backtest_run_id=str(bt_run.id),
            symbol=stock.symbol,
            strategy_type=strategy.strategy_type,
            trades_count=len(trade_responses),
            total_return_pct=sim_result.metrics.get("total_return_pct"),
        )

        return BacktestRunResponse(
            id=bt_run.id,
            strategy_version_id=bt_run.strategy_version_id,
            symbol=stock.symbol,
            strategy_type=strategy.strategy_type,
            strategy_version=strat_ver.version,
            start_date=bt_run.start_date,
            end_date=bt_run.end_date,
            initial_capital=bt_run.initial_capital,
            fee_rate=bt_run.fee_rate or Decimal("0.0015"),
            tax_rate=bt_run.tax_rate or Decimal("0.0010"),
            slippage_bps=bt_run.slippage_bps or Decimal("10.0000"),
            status=bt_run.status or "COMPLETED",
            assumptions=bt_run.assumptions or {},
            metrics=bt_run.metrics or {},
            trades=trade_responses,
            created_at=bt_run.created_at,
        )

    def get_backtest_run(self, backtest_id: uuid.UUID) -> BacktestRunResponse:
        """Truy xuất chi tiết kết quả một phiên chạy Backtest theo ID."""
        bt_run = self.session.get(BacktestRun, backtest_id)
        if not bt_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy phiên Backtest với ID '{backtest_id}'.",
            )

        strat_ver = self.session.get(StrategyVersion, bt_run.strategy_version_id)
        strategy = self.session.get(Strategy, strat_ver.strategy_id) if strat_ver else None

        trades_rows = self.session.execute(
            select(BacktestTrade, Stock.symbol)
            .join(Stock, BacktestTrade.stock_id == Stock.id)
            .where(BacktestTrade.backtest_run_id == bt_run.id)
            .order_by(BacktestTrade.entry_date.asc())
        ).all()

        assumptions = bt_run.assumptions or {}
        symbol = str(assumptions.get("symbol") or (trades_rows[0][1] if trades_rows else "UNKNOWN"))

        trade_items = [
            BacktestTradeItemResponse(
                id=tr.id,
                symbol=sym,
                signal_date=None,
                entry_date=tr.entry_date or bt_run.start_date,
                exit_date=tr.exit_date or bt_run.end_date,
                entry_price=tr.entry_price or Decimal("0"),
                exit_price=tr.exit_price or Decimal("0"),
                quantity=tr.quantity or 0,
                fees=tr.fees or Decimal("0"),
                taxes=tr.taxes or Decimal("0"),
                pnl=tr.pnl or Decimal("0"),
                exit_reason=tr.exit_reason or "UNKNOWN",
            )
            for tr, sym in trades_rows
        ]

        return BacktestRunResponse(
            id=bt_run.id,
            strategy_version_id=bt_run.strategy_version_id,
            symbol=symbol,
            strategy_type=strategy.strategy_type if strategy else str(assumptions.get("strategy_type", "TREND_FOLLOWING")),
            strategy_version=strat_ver.version if strat_ver else int(assumptions.get("strategy_version", 1)),
            start_date=bt_run.start_date,
            end_date=bt_run.end_date,
            initial_capital=bt_run.initial_capital,
            fee_rate=bt_run.fee_rate or Decimal("0.0015"),
            tax_rate=bt_run.tax_rate or Decimal("0.0010"),
            slippage_bps=bt_run.slippage_bps or Decimal("10.0000"),
            status=bt_run.status or "COMPLETED",
            assumptions=assumptions,
            metrics=bt_run.metrics or {},
            trades=trade_items,
            created_at=bt_run.created_at,
        )
