# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `portfolio` (accounts, positions, cash_transactions, daily_snapshots).
# Lý do: Đảm bảo quy tắc kế toán (Accounting rule) trong đó cash_transactions và executions là dữ liệu gốc để đối soát.

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Account(Base):
    """Tài khoản giao dịch giả lập (Paper Account)."""

    __tablename__ = "accounts"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="VND")
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PAPER")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Position(Base):
    """Vị thế nắm giữ cổ phiếu hiện tại của tài khoản (tổng hợp từ executions)."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "stock_id", name="uq_positions_account_stock"),
        {"schema": "portfolio"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio.accounts.id", ondelete="RESTRICT"), nullable=False
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CashTransaction(Base):
    """Sổ cái ghi nhận mọi biến động tiền mặt (nạp vốn gốc, trừ tiền mua, cộng tiền bán, phí, thuế)."""

    __tablename__ = "cash_transactions"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio.accounts.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailySnapshot(Base):
    """Bản chụp giá trị tài sản ròng (NAV) cuối mỗi ngày giao dịch."""

    __tablename__ = "daily_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_daily_snapshots_account_date"),
        Index("ix_daily_snapshots_account_snapshot_date", "account_id", "snapshot_date"),
        {"schema": "portfolio"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio.accounts.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
