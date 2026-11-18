# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử migration 0005 (UNIQUE `portfolio.accounts.account_name`).
#   - Offline (luôn chạy): SQL phát ra idempotent (khối DO kiểm tra pg_constraint), guard trùng tên chạy TRƯỚC khi thêm ràng
#     buộc, không có DDL trùng với 0001 (0001 dùng `Base.metadata` hiện tại nên DB mới đã có sẵn ràng buộc), model khai báo
#     đúng ràng buộc tương ứng.
#   - PostgreSQL thật (chỉ chạy khi đặt MIGRATION_TEST_POSTGRES_URL): DB mới đã có ràng buộc, DB cũ (0004, chưa có ràng buộc)
#     được nâng cấp, tên trùng làm migration dừng rõ ràng và KHÔNG tự gộp/xóa dữ liệu, chạy lại SQL không đổi gì, downgrade/upgrade.
# Lý do: Khóa Account FOR UPDATE chỉ đúng khi chỉ có một DEFAULT_PAPER_ACCOUNT.

import io
import re
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import UniqueConstraint, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.portfolio.models import Account
from test_migration_0002 import _offline_sql
from test_migration_0003_0004 import (
    REV_0004,
    VERSIONS_DIR,
    _cfg,
    _load_migration,
    _positions,
    _revision,
    pg_db,  # noqa: F401  (fixture)
    requires_pg,
)

REV_0005 = "0005_unique_account_name"
CONSTRAINT = "uq_accounts_account_name"
MIGRATION_0005 = _load_migration("0005_unique_account_name.py")


def _unique_names(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_unique_constraints("accounts", schema="portfolio")}


def _insert_account(conn, name: str, cash: str = "1000.00") -> None:
    conn.execute(
        text(
            "INSERT INTO portfolio.accounts (id, account_name, initial_capital, cash_balance, currency, account_type, "
            "created_at) VALUES (gen_random_uuid(), :name, :cash, :cash, 'VND', 'PAPER', now())"
        ),
        {"name": name, "cash": Decimal(cash)},
    )


# --------------------------------------------------------------------------------------
# Offline / metadata (luôn chạy)
# --------------------------------------------------------------------------------------


def test_revision_chain_0004_to_0005() -> None:
    assert MIGRATION_0005.revision == REV_0005 and len(REV_0005) <= 32
    assert MIGRATION_0005.down_revision == REV_0004
    assert (VERSIONS_DIR / "0005_unique_account_name.py").exists()


def test_model_declares_the_same_unique_constraint_the_migration_adds() -> None:
    unique_columns = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in Account.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert unique_columns == {CONSTRAINT: ["account_name"]}
    assert MIGRATION_0005.ACCOUNT_NAME_UNIQUE == CONSTRAINT


def test_offline_0005_is_idempotent_and_guards_duplicates_before_adding_constraint() -> None:
    sql = _offline_sql(f"{REV_0004}:{REV_0005}")

    assert f"conname = '{CONSTRAINT}'" in sql and "conrelid = 'portfolio.accounts'::regclass" in sql
    guard, add = _positions(
        sql,
        "Migration 0005_unique_account_name aborted",
        f"ADD CONSTRAINT {CONSTRAINT} UNIQUE (account_name)",
    )
    assert guard < add
    assert "HAVING count(*) > 1" in sql
    assert "ERRCODE = '23505'" in sql
    # Không tự gộp/xóa/đổi tên dữ liệu trùng: migration không có câu DML nào trên portfolio.*
    assert not re.search(r"\b(UPDATE|DELETE FROM|INSERT INTO)\s+portfolio\.", sql)


def test_offline_full_upgrade_keeps_0001_unique_and_guards_it_again_in_0005() -> None:
    sql = _offline_sql("base:head")

    assert sql.count("CREATE TABLE portfolio.accounts") == 1
    assert f"CONSTRAINT {CONSTRAINT} UNIQUE (account_name)" in sql  # 0001 dùng metadata hiện tại
    created_by_0001, guarded_by_0005 = _positions(
        sql,
        f"CONSTRAINT {CONSTRAINT} UNIQUE (account_name)",
        f"conname = '{CONSTRAINT}'",
    )
    assert created_by_0001 < guarded_by_0005
    assert sql.count(f"ADD CONSTRAINT {CONSTRAINT}") == 1  # chỉ trong khối DO ... IF NOT EXISTS của 0005


