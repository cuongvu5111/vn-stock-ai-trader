# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `market` (stocks, data_sources, import_batches, daily_prices).
# Lý do: Đảm bảo toàn bộ giá cổ phiếu lưu bằng kiểu NUMERIC(18,4) và có đầy đủ ràng buộc kiểm tra tính hợp lệ OHLCV.

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
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


class Stock(Base):
    """Danh mục mã cổ phiếu niêm yết trên HOSE, HNX, UPCOM."""

    __tablename__ = "stocks"
    __table_args__ = {"schema": "market"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataSource(Base):
    """Nguồn dữ liệu thị trường (CSV hoặc Licensed Provider)."""

    __tablename__ = "data_sources"
    __table_args__ = {"schema": "market"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    license_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportBatch(Base):
    """Theo dõi lịch sử các lần import dữ liệu để đảm bảo idempotency và truy vết lỗi."""

    __tablename__ = "import_batches"
    __table_args__ = {"schema": "market"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.data_sources.id"), nullable=True
    )
    file_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    rows_read: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_inserted: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_rejected: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)


class DailyPrice(Base):
    """Dữ liệu giá OHLCV theo ngày của từng cổ phiếu."""

    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("stock_id", "trading_date", "source_id", name="uq_daily_prices_stock_date_source"),
        CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="positive_prices",
        ),
        CheckConstraint(
            "adjusted_close IS NULL OR adjusted_close > 0",
            name="positive_adjusted_close",
        ),
        CheckConstraint("high >= low", name="high_gte_low"),
        CheckConstraint("high >= open AND high >= close", name="high_gte_open_close"),
        CheckConstraint("low <= open AND low <= close", name="low_lte_open_close"),
        CheckConstraint("volume >= 0", name="non_negative_volume"),
        Index("ix_daily_prices_stock_trading_date", "stock_id", "trading_date"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.stocks.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.data_sources.id"), nullable=False
    )
    import_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market.import_batches.id"), nullable=True
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
