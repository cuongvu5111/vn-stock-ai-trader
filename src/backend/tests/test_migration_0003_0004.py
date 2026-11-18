# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử migration 0003 (order.approval_id, approvals.approver_user_id) và 0004 (executions trade/settlement date).
#   - Offline (luôn chạy): kiểm tra SQL phát ra idempotent, không DDL trùng với 0001 (dùng Base.metadata hiện tại), đúng thứ tự
#     backfill -> kiểm tra orphan -> NOT NULL -> ràng buộc, và bảng ánh xạ T+2 khớp hàm Python.
#   - PostgreSQL thật (chỉ chạy khi đặt MIGRATION_TEST_POSTGRES_URL, ví dụ
#     postgresql+psycopg://postgres:<mật khẩu>@127.0.0.1:55432/postgres): nâng cấp DB cũ có dữ liệu, backfill, orphan fail rõ,
#     chạy lại SQL không đổi dữ liệu, downgrade/upgrade lại. Mỗi test dùng một database tạm riêng rồi xóa.

import importlib.util
import io
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import get_args
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.config import Settings, get_settings
from app.indicators.models import StockSignal
from app.market_data.models import Stock
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.settlement import add_trading_days
from test_migration_0002 import _offline_sql

BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
PG_URL = os.environ.get("MIGRATION_TEST_POSTGRES_URL")
REV_0002 = "0002_auth_users"
REV_0003 = "0003_order_approval_integrity"
REV_0004 = "0004_execution_settlement"
REV_0005 = "0005_unique_account_name"


def _load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION_0003 = _load_migration("0003_order_approval_integrity.py")
MIGRATION_0004 = _load_migration("0004_execution_settlement.py")


def _positions(sql: str, *needles: str) -> list[int]:
    found = []
    for needle in needles:
        assert needle in sql, f"thiếu: {needle}"
        found.append(sql.index(needle))
    return found


# --------------------------------------------------------------------------------------
# Offline SQL (luôn chạy)
# --------------------------------------------------------------------------------------


def test_revision_chain_is_0002_0003_0004() -> None:
    assert MIGRATION_0003.down_revision == REV_0002
    assert MIGRATION_0004.down_revision == REV_0003
    assert len(MIGRATION_0003.revision) <= 32 and len(MIGRATION_0004.revision) <= 32


def test_offline_0003_is_idempotent_and_orders_backfill_before_constraints() -> None:
    sql = _offline_sql(f"{REV_0002}:{REV_0003}")

    assert "ADD COLUMN IF NOT EXISTS approval_id UUID" in sql
    assert "ADD COLUMN IF NOT EXISTS approver_user_id UUID" in sql
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)
    for constraint in ("uq_orders_approval_id", "fk_orders_approval_id_approvals", "fk_approvals_approver_user_id_users"):
        assert f"conname = '{constraint}'" in sql
    assert "ON DELETE RESTRICT" in sql

    backfill, orphan_guard, not_null, unique, foreign_key = _positions(
        sql,
        "SET approval_id = a.id",
        "Migration 0003_order_approval_integrity aborted",
        "ALTER COLUMN approval_id SET NOT NULL",
        "ADD CONSTRAINT uq_orders_approval_id UNIQUE (approval_id)",
        "ADD CONSTRAINT fk_orders_approval_id_approvals FOREIGN KEY (approval_id)",
    )
    assert backfill < orphan_guard < not_null < unique
    assert backfill < orphan_guard < not_null < foreign_key


def test_offline_0003_backfill_only_uses_unambiguous_approved_approval_of_same_proposal() -> None:
    sql = _offline_sql(f"{REV_0002}:{REV_0003}")

    assert "a.proposal_id = o.proposal_id" in sql
    assert "a.decision = 'APPROVED'" in sql
    assert ") = 1" in sql  # đúng một approval APPROVED / một order cho mỗi proposal
    assert "NOT EXISTS (SELECT 1 FROM trading.orders AS o3 WHERE o3.approval_id = a.id)" in sql
    assert "u.username = lower(a.approved_by)" in sql


def test_offline_0004_backfills_market_dates_before_not_null() -> None:
    sql = _offline_sql(f"{REV_0003}:{REV_0004}")

    assert "ADD COLUMN IF NOT EXISTS trade_date DATE" in sql
    assert "ADD COLUMN IF NOT EXISTS settlement_date DATE" in sql
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)
    assert "executed_at AT TIME ZONE 'Asia/Ho_Chi_Minh'" in sql
    assert "EXTRACT(ISODOW FROM trade_date)" in sql
    assert "conname = 'ck_executions_settlement_after_trade'" in sql

    trade_backfill, settlement_backfill, trade_not_null, settlement_not_null, check = _positions(
        sql,
        "SET trade_date = (executed_at AT TIME ZONE",
        "SET settlement_date = trade_date +",
        "ALTER COLUMN trade_date SET NOT NULL",
        "ALTER COLUMN settlement_date SET NOT NULL",
        "ADD CONSTRAINT ck_executions_settlement_after_trade",
    )
    assert trade_backfill < settlement_backfill < trade_not_null < settlement_not_null < check


