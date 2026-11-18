# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử migration 0002 (system.users + data-fix require_human_approval) ở chế độ offline SQL và online (SQLite).
# Lý do: Không có PostgreSQL trong unit test nên offline kiểm tra SQL phát ra; online kiểm tra logic tạo bảng idempotent.

import importlib.util
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.auth.models import User

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_DIR / "alembic" / "versions" / "0002_auth_users.py"


def _offline_sql(revision_range: str) -> str:
    # Config không có file ini để env.py không gọi fileConfig làm đổi cấu hình logging của pytest
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, revision_range, sql=True)
    return buffer.getvalue()


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0002", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_0002_does_not_emit_second_create_table_for_users() -> None:
    sql = _offline_sql("0001_initial_schemas:0002_auth_users")

    assert "CREATE TABLE system.users" not in sql
    assert "UPDATE system.risk_configs" in sql


def test_offline_full_upgrade_creates_users_table_exactly_once() -> None:
    sql = _offline_sql("base:head")

    assert sql.count("CREATE TABLE system.users") == 1


def test_offline_data_fix_forces_human_approval_idempotently_and_keeps_other_keys() -> None:
    sql = _offline_sql("0001_initial_schemas:0002_auth_users")

    assert "configuration || jsonb_build_object('require_human_approval', TRUE)" in sql
    assert "IS DISTINCT FROM 'true'::jsonb" in sql
    assert "jsonb_typeof(configuration) = 'object'" in sql
    # Chỉ UPDATE, không thay thế toàn bộ configuration bằng object mới (sẽ làm mất key khác)
    assert "SET configuration = '" not in sql


@pytest.fixture()
def sqlite_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"system": None}},
    )
    yield engine
    engine.dispose()


def test_online_create_users_if_missing_supports_old_and_new_databases(sqlite_engine) -> None:
    migration = _load_migration()

    # DB 0001 cũ chưa có users -> được tạo
    with sqlite_engine.begin() as conn:
        assert not inspect(conn).has_table("users")
        migration._create_users_table_if_missing(conn)
        assert inspect(conn).has_table("users")

    # DB mới đã có users (0001 tạo từ Base.metadata) -> chạy lại không lỗi và không mất dữ liệu
    with sqlite_engine.begin() as conn:
        conn.execute(
            User.__table__.insert().values(username="keep", password_hash="h", role="viewer")
        )
        migration._create_users_table_if_missing(conn)
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
