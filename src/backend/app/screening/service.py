# Ngày tạo: 2026-11-03
# Mục đích: Xử lý nghiệp vụ quét cổ phiếu (Stock Scanner), quản lý phiên bản chiến lược và lưu trữ tín hiệu (`analysis.stock_signals`).

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indicators.calculator import IndicatorPoint, OhlcvBar, calculate_indicator_series
from app.indicators.models import AnalysisRun, StockSignal
from app.market_data.models import DailyPrice, Stock
from app.schemas.strategy import (
    ScannerRunRequest,
    ScannerRunResponse,
    SignalContractResponse,
    SignalListResponse,
)
from app.strategies.engine import build_strategy_instance
from app.strategies.models import Strategy, StrategyVersion

logger = structlog.get_logger(__name__)

DEFAULT_STRATEGY_CONFIGS: Dict[str, Dict[str, Any]] = {
    "TREND_FOLLOWING": {
        "ma_fast": 20,
        "ma_slow": 50,
        "rsi_min": 50,
        "rsi_max": 70,
        "rsi_overbought_exit": 78,
        "volume_multiplier": "1.2",
        "atr_stop_multiplier": "2.0",
        "exit_rule": "CLOSE_BELOW_MA20_OR_MA20_BELOW_MA50_OR_RSI_OVERBOUGHT",
    },
    "PULLBACK": {
        "trend_ma": 50,
        "pullback_zone_ma": 20,
        "pullback_tolerance_pct": "0.025",
        "rsi_recovery_min": 40,
        "rsi_recovery_max": 62,
        "rsi_take_profit": 72,
        "atr_stop_multiplier": "1.5",
        "exit_rule": "CLOSE_BELOW_MA50_OR_RSI_TAKE_PROFIT",
    },
}


