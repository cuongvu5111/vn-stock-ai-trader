# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `trading` (trade_proposals, approvals, orders, executions).
# Lý do: Không dùng cascade delete đối với lịch sử lệnh/khớp lệnh; tách riêng Order và Execution để hỗ trợ partial fills.

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TradeProposal(Base):
    """Đề xuất giao dịch đã qua kiểm tra Risk Engine bước 1 và chờ con người phê duyệt."""

    __tablename__ = "trade_proposals"
    __table_args__ = (
        Index("ix_trade_proposals_status_created_at", "status", "created_at"),
        {"schema": "trading"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis.stock_signals.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    risk_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    risk_check_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Approval(Base):
    """Bản ghi quyết định phê duyệt hoặc từ chối của người dùng đối với một TradeProposal."""

    __tablename__ = "approvals"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.trade_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Order(Base):
    """Lệnh giao dịch gửi sang Paper Broker sau khi đã được người dùng phê duyệt."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_created_at", "status", "created_at"),
        {"schema": "trading"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.trade_proposals.id", ondelete="RESTRICT"), nullable=True
    )
    broker_name: Mapped[str] = mapped_column(String(50), nullable=False, default="PAPER")
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    average_fill_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Execution(Base):
    """Bút toán khớp lệnh chi tiết (một Order có thể có nhiều Executions)."""

    __tablename__ = "executions"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.orders.id", ondelete="RESTRICT"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