def test_offline_full_upgrade_does_not_duplicate_columns_created_by_0001_metadata() -> None:
    sql = _offline_sql("base:head")

    assert sql.count("CREATE TABLE trading.orders") == 1
    assert sql.count("CREATE TABLE trading.executions") == 1
    assert sql.count("CREATE TABLE trading.approvals") == 1
    # 0001 dùng metadata hiện tại nên đã có cột mới; 0003/0004 chỉ thêm khi thiếu (IF NOT EXISTS) và không CREATE lại
    assert "approval_id UUID NOT NULL" in sql
    assert "trade_date DATE NOT NULL" in sql
    assert not re.search(r"ADD COLUMN (?!IF NOT EXISTS)", sql)
    assert _positions(sql, "CREATE TABLE trading.orders", "SET approval_id = a.id")[0] < sql.index(
        "SET approval_id = a.id"
    )


def test_offline_downgrade_drops_only_if_exists() -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.downgrade(cfg, f"{REV_0004}:{REV_0002}", sql=True)
    sql = buffer.getvalue()

    assert "DROP COLUMN IF EXISTS settlement_date" in sql
    assert "DROP COLUMN IF EXISTS approval_id" in sql
    assert "DROP CONSTRAINT IF EXISTS fk_orders_approval_id_approvals" in sql


def test_migration_market_timezone_is_the_only_value_settings_accepts() -> None:
    allowed = get_args(Settings.model_fields["MARKET_TIMEZONE"].annotation)

    assert allowed == (MIGRATION_0004.MARKET_TIMEZONE,) == ("Asia/Ho_Chi_Minh",)
    assert get_settings().MARKET_TIMEZONE == MIGRATION_0004.MARKET_TIMEZONE


def test_t_plus_2_calendar_offsets_match_python_function() -> None:
    offsets = MIGRATION_0004.T_PLUS_2_CALENDAR_DAYS_BY_ISODOW
    start = date(2026, 1, 1)

    for i in range(400):
        day = start + timedelta(days=i)
        assert day + timedelta(days=offsets[day.isoweekday()]) == add_trading_days(day, 2), day


# --------------------------------------------------------------------------------------
# PostgreSQL thật (tùy chọn)
# --------------------------------------------------------------------------------------

requires_pg = pytest.mark.skipif(not PG_URL, reason="Đặt MIGRATION_TEST_POSTGRES_URL để chạy test migration trên PostgreSQL thật")


def make_url_with_database(url: str, database: str | None) -> str:
    parsed = make_url(url)
    return parsed.set(database=database or parsed.database).render_as_string(hide_password=False)


@pytest.fixture()
def pg_db(monkeypatch):
    """Tạo database tạm, trỏ Alembic (env.py đọc DATABASE_URL_OVERRIDE) vào đó và xóa sau test."""
    admin_url = make_url_with_database(PG_URL, None)
    name = f"mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url_with_database(PG_URL, name)
    monkeypatch.setattr(get_settings(), "DATABASE_URL_OVERRIDE", url)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _columns(engine, table: str) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns(table, schema="trading")}


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _constraint_names(engine, table: str) -> set[str]:
    insp = inspect(engine)
    names = {c["name"] for c in insp.get_unique_constraints(table, schema="trading")}
    names |= {c["name"] for c in insp.get_foreign_keys(table, schema="trading")}
    names |= {c["name"] for c in insp.get_check_constraints(table, schema="trading")}
    return names


def _downgrade_to_legacy_schema(engine) -> None:
    """DB ở revision 0002 với schema cũ (chưa có cột/ràng buộc mới) để mô phỏng dữ liệu trước khi nâng cấp."""
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), REV_0002)
    assert "approval_id" not in _columns(engine, "orders")
    assert "trade_date" not in _columns(engine, "executions")


