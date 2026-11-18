# Ngày tạo: 2026-11-17
# Mục đích: Thêm `trade_date` và `settlement_date` (DATE) vào `trading.executions` để suy dẫn số lượng khả dụng theo T+2.
# Lý do: 0001 dùng `Base.metadata.create_all` nên DB mới đã có sẵn hai cột này, còn DB cũ thì chưa. Mọi câu lệnh tự kiểm tra
#        tồn tại trong SQL (`IF NOT EXISTS`/khối DO) nên chạy đúng ở cả online lẫn offline (`--sql`), không phát sinh DDL trùng.
#        Dữ liệu lịch sử được backfill cố định theo T+2 (không đọc cấu hình môi trường) để migration luôn tất định;
#        `SETTLEMENT_LAG_TRADING_DAYS` chỉ áp dụng cho các lần khớp mới.

"""Execution trade_date and settlement_date

Revision ID: 0004_execution_settlement
Revises: 0003_order_approval_integrity
Create Date: 2026-11-17 10:45:00
"""

from typing import Dict, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_execution_settlement"
down_revision: Union[str, None] = "0003_order_approval_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Hardcode có chủ đích: `Settings.MARKET_TIMEZONE` chỉ chấp nhận đúng giá trị này nên migration và runtime không thể lệch (có test đối chiếu).
MARKET_TIMEZONE = "Asia/Ho_Chi_Minh"
SETTLEMENT_CHECK = "ck_executions_settlement_after_trade"

# ISODOW (1=thứ 2 .. 7=Chủ nhật) -> số ngày lịch cần cộng để được T+2 ngày làm việc, bỏ thứ 7/Chủ nhật.
# Phải khớp `app.trading.settlement.add_trading_days(day, 2)` (có test đối chiếu).
T_PLUS_2_CALENDAR_DAYS_BY_ISODOW: Dict[int, int] = {1: 2, 2: 2, 3: 2, 4: 4, 5: 4, 6: 3, 7: 2}


def _settlement_offset_case_sql() -> str:
    branches = " ".join(
        f"WHEN {isodow} THEN {days}" for isodow, days in T_PLUS_2_CALENDAR_DAYS_BY_ISODOW.items()
    )
    return f"CASE EXTRACT(ISODOW FROM trade_date)::int {branches} END"


BACKFILL_TRADE_DATE_SQL = f"""
UPDATE trading.executions
SET trade_date = (executed_at AT TIME ZONE '{MARKET_TIMEZONE}')::date
WHERE trade_date IS NULL
"""

BACKFILL_SETTLEMENT_DATE_SQL = f"""
UPDATE trading.executions
SET settlement_date = trade_date + ({_settlement_offset_case_sql()})
WHERE settlement_date IS NULL
"""

ADD_SETTLEMENT_CHECK_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{SETTLEMENT_CHECK}' AND conrelid = 'trading.executions'::regclass
    ) THEN
        ALTER TABLE trading.executions
            ADD CONSTRAINT {SETTLEMENT_CHECK} CHECK (settlement_date >= trade_date);
    END IF;
END
$$
"""

UPGRADE_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE trading.executions ADD COLUMN IF NOT EXISTS trade_date DATE",
    "ALTER TABLE trading.executions ADD COLUMN IF NOT EXISTS settlement_date DATE",
    BACKFILL_TRADE_DATE_SQL,
    BACKFILL_SETTLEMENT_DATE_SQL,
    "ALTER TABLE trading.executions ALTER COLUMN trade_date SET NOT NULL",
    "ALTER TABLE trading.executions ALTER COLUMN settlement_date SET NOT NULL",
    ADD_SETTLEMENT_CHECK_SQL,
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    f"ALTER TABLE trading.executions DROP CONSTRAINT IF EXISTS {SETTLEMENT_CHECK}",
    "ALTER TABLE trading.executions DROP COLUMN IF EXISTS settlement_date",
    "ALTER TABLE trading.executions DROP COLUMN IF EXISTS trade_date",
)


def upgrade() -> None:
    """Thêm hai cột nếu thiếu, backfill lịch sử theo giờ thị trường rồi mới đặt NOT NULL và CHECK."""
    for statement in UPGRADE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    """Gỡ CHECK và hai cột ngày giao dịch/thanh toán."""
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(sa.text(statement))