def test_offline_0005_downgrade_drops_only_if_exists() -> None:
    cfg = _cfg()
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.downgrade(cfg, f"{REV_0005}:{REV_0004}", sql=True)

    assert f"DROP CONSTRAINT IF EXISTS {CONSTRAINT}" in buffer.getvalue()


# --------------------------------------------------------------------------------------
# PostgreSQL thật (tùy chọn)
# --------------------------------------------------------------------------------------


@requires_pg
def test_pg_fresh_install_has_unique_constraint_and_duplicates_are_rejected(pg_db) -> None:  # noqa: F811
    command.upgrade(_cfg(), "head")

    assert CONSTRAINT in _unique_names(pg_db)
    assert _revision(pg_db) == REV_0005
    with pytest.raises(IntegrityError):
        with pg_db.begin() as conn:
            _insert_account(conn, "DEFAULT_PAPER_ACCOUNT")
            _insert_account(conn, "DEFAULT_PAPER_ACCOUNT")

    with pg_db.begin() as conn:  # chạy lại SQL của 0005 trên DB đã nâng cấp: không lỗi, không đổi schema
        for statement in MIGRATION_0005.UPGRADE_STATEMENTS:
            conn.execute(text(statement))
    assert CONSTRAINT in _unique_names(pg_db)


@requires_pg
def test_pg_legacy_database_without_constraint_is_upgraded_and_data_is_kept(pg_db) -> None:  # noqa: F811
    command.upgrade(_cfg(), REV_0004)
    with pg_db.begin() as conn:
        conn.execute(text(f"ALTER TABLE portfolio.accounts DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
        _insert_account(conn, "DEFAULT_PAPER_ACCOUNT", cash="123.45")
        _insert_account(conn, "OTHER_ACCOUNT", cash="1.00")
    assert CONSTRAINT not in _unique_names(pg_db)

    command.upgrade(_cfg(), "head")

    assert CONSTRAINT in _unique_names(pg_db)
    assert _revision(pg_db) == REV_0005
    with pg_db.connect() as conn:
        rows = conn.execute(text("SELECT account_name, cash_balance FROM portfolio.accounts ORDER BY 1")).all()
    assert rows == [("DEFAULT_PAPER_ACCOUNT", Decimal("123.45")), ("OTHER_ACCOUNT", Decimal("1.00"))]


@requires_pg
def test_pg_duplicate_account_names_abort_migration_without_merging_anything(pg_db) -> None:  # noqa: F811
    command.upgrade(_cfg(), REV_0004)
    with pg_db.begin() as conn:
        conn.execute(text(f"ALTER TABLE portfolio.accounts DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
        _insert_account(conn, "DEFAULT_PAPER_ACCOUNT", cash="100.00")
        _insert_account(conn, "DEFAULT_PAPER_ACCOUNT", cash="200.00")
        _insert_account(conn, "UNIQUE_ONE")

    with pytest.raises(DBAPIError) as exc_info:
        command.upgrade(_cfg(), "head")

    message = str(exc_info.value)
    assert "Migration 0005_unique_account_name aborted" in message
    assert "DEFAULT_PAPER_ACCOUNT (x2)" in message
    assert "never merges accounts" in message
    assert _revision(pg_db) == REV_0004
    assert CONSTRAINT not in _unique_names(pg_db)
    with pg_db.connect() as conn:
        rows = conn.execute(text("SELECT account_name, cash_balance FROM portfolio.accounts ORDER BY 1, 2")).all()
    assert rows == [
        ("DEFAULT_PAPER_ACCOUNT", Decimal("100.00")),
        ("DEFAULT_PAPER_ACCOUNT", Decimal("200.00")),
        ("UNIQUE_ONE", Decimal("1000.00")),
    ]


@requires_pg
def test_pg_downgrade_then_upgrade_restores_unique_constraint(pg_db) -> None:  # noqa: F811
    command.upgrade(_cfg(), "head")

    command.downgrade(_cfg(), REV_0004)
    assert CONSTRAINT not in _unique_names(pg_db)
    assert _revision(pg_db) == REV_0004

    command.upgrade(_cfg(), "head")
    assert CONSTRAINT in _unique_names(pg_db)
    assert _revision(pg_db) == REV_0005
