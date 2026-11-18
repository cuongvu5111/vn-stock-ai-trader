# Ngày tạo: 2026-11-17
# Mục đích: Thêm UNIQUE `portfolio.accounts.account_name` để chỉ tồn tại đúng một `DEFAULT_PAPER_ACCOUNT`.
# Lý do: Khớp lệnh khóa dòng Account (`SELECT ... FOR UPDATE`) để tuần tự hóa cập nhật `cash_balance`; nếu cho phép hai dòng
#        cùng tên thì hai worker có thể khóa hai dòng khác nhau (hoặc cùng tạo tài khoản mặc định) và khóa mất tác dụng.
#        0001 dùng `Base.metadata.create_all` nên DB mới đã có sẵn ràng buộc này, còn DB cũ thì chưa; vì vậy câu lệnh tự kiểm
#        tra tồn tại ngay trong SQL (khối DO) và chạy đúng ở cả online lẫn offline (`--sql`), không phát sinh DDL trùng.
#        Nếu DB cũ đã có tên tài khoản trùng thì migration DỪNG với thông báo rõ ràng và KHÔNG tự gộp/xóa/đổi tên: tài khoản
#        được tham chiếu bởi `cash_transactions`, `positions`, `daily_snapshots` nên chỉ con người mới quyết định cách xử lý.

"""Unique portfolio.accounts.account_name

Revision ID: 0005_unique_account_name
Revises: 0004_execution_settlement
Create Date: 2026-11-17 11:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_unique_account_name"
down_revision: Union[str, None] = "0004_execution_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACCOUNT_NAME_UNIQUE = "uq_accounts_account_name"

# Message cố ý chỉ dùng ASCII để in được ở mọi console khi chạy `alembic upgrade --sql`.
DUPLICATE_ACCOUNT_GUARD_SQL = """
DO $$
DECLARE
    duplicate_count integer;
    duplicate_names text;
BEGIN
    SELECT count(*) INTO duplicate_count FROM (
        SELECT account_name FROM portfolio.accounts GROUP BY account_name HAVING count(*) > 1
    ) AS duplicated;
    IF duplicate_count > 0 THEN
        SELECT string_agg(sample.account_name || ' (x' || sample.account_count || ')', ', ') INTO duplicate_names
        FROM (
            SELECT account_name, count(*) AS account_count
            FROM portfolio.accounts
            GROUP BY account_name
            HAVING count(*) > 1
            ORDER BY account_name
            LIMIT 10
        ) AS sample;
        RAISE EXCEPTION USING
            ERRCODE = '23505',
            MESSAGE = 'Migration 0005_unique_account_name aborted: ' || duplicate_count
                || ' duplicated account_name value(s) in portfolio.accounts (sample: '
                || duplicate_names || ').',
            HINT = 'Review these accounts and the cash_transactions, positions and daily_snapshots that reference them, '
                || 'then merge or rename them manually and re-run. The migration never merges accounts.';
    END IF;
END
$$
"""

ADD_ACCOUNT_NAME_UNIQUE_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{ACCOUNT_NAME_UNIQUE}' AND conrelid = 'portfolio.accounts'::regclass
    ) THEN
        ALTER TABLE portfolio.accounts ADD CONSTRAINT {ACCOUNT_NAME_UNIQUE} UNIQUE (account_name);
    END IF;
END
$$
"""

UPGRADE_STATEMENTS: tuple[str, ...] = (
    DUPLICATE_ACCOUNT_GUARD_SQL,
    ADD_ACCOUNT_NAME_UNIQUE_SQL,
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"ALTER TABLE portfolio.accounts DROP CONSTRAINT IF EXISTS {ACCOUNT_NAME_UNIQUE}",
)


def upgrade() -> None:
    """Dừng rõ ràng nếu còn tên tài khoản trùng, rồi mới thêm UNIQUE (bỏ qua nếu 0001 đã tạo sẵn)."""
    for statement in UPGRADE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    """Gỡ UNIQUE `account_name`."""
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(sa.text(statement))