class ScannerService:
    """Service quản lý phiên bản chiến lược, quét tín hiệu EOD và lưu vào `analysis.stock_signals`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_strategy_version(
        self,
        strategy_type: str,
        version: int = 1,
        configuration_override: Optional[Dict[str, Any]] = None,
    ) -> tuple[Strategy, StrategyVersion]:
        """Lấy hoặc tự động khởi tạo bản ghi Strategy và StrategyVersion tương ứng."""
        norm_type = strategy_type.strip().upper()
        if norm_type not in DEFAULT_STRATEGY_CONFIGS:
            raise ValueError(f"Chiến lược '{norm_type}' không hợp lệ. Chỉ hỗ trợ TREND_FOLLOWING hoặc PULLBACK.")

        strategy = self.session.scalar(
            select(Strategy).where(Strategy.strategy_type == norm_type)
        )
        if not strategy:
            strategy = Strategy(
                name=f"{norm_type.replace('_', ' ').title()} EOD",
                description=f"Chiến lược {norm_type} có thể giải thích cho Daily Trading.",
                strategy_type=norm_type,
                is_active=True,
            )
            self.session.add(strategy)
            self.session.flush()

        merged_config = dict(DEFAULT_STRATEGY_CONFIGS[norm_type])
        if configuration_override:
            merged_config.update(configuration_override)

        strat_ver = self.session.scalar(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == version,
            )
        )
        if not strat_ver:
            strat_ver = StrategyVersion(
                strategy_id=strategy.id,
                version=version,
                configuration=merged_config,
                code_version="0.1.0",
            )
            self.session.add(strat_ver)
            self.session.flush()
        elif configuration_override:
            strat_ver.configuration = merged_config
            self.session.flush()

        return strategy, strat_ver

    def run_scanner(self, payload: ScannerRunRequest) -> ScannerRunResponse:
        """
        Quét cổ phiếu theo điều kiện chiến lược tại ngày `as_of_date`,
        lưu tín hiệu vào `analysis.stock_signals` và trả về danh sách `SignalContractResponse`.
        """
        started_at = datetime.now(timezone.utc)
        strategy, strat_ver = self.get_or_create_strategy_version(
            strategy_type=payload.strategy_type,
            version=payload.strategy_version,
            configuration_override=payload.configuration_override,
        )

        strategy_engine = build_strategy_instance(
            strategy_type=strategy.strategy_type,
            strategy_id=str(strategy.id),
            strategy_version=strat_ver.version,
            configuration=strat_ver.configuration,
        )

        run_record = AnalysisRun(
            run_type="SCANNER",
            started_at=started_at,
            status="PROCESSING",
            data_as_of=payload.as_of_date,
            parameters={
                "strategy_type": strategy.strategy_type,
                "strategy_version": strat_ver.version,
                "symbols": payload.symbols or "ALL_ACTIVE",
            },
        )
        self.session.add(run_record)
        self.session.flush()

        stock_stmt = select(Stock)
        if payload.symbols:
            cleaned = [s.strip().upper() for s in payload.symbols if s.strip()]
            stock_stmt = stock_stmt.where(Stock.symbol.in_(cleaned))
        else:
            stock_stmt = stock_stmt.where(Stock.is_active.is_(True))

        stocks = self.session.scalars(stock_stmt.order_by(Stock.symbol.asc())).all()
        signals_out: List[SignalContractResponse] = []
        total_scanned = 0

        for stock in stocks:
            price_stmt = select(DailyPrice).where(DailyPrice.stock_id == stock.id)
            if payload.as_of_date is not None:
                price_stmt = price_stmt.where(DailyPrice.trading_date <= payload.as_of_date)

            price_rows = self.session.scalars(
                price_stmt.order_by(DailyPrice.trading_date.asc())
            ).all()
            if not price_rows:
                continue

            total_scanned += 1
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

            ind_series: List[IndicatorPoint] = calculate_indicator_series(
                bars=bars,
                calculation_version=payload.calculation_version,
            )
            latest_bar = bars[-1]
            latest_ind = ind_series[-1]
            latest_source_ver = f"BATCH_{price_rows[-1].import_batch_id or price_rows[-1].source_id}"

            evaluated = strategy_engine.evaluate_bar(
                symbol=stock.symbol,
                bar=latest_bar,
                indicator=latest_ind,
                source_data_version=latest_source_ver,
            )

            # Kiểm tra tránh tạo trùng bản ghi StockSignal cho cùng (stock_id, strategy_version_id, trading_date)
            existing_sig = self.session.scalar(
                select(StockSignal).where(
                    StockSignal.stock_id == stock.id,
                    StockSignal.strategy_version_id == strat_ver.id,
                    StockSignal.trading_date == evaluated.signal_date,
                )
            )

            reason_json = {
                "reasons": evaluated.reasons,
                "warnings": evaluated.warnings,
                "source_data_version": evaluated.source_data_version,
                "data_as_of": evaluated.data_as_of.isoformat(),
                "indicators_snapshot": evaluated.indicators_snapshot,
            }

            if existing_sig is None:
                db_sig = StockSignal(
                    stock_id=stock.id,
                    strategy_version_id=strat_ver.id,
                    analysis_run_id=run_record.id,
                    trading_date=evaluated.signal_date,
                    action=evaluated.action,
                    score=evaluated.score,
                    reference_price=evaluated.reference_price,
                    stop_loss=evaluated.stop_loss,
                    reason=reason_json,
                    status="GENERATED",
                )
                self.session.add(db_sig)
                self.session.flush()
            else:
                existing_sig.analysis_run_id = run_record.id
                existing_sig.action = evaluated.action
                existing_sig.score = evaluated.score
                existing_sig.reference_price = evaluated.reference_price
                existing_sig.stop_loss = evaluated.stop_loss
                existing_sig.reason = reason_json
                db_sig = existing_sig

            if payload.only_actionable and evaluated.action == "HOLD":
                continue

            signals_out.append(
                SignalContractResponse(
                    id=db_sig.id,
                    symbol=stock.symbol,
                    strategy_id=evaluated.strategy_id,
                    strategy_version=evaluated.strategy_version,
                    signal_date=evaluated.signal_date,
                    data_as_of=evaluated.data_as_of,
                    action=evaluated.action,
                    score=evaluated.score,
                    reference_price=evaluated.reference_price,
                    stop_loss=evaluated.stop_loss,
                    reason=evaluated.reasons,
                    warnings=evaluated.warnings,
                    source_data_version=evaluated.source_data_version,
                    status=db_sig.status,
                    created_at=db_sig.created_at,
                )
            )

        run_record.completed_at = datetime.now(timezone.utc)
        run_record.status = "COMPLETED"
        self.session.commit()

        return ScannerRunResponse(
            analysis_run_id=run_record.id,
            strategy_type=strategy.strategy_type,
            strategy_version=strat_ver.version,
            total_scanned=total_scanned,
            signals_generated=len(signals_out),
            signals=signals_out,
        )

    def list_signals(
        self,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
        trading_date: Optional[date] = None,
        limit: int = 100,
    ) -> SignalListResponse:
        """Lấy danh sách tín hiệu đã lưu trong `analysis.stock_signals`."""
        stmt = (
            select(StockSignal, Stock.symbol, StrategyVersion.strategy_id, StrategyVersion.version)
            .join(Stock, StockSignal.stock_id == Stock.id)
            .outerjoin(StrategyVersion, StockSignal.strategy_version_id == StrategyVersion.id)
        )

        if symbol:
            stmt = stmt.where(Stock.symbol == symbol.strip().upper())
        if action:
            stmt = stmt.where(StockSignal.action == action.strip().upper())
        if trading_date:
            stmt = stmt.where(StockSignal.trading_date == trading_date)

        rows = self.session.execute(
            stmt.order_by(StockSignal.trading_date.desc(), StockSignal.created_at.desc()).limit(limit)
        ).all()

        items: List[SignalContractResponse] = []
        for sig, sym, strat_id, strat_ver_num in rows:
            r_data = sig.reason or {}
            items.append(
                SignalContractResponse(
                    id=sig.id,
                    symbol=sym,
                    strategy_id=str(strat_id or uuid.UUID(int=0)),
                    strategy_version=int(strat_ver_num or 1),
                    signal_date=sig.trading_date,
                    data_as_of=date.fromisoformat(r_data.get("data_as_of", sig.trading_date.isoformat())),
                    action=sig.action,
                    score=sig.score or Decimal("0.00"),
                    reference_price=sig.reference_price or Decimal("0.0000"),
                    stop_loss=sig.stop_loss,
                    reason=list(r_data.get("reasons", [])),
                    warnings=list(r_data.get("warnings", [])),
                    source_data_version=str(r_data.get("source_data_version", "CSV_EOD_V1")),
                    status=sig.status,
                    created_at=sig.created_at,
                )
            )

        return SignalListResponse(total=len(items), items=items)
