# Ngày tạo: 2026-11-17
# Mục đích: SQLAlchemy 2.0 model `system.users` phục vụ xác thực, khóa tài khoản và thu hồi token.

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ROLE_ADMIN = "admin"
ROLE_TRADER = "trader"
ROLE_VIEWER = "viewer"
ALL_ROLES = (ROLE_ADMIN, ROLE_TRADER, ROLE_VIEWER)


def utc_now() -> datetime:
    """Mọi timestamp sự kiện lưu UTC timezone-aware."""
    return datetime.now(timezone.utc)


class User(Base):
    """Tài khoản người dùng nội bộ; `token_version` tăng lên để thu hồi toàn bộ JWT đã cấp."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'trader', 'viewer')", name="role"),
        CheckConstraint("username = lower(username)", name="username_normalized"),
        {"schema": "system"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