class LegacyData:
    """Dữ liệu lịch sử tạo bằng Core insert chỉ với các cột của schema cũ."""

    def __init__(self, engine) -> None:
        self.engine = engine
        with Session(engine) as session:
            stock = Stock(symbol="FPT", exchange="HOSE", company_name="[SAMPLE] FPT")
            session.add(stock)
            session.flush()
            self.signal = StockSignal(
                stock_id=stock.id,
                trading_date=date(2026, 11, 13),
                action="BUY",
                reason={"reasons": ["SAMPLE"]},
                status="GENERATED",
            )
            session.add_all([self.signal, User(username="cuong_trader", password_hash="x", role="trader")])
            session.flush()
            self.user_id = session.scalar(text("SELECT id FROM system.users WHERE username = 'cuong_trader'"))
            session.commit()
            self.signal_id = self.signal.id

    def proposal(self, symbol: str = "FPT") -> uuid.UUID:
        proposal_id = uuid.uuid4()
        with Session(self.engine) as session:
            session.add(
                TradeProposal(
                    id=proposal_id,
                    signal_id=self.signal_id,
                    symbol=symbol,
                    side="BUY",
                    proposed_quantity=200,
                    limit_price=Decimal("25000"),
                    status="Submitted",
                    expires_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()
        return proposal_id

    def approval(self, proposal_id: uuid.UUID, decision: str = "APPROVED", approved_by: str = "cuong_trader") -> uuid.UUID:
        approval_id = uuid.uuid4()
        with self.engine.begin() as conn:
            conn.execute(
                insert(Approval.__table__).values(
                    id=approval_id, proposal_id=proposal_id, decision=decision, approved_by=approved_by
                )
            )
        return approval_id

    def order(self, proposal_id: uuid.UUID | None, suffix: str) -> uuid.UUID:
        order_id = uuid.uuid4()
        with self.engine.begin() as conn:
            conn.execute(
                insert(Order.__table__).values(
                    id=order_id,
                    proposal_id=proposal_id,
                    client_order_id=f"LEGACY-{suffix}",
                    symbol="FPT",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=200,
                    status="Submitted",
                )
            )
        return order_id

    def execution(self, order_id: uuid.UUID, executed_at: datetime) -> uuid.UUID:
        execution_id = uuid.uuid4()
        with self.engine.begin() as conn:
            conn.execute(
                insert(Execution.__table__).values(
                    id=execution_id,
                    order_id=order_id,
                    execution_id=f"EXEC-{execution_id.hex[:12]}",
                    quantity=100,
                    price=Decimal("25000"),
                    fee=Decimal("0"),
                    tax=Decimal("0"),
                    executed_at=executed_at,
                )
            )
        return execution_id


@requires_pg
def test_pg_fresh_install_has_constraints_and_rerunning_migration_sql_is_noop(pg_db) -> None:
    command.upgrade(_cfg(), "head")

    orders = _columns(pg_db, "orders")
    assert orders["approval_id"]["nullable"] is False
    assert {"uq_orders_approval_id", "fk_orders_approval_id_approvals"} <= _constraint_names(pg_db, "orders")
    assert "fk_approvals_approver_user_id_users" in _constraint_names(pg_db, "approvals")
    assert _columns(pg_db, "approvals")["approver_user_id"]["nullable"] is True
    executions = _columns(pg_db, "executions")
    assert executions["trade_date"]["nullable"] is False and executions["settlement_date"]["nullable"] is False
    assert "ck_executions_settlement_after_trade" in _constraint_names(pg_db, "executions")
    assert _revision(pg_db) == REV_0005

    # Chạy lại toàn bộ SQL của 0003/0004 trên DB đã nâng cấp phải không lỗi và không đổi schema
    with pg_db.begin() as conn:
        for statement in (*MIGRATION_0003.UPGRADE_STATEMENTS, *MIGRATION_0004.UPGRADE_STATEMENTS):
            conn.execute(text(statement))
    assert _columns(pg_db, "orders")["approval_id"]["nullable"] is False
    assert _constraint_names(pg_db, "orders") >= {"uq_orders_approval_id", "fk_orders_approval_id_approvals"}


@requires_pg
def test_pg_legacy_upgrade_backfills_approval_user_and_market_dates(pg_db) -> None:
    _downgrade_to_legacy_schema(pg_db)
    legacy = LegacyData(pg_db)

    proposal_1 = legacy.proposal()
    approved_1 = legacy.approval(proposal_1, approved_by="cuong_trader")
    legacy.approval(proposal_1, decision="REJECTED", approved_by="cuong_trader")
    order_1 = legacy.order(proposal_1, "1")

    proposal_2 = legacy.proposal()
    approved_2 = legacy.approval(proposal_2, approved_by="Cuong_Trader")
    order_2 = legacy.order(proposal_2, "2")

    ghost_proposal = legacy.proposal()
    ghost_approval = legacy.approval(ghost_proposal, approved_by="ghost_actor")
    order_3 = legacy.order(ghost_proposal, "3")

    executed_at_values = [
        datetime(2026, 11, 13, 17, 30, tzinfo=timezone.utc),  # 00:30 thứ 7 giờ VN
        datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc),  # thứ 2
        datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),  # thứ 5
        datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc),  # thứ 6
        datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc),  # 03:00 Chủ nhật giờ VN
        datetime(2026, 11, 17, 16, 59, tzinfo=timezone.utc),  # 23:59 thứ 3 giờ VN
        datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc),  # 00:00 thứ 4 giờ VN
    ]
    execution_ids = [legacy.execution(order_1, ts) for ts in executed_at_values]

    command.upgrade(_cfg(), "head")

    with pg_db.connect() as conn:
        order_links = dict(conn.execute(text("SELECT id, approval_id FROM trading.orders")).all())
        approver_links = dict(conn.execute(text("SELECT id, approver_user_id FROM trading.approvals")).all())
        dates = {
            row.id: (row.trade_date, row.settlement_date)
            for row in conn.execute(text("SELECT id, trade_date, settlement_date FROM trading.executions"))
        }
    assert order_links == {order_1: approved_1, order_2: approved_2, order_3: ghost_approval}
    assert approver_links[approved_1] == legacy.user_id
    assert approver_links[approved_2] == legacy.user_id
    assert approver_links[ghost_approval] is None
    assert _columns(pg_db, "orders")["approval_id"]["nullable"] is False

    for execution_id, executed_at in zip(execution_ids, executed_at_values):
        trade_date = executed_at.astimezone(MARKET_TZ).date()
        assert dates[execution_id] == (trade_date, add_trading_days(trade_date, 2)), executed_at
    assert dates[execution_ids[0]] == (date(2026, 11, 14), date(2026, 11, 17))
    assert dates[execution_ids[5]] == (date(2026, 11, 17), date(2026, 11, 19))
    assert dates[execution_ids[6]] == (date(2026, 11, 18), date(2026, 11, 20))

    with pg_db.begin() as conn:
        snapshot = conn.execute(text("SELECT id, approval_id FROM trading.orders ORDER BY id")).all()
        for statement in (*MIGRATION_0003.UPGRADE_STATEMENTS, *MIGRATION_0004.UPGRADE_STATEMENTS):
            conn.execute(text(statement))
        assert conn.execute(text("SELECT id, approval_id FROM trading.orders ORDER BY id")).all() == snapshot


