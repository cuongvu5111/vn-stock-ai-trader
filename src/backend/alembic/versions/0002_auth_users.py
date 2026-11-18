# Ngày tạo: 2026-11-17
# Mục đích: Migration bổ sung bảng `system.users` (xác thực JWT/RBAC), data-fix require_human_approval và seed bootstrap admin từ biến môi trường.
# Lý do: 0001 dùng Base.metadata.create_all nên DB mới đã có sẵn bảng này; migration phải idempotent cho cả hai trường hợp.

"""Auth users table and bootstrap admin

Revision ID: 0002_auth_users
Revises: 0001_initial_schemas
Create Date: 2026-11-17 08:50:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import ensure_bootstrap_admin

revision: str = "0002_auth_users"
down_revision: Union[str, None] = "0001_initial_schemas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_users_table_if_missing(bind) -> None:
    """DB 0001 cũ chưa có `system.users` thì tạo; DB mới (0001 dùng Base.metadata hiện tại) đã có thì bỏ qua."""
    User.__table__.create(bind=bind, checkfirst=True)


def _enforce_human_approval() -> None:
    """
    Data-fix idempotent trước rollout: mọi cấu hình rủi ro bắt buộc `require_human_approval = true`.
    Chỉ ghi đè đúng key này (toán tử `||` trên JSONB giữ nguyên các key khác) và bỏ qua dòng đã đúng.
    """
    op.execute(
        sa.text(
            "UPDATE system.risk_configs "
            "SET configuration = configuration || jsonb_build_object('require_human_approval', TRUE) "
            "WHERE jsonb_typeof(configuration) = 'object' "
            "AND (configuration -> 'require_human_approval') IS DISTINCT FROM 'true'::jsonb"
        )
    )


def upgrade() -> None:
    """Tạo `system.users` nếu thiếu, ép require_human_approval=true rồi seed admin (nếu có BOOTSTRAP_ADMIN_* hợp lệ)."""
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS system"))

    # Offline: 0001 đã phát CREATE TABLE cho toàn bộ Base.metadata (gồm system.users) và offline
    # không thể checkfirst, nên 0002 không được phát CREATE TABLE lần hai.
    if not context.is_offline_mode():
        _create_users_table_if_missing(op.get_bind())

    _enforce_human_approval()

    if context.is_offline_mode():
        return

    # Seed idempotent: user đã tồn tại thì giữ nguyên, không bao giờ ghi đè mật khẩu
    with Session(bind=op.get_bind()) as session:
        ensure_bootstrap_admin(session)

def downgrade() -> None:
    """Xóa `system.users` nếu tồn tại."""
    bind = op.get_bind()
    User.__table__.drop(bind=bind, checkfirst=not context.is_offline_mode())
