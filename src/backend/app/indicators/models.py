# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `analysis` (analysis_runs, technical_indicators, stock_signals, ai_reports).

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalysisRun(Base):
    """Lịch sử một đợt chạy tính toán chỉ báo, quét tín hiệu hoặc phân tích AI."""

    __tablename__ = "analysis_runs"
    __table_args__ = {"schema": "analysis"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    data_as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)


class TechnicalIndicator(Base):
    """Lưu trữ bộ chỉ báo kỹ thuật theo ngày và phiên bản tính toán (calculation_version)."""

    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "trading_date",
            "calculation_version",
            name="uq_tech_indicators_stock_date_ver",
        ),
        Index("ix_technical_indicators_stock_trading_date", "stock_id", "trading_date"),
        {"schema": "analysis"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id"), nullable=False
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    ma20: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    ma50: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    ma200: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    ema20: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    ema50: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    rsi14: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    macd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    macd_signal: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    macd_histogram: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    atr14: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    volume_avg20: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    calculation_version: Mapped[str] = mapped_column(String(30), nullable=False)


class StockSignal(Base):
    """Tín hiệu BUY/SELL/HOLD sinh ra từ chiến lược có kèm lý do và mức cắt lỗ."""

    __tablename__ = "stock_signals"
    __table_args__ = (
        Index("ix_stock_signals_stock_trading_date", "stock_id", "trading_date"),
        Index("ix_stock_signals_status_created_at", "status", "created_at"),
        {"schema": "analysis"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id"), nullable=False
    )
    strategy_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.strategy_versions.id"), nullable=True
    )
    analysis_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis.analysis_runs.id"), nullable=True
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    reference_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    reason: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiReport(Base):
    """Báo cáo giải thích từ AI kèm snapshot dữ liệu đầu vào, phiên bản prompt và nguồn trích dẫn."""

    __tablename__ = "ai_reports"
    __table_args__ = {"schema": "analysis"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id"), nullable=True
    )
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis.stock_signals.id"), nullable=True
    )
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    input_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    report: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    source_references: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
