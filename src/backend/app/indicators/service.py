# Ngày tạo: 2026-11-03
# Mục đích: Điều phối việc đọc dữ liệu giá từ `market.daily_prices`, tính toán chỉ báo kỹ thuật và lưu trữ vào `analysis.technical_indicators`.
# Lý do:
#   - Đảm bảo tính idempotent theo khóa (stock_id, trading_date, calculation_version).
#   - Chỉ đọc dữ liệu <= as_of_date để chống look-ahead bias tuyệt đối.

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indicators.calculator import OhlcvBar, calculate_indicator_series
from app.indicators.models import AnalysisRun, TechnicalIndicator
from app.market_data.models import DailyPrice, Stock
from app.schemas.indicators import (
    IndicatorCalculationRunResponse,
    StockIndicatorHistoryResponse,
    TechnicalIndicatorItemResponse,
)

logger = structlog.get_logger(__name__)


class IndicatorService:
    """Service quản lý tính toán và truy xuất chỉ báo kỹ thuật."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def calculate_and_persist(
        self,
        symbols: Optional[List[str]] = None,
        as_of_date: Optional[date] = None,
        calculation_version: str = "v1.0",
    ) -> IndicatorCalculationRunResponse:
        """
        Tính toán chỉ báo kỹ thuật cho danh sách mã cổ phiếu (hoặc toàn bộ mã active)
        và lưu idempotent vào bảng `analysis.technical_indicators`.
        """
        started_at = datetime.now(timezone.utc)
        cleaned_symbols = [s.strip().upper() for s in symbols if s.strip()] if symbols else None

        run_record = AnalysisRun(
            run_type="INDICATORS",
            started_at=started_at,
            status="PROCESSING",
            data_as_of=as_of_date,
            parameters={
                "symbols": cleaned_symbols or "ALL_ACTIVE",
                "calculation_version": calculation_version,
            },
        )
        self.session.add(run_record)
        self.session.flush()

        stock_stmt = select(Stock)
        if cleaned_symbols:
            stock_stmt = stock_stmt.where(Stock.symbol.in_(cleaned_symbols))
        else:
            stock_stmt = stock_stmt.where(Stock.is_active.is_(True))

        stocks = self.session.scalars(stock_stmt.order_by(Stock.symbol.asc())).all()

        warnings: Dict[str, str] = {}
        if cleaned_symbols:
            found_symbols = {s.symbol for s in stocks}
            for req_sym in cleaned_symbols:
                if req_sym not in found_symbols:
                    warnings[req_sym] = "SYMBOL_NOT_FOUND"

        symbols_processed = 0
        rows_upserted = 0
        max_date_seen: Optional[date] = as_of_date

        for stock in stocks:
            price_stmt = select(DailyPrice).where(DailyPrice.stock_id == stock.id)
            if as_of_date is not None:
                price_stmt = price_stmt.where(DailyPrice.trading_date <= as_of_date)

            price_rows = self.session.scalars(
                price_stmt.order_by(DailyPrice.trading_date.asc())
            ).all()

            if not price_rows:
                warnings[stock.symbol] = "NO_PRICE_DATA"
                continue

            if len(price_rows) < 20:
                warnings[stock.symbol] = (
                    f"INSUFFICIENT_WARMUP_ROWS ({len(price_rows)} rows; minimum 20 needed for MA20/EMA20/VolAvg20)"
                )

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

            indicator_points = calculate_indicator_series(
                bars=bars,
                calculation_version=calculation_version,
            )

            existing_indicators = {
                ind.trading_date: ind
                for ind in self.session.scalars(
                    select(TechnicalIndicator).where(
                        TechnicalIndicator.stock_id == stock.id,
                        TechnicalIndicator.calculation_version == calculation_version,
                    )
                ).all()
            }

            for pt in indicator_points:
                if max_date_seen is None or pt.trading_date > max_date_seen:
                    max_date_seen = pt.trading_date

                existing = existing_indicators.get(pt.trading_date)
                if existing is None:
                    self.session.add(
                        TechnicalIndicator(
                            stock_id=stock.id,
                            trading_date=pt.trading_date,
                            ma20=pt.ma20,
                            ma50=pt.ma50,
                            ma200=pt.ma200,
                            ema20=pt.ema20,
                            ema50=pt.ema50,
                            rsi14=pt.rsi14,
                            macd=pt.macd,
                            macd_signal=pt.macd_signal,
                            macd_histogram=pt.macd_histogram,
                            atr14=pt.atr14,
                            volume_avg20=pt.volume_avg20,
                            calculation_version=calculation_version,
                        )
                    )
                else:
                    existing.ma20 = pt.ma20
                    existing.ma50 = pt.ma50
                    existing.ma200 = pt.ma200
                    existing.ema20 = pt.ema20
                    existing.ema50 = pt.ema50
                    existing.rsi14 = pt.rsi14
                    existing.macd = pt.macd
                    existing.macd_signal = pt.macd_signal
                    existing.macd_histogram = pt.macd_histogram
                    existing.atr14 = pt.atr14
                    existing.volume_avg20 = pt.volume_avg20

                rows_upserted += 1

            symbols_processed += 1

        completed_at = datetime.now(timezone.utc)
        run_record.completed_at = completed_at
        run_record.status = "COMPLETED"
        run_record.data_as_of = max_date_seen
        if warnings:
            run_record.error_detail = {"warnings": warnings}

        self.session.commit()
        self.session.refresh(run_record)

        logger.info(
            "indicators_calculation_completed",
            analysis_run_id=str(run_record.id),
            calculation_version=calculation_version,
            symbols_processed=symbols_processed,
            rows_upserted=rows_upserted,
        )

        return IndicatorCalculationRunResponse(
            analysis_run_id=run_record.id,
            status=run_record.status or "COMPLETED",
            calculation_version=calculation_version,
            data_as_of=run_record.data_as_of,
            symbols_processed=symbols_processed,
            rows_upserted=rows_upserted,
            warnings=warnings,
            started_at=run_record.started_at,
            completed_at=run_record.completed_at,
        )

    def get_stock_indicators(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        calculation_version: str = "v1.0",
        limit: int = 500,
    ) -> StockIndicatorHistoryResponse:
        """Truy vấn chuỗi chỉ báo kỹ thuật đã lưu của một mã cổ phiếu."""
        normalized_symbol = symbol.strip().upper()
        stock = self.session.scalar(select(Stock).where(Stock.symbol == normalized_symbol))
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy mã cổ phiếu '{normalized_symbol}'.",
            )

        stmt = select(TechnicalIndicator).where(
            TechnicalIndicator.stock_id == stock.id,
            TechnicalIndicator.calculation_version == calculation_version,
        )
        if start_date is not None:
            stmt = stmt.where(TechnicalIndicator.trading_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(TechnicalIndicator.trading_date <= end_date)

        rows = self.session.scalars(
            stmt.order_by(TechnicalIndicator.trading_date.asc()).limit(limit)
        ).all()

        items: List[TechnicalIndicatorItemResponse] = []
        for row in rows:
            warm_up_core_ready = all(
                val is not None
                for val in (row.ma20, row.ema20, row.rsi14, row.atr14, row.volume_avg20)
            )
            items.append(
                TechnicalIndicatorItemResponse(
                    trading_date=row.trading_date,
                    ma20=row.ma20,
                    ma50=row.ma50,
                    ma200=row.ma200,
                    ema20=row.ema20,
                    ema50=row.ema50,
                    rsi14=row.rsi14,
                    macd=row.macd,
                    macd_signal=row.macd_signal,
                    macd_histogram=row.macd_histogram,
                    atr14=row.atr14,
                    volume_avg20=row.volume_avg20,
                    calculation_version=row.calculation_version,
                    warm_up_core_ready=warm_up_core_ready,
                )
            )

        return StockIndicatorHistoryResponse(
            symbol=stock.symbol,
            exchange=stock.exchange,
            calculation_version=calculation_version,
            start_date=start_date,
            end_date=end_date,
            total_records=len(items),
            items=items,
        )