@requires_pg
@pytest.mark.parametrize("scenario", ["no_proposal", "only_rejected", "two_approved", "two_orders_one_proposal"])
def test_pg_orphan_orders_abort_migration_without_guessing(pg_db, scenario) -> None:
    _downgrade_to_legacy_schema(pg_db)
    legacy = LegacyData(pg_db)
    proposal = legacy.proposal()
    if scenario == "no_proposal":
        orphan = legacy.order(None, "orphan")
    elif scenario == "only_rejected":
        legacy.approval(proposal, decision="REJECTED")
        orphan = legacy.order(proposal, "orphan")
    elif scenario == "two_approved":
        legacy.approval(proposal)
        legacy.approval(proposal)
        orphan = legacy.order(proposal, "orphan")
    else:
        legacy.approval(proposal)
        legacy.order(proposal, "first")
        orphan = legacy.order(proposal, "second")

    with pytest.raises(DBAPIError) as exc_info:
        command.upgrade(_cfg(), "head")

    message = str(exc_info.value)
    assert "Migration 0003_order_approval_integrity aborted" in message
    if scenario != "two_orders_one_proposal":
        assert str(orphan) in message
    # Toàn bộ nâng cấp bị rollback: DB vẫn ở 0002 và chưa có cột mới
    assert _revision(pg_db) == REV_0002
    assert "approval_id" not in _columns(pg_db, "orders")
    assert "trade_date" not in _columns(pg_db, "executions")


@requires_pg
def test_pg_downgrade_then_upgrade_restores_schema(pg_db) -> None:
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), REV_0003)
    assert "trade_date" not in _columns(pg_db, "executions")
    assert "approval_id" in _columns(pg_db, "orders")

    command.downgrade(_cfg(), REV_0002)
    assert "approval_id" not in _columns(pg_db, "orders")
    assert "approver_user_id" not in _columns(pg_db, "approvals")

    command.upgrade(_cfg(), "head")
    assert _columns(pg_db, "orders")["approval_id"]["nullable"] is False
    assert _revision(pg_db) == REV_0005


@requires_pg
def test_pg_sql_settlement_case_matches_python_calendar(pg_db) -> None:
    case_sql = MIGRATION_0004._settlement_offset_case_sql()
    query = (
        "SELECT trade_date, trade_date + (" + case_sql + ") FROM "
        "(SELECT generate_series(date '2026-01-01', date '2026-12-31', interval '1 day')::date AS trade_date) AS days"
    )
    with pg_db.connect() as conn:
        rows = conn.execute(text(query)).all()

    assert len(rows) == 365
    for trade_date, settlement_date in rows:
        assert settlement_date == add_trading_days(trade_date, 2), trade_date
