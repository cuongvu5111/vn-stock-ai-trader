# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `strategy` (strategies, strategy_versions, backtest_runs, backtest_trades).

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Strategy(Base):
    """Định nghĩa chiến lược giao dịch (ví dụ: Trend Following, Pullback)."""

    __tablename__ = "strategies"
    __table_args__ = {"schema": "strategy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class StrategyVersion(Base):
    """Lưu trữ phiên bản cấu hình tham số của từng chiến lược để tái lập kết quả backtest/signal."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_strategy_ver"),
        {"schema": "strategy"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.strategies.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    code_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class BacktestRun(Base):
    """Thông tin một phiên chạy Backtest với đầy đủ giả định phí, thuế và độ trượt giá."""

    __tablename__ = "backtest_runs"
    __table_args__ = {"schema": "strategy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.strategy_versions.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fee_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    tax_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    slippage_bps: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    assumptions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class BacktestTrade(Base):
    """Chi tiết từng giao dịch giả lập trong một phiên chạy Backtest."""

    __tablename__ = "backtest_trades"
    __table_args__ = {"schema": "strategy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.backtest_runs.id"), nullable=False
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id"), nullable=False
    )
    entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fees: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    taxes: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
