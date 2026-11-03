# Ngày tạo: 2026-11-03
# Mục đích: Migration khởi tạo toàn bộ 6 PostgreSQL schemas (market, analysis, strategy, trading, portfolio, system)
#           cùng 24 bảng, check constraints và indexes theo đúng đặc tả Mục 6 của Implementation Plan.

"""Initial 6 schemas and 24 tables

Revision ID: 0001_initial_schemas
Revises: None
Create Date: 2026-11-03 09:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.models_registry import POSTGRES_SCHEMAS, Base

revision: str = "0001_initial_schemas"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tạo 6 schemas và toàn bộ các bảng, ràng buộc, chỉ mục."""
    bind = op.get_bind()
    for schema_name in POSTGRES_SCHEMAS:
        op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # Sử dụng Base.metadata.create_all trên bind của Alembic để tạo chuẩn xác 24 bảng cùng FK/Check/Index
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Xóa toàn bộ các bảng và 6 schemas theo thứ tự ngược lại."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    for schema_name in reversed(POSTGRES_SCHEMAS):
        op.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
