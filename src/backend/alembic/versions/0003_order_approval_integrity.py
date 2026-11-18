# Ngày tạo: 2026-11-17
# Mục đích: Toàn vẹn phê duyệt — mỗi `trading.orders` phải trỏ tới đúng một `trading.approvals` (unique, NOT NULL)
#           và `trading.approvals` lưu thêm `approver_user_id` (FK `system.users`, nullable) bên cạnh snapshot `approved_by`.
# Lý do: 0001 dùng `Base.metadata.create_all` nên DB mới đã có sẵn các cột/ràng buộc này, còn DB cũ thì chưa.
#        Mọi câu lệnh ở đây tự kiểm tra tồn tại ngay trong SQL (`IF NOT EXISTS`/khối DO) nên cùng một bản SQL
#        chạy đúng cho cả hai trường hợp, ở cả chế độ online lẫn offline (`--sql`), không phát sinh DDL trùng.

"""Order approval integrity and approver user link

Revision ID: 0003_order_approval_integrity
Revises: 0002_auth_users
Create Date: 2026-11-17 10:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_approval_integrity"
down_revision: Union[str, None] = "0002_auth_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORDER_APPROVAL_UNIQUE = "uq_orders_approval_id"
ORDER_APPROVAL_FK = "fk_orders_approval_id_approvals"
APPROVER_USER_FK = "fk_approvals_approver_user_id_users"

# Chỉ backfill khi khớp không mơ hồ: order có đúng một Approval APPROVED cùng proposal, proposal chỉ có một order
# và approval đó chưa gắn cho order khác. Mọi trường hợp còn lại giữ NULL để bước kiểm tra orphan bên dưới dừng migration.
BACKFILL_ORDER_APPROVAL_SQL = """
UPDATE trading.orders AS o
SET approval_id = a.id
FROM trading.approvals AS a
WHERE o.approval_id IS NULL
  AND o.proposal_id IS NOT NULL
  AND a.proposal_id = o.proposal_id
  AND a.decision = 'APPROVED'
  AND (
      SELECT count(*) FROM trading.approvals AS a2
      WHERE a2.proposal_id = o.proposal_id AND a2.decision = 'APPROVED'
  ) = 1
  AND (
      SELECT count(*) FROM trading.orders AS o2 WHERE o2.proposal_id = o.proposal_id
  ) = 1
  AND NOT EXISTS (SELECT 1 FROM trading.orders AS o3 WHERE o3.approval_id = a.id)
"""

# Username đã chuẩn hóa chữ thường (CHECK `username = lower(username)`), chỉ khớp chính xác; không khớp thì để NULL.
BACKFILL_APPROVER_USER_SQL = """
UPDATE trading.approvals AS a
SET approver_user_id = u.id
FROM system.users AS u
WHERE a.approver_user_id IS NULL
  AND u.username = lower(a.approved_by)
"""

# Message cố ý chỉ dùng ASCII để in được ở mọi console khi chạy `alembic upgrade --sql`.
ORPHAN_ORDER_GUARD_SQL = """
DO $$
DECLARE
    orphan_count integer;
    orphan_ids text;
BEGIN
    SELECT count(*) INTO orphan_count FROM trading.orders WHERE approval_id IS NULL;
    IF orphan_count > 0 THEN
        SELECT string_agg(sample.id::text, ', ') INTO orphan_ids
        FROM (
            SELECT id FROM trading.orders WHERE approval_id IS NULL ORDER BY created_at, id LIMIT 10
        ) AS sample;
        RAISE EXCEPTION USING
            ERRCODE = '23502',
            MESSAGE = 'Migration 0003_order_approval_integrity aborted: ' || orphan_count
                || ' order(s) have no unambiguous APPROVED approval for the same proposal (sample order ids: '
                || orphan_ids || ').',
            HINT = 'Review these orders and their trading.approvals rows manually, then re-run. '
                || 'The migration never guesses an approval_id.';
    END IF;
END
$$
"""


def _add_constraint_if_missing_sql(table: str, name: str, definition: str) -> str:
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{name}' AND conrelid = '{table}'::regclass
    ) THEN
        ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
    END IF;
END
$$
"""


UPGRADE_STATEMENTS: tuple[str, ...] = (
    # --- trading.approvals.approver_user_id ---
    "ALTER TABLE trading.approvals ADD COLUMN IF NOT EXISTS approver_user_id UUID",
    _add_constraint_if_missing_sql(
        "trading.approvals",
        APPROVER_USER_FK,
        "FOREIGN KEY (approver_user_id) REFERENCES system.users (id) ON DELETE RESTRICT",
    ),
    BACKFILL_APPROVER_USER_SQL,
    # --- trading.orders.approval_id ---
    "ALTER TABLE trading.orders ADD COLUMN IF NOT EXISTS approval_id UUID",
    BACKFILL_ORDER_APPROVAL_SQL,
    ORPHAN_ORDER_GUARD_SQL,
    "ALTER TABLE trading.orders ALTER COLUMN approval_id SET NOT NULL",
    _add_constraint_if_missing_sql(
        "trading.orders",
        ORDER_APPROVAL_UNIQUE,
        "UNIQUE (approval_id)",
    ),
    _add_constraint_if_missing_sql(
        "trading.orders",
        ORDER_APPROVAL_FK,
        "FOREIGN KEY (approval_id) REFERENCES trading.approvals (id) ON DELETE RESTRICT",
    ),
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"ALTER TABLE trading.orders DROP CONSTRAINT IF EXISTS {ORDER_APPROVAL_FK}",
    f"ALTER TABLE trading.orders DROP CONSTRAINT IF EXISTS {ORDER_APPROVAL_UNIQUE}",
    "ALTER TABLE trading.orders DROP COLUMN IF EXISTS approval_id",
    f"ALTER TABLE trading.approvals DROP CONSTRAINT IF EXISTS {APPROVER_USER_FK}",
    "ALTER TABLE trading.approvals DROP COLUMN IF EXISTS approver_user_id",
)


def upgrade() -> None:
    """Thêm cột/ràng buộc nếu thiếu, backfill order cũ, dừng rõ ràng nếu còn order mồ côi rồi mới đặt NOT NULL."""
    for statement in UPGRADE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    """Gỡ ràng buộc và cột đã thêm (mất liên kết order -> approval)."""
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(sa.text(statement))
