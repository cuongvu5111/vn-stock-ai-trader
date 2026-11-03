# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa SQLAlchemy 2.0 models cho schema `system` (risk_configs, job_runs, audit_logs, app_settings).

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RiskConfig(Base):
    """Cấu hình hạn mức rủi ro và Kill Switch cho hệ thống."""

    __tablename__ = "risk_configs"
    __table_args__ = {"schema": "system"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class JobRun(Base):
    """Theo dõi trạng thái các background job định kỳ (import, scan, daily report)."""

    __tablename__ = "job_runs"
    __table_args__ = {"schema": "system"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    records_processed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)


class AuditLog(Base):
    """Nhật ký kiểm toán bất biến cho mọi thay đổi trạng thái quan trọng (approve, reject, order, risk config)."""

    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "system"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    before_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AppSetting(Base):
    """Cấu hình động dạng key-value của hệ thống."""

    __tablename__ = "app_settings"
    __table_args__ = {"schema": "system"}

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
