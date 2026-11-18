# Ngày tạo: 2026-11-17
# Mục đích: Thiết lập môi trường test chung và fixtures xác thực dùng lại cho các bộ test auth/RBAC.
# Lý do: Test chạy với APP_ENV=test, JWT secret test-only đặt tường minh tại đây (không có fallback trong app) và SQLite in-memory.

import os
import uuid
from datetime import datetime, timezone
from typing import Callable, Generator

# Phải đặt trước khi import app.* vì Settings được khởi tạo ngay khi import app.core.database.
# Ghi đè cả giá trị từ .env/môi trường của máy dev để test luôn tất định và không đụng secret thật.
TEST_JWT_SECRET = "Tq7#Zr4!Vk9@Wm2$Xd6&Hb3^Ns8*Lp5-Yc1+Ge0"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
# Test không bao giờ khởi động scheduler thật hay kiểm tra Host header, kể cả khi .env của máy dev bật các tính năng này.
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["TRUSTED_HOSTS"] = ""

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth.dependencies import get_current_user  # noqa: E402
from app.auth.models import User  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.core import clock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_PASSWORD = "Correct-Horse-Battery-9"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw) -> str:
    return "INTEGER"


@pytest.fixture(autouse=True)
def _default_admin_for_legacy_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Các test nghiệp vụ có sẵn không quan tâm tới đăng nhập: mọi TestClient tạo trong test được
    ghi đè `get_current_user` bằng admin giả lập. Test đánh dấu `real_auth` giữ nguyên xác thực thật.
    """
    if request.node.get_closest_marker("real_auth"):
        # Không bao giờ gọi LLM thật từ test, kể cả khi .env của máy dev bật AI
        settings = get_settings()
        monkeypatch.setattr(settings, "AI_ENABLED", False)
        monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
        monkeypatch.setattr(settings, "AI_MODEL", "mock-v1")
        monkeypatch.setattr(settings, "LLM_MODEL", "")
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        monkeypatch.setattr(settings, "AI_API_KEY", "")
        return

    stub_admin = User(
        id=uuid.uuid4(),
        username="legacy_test_admin",
        password_hash="",
        role="admin",
        is_active=True,
        token_version=0,
        failed_login_count=0,
        must_change_password=False,
    )
    original_init = TestClient.__init__

    def _init_with_admin(self, app, *args, **kwargs) -> None:
        original_init(self, app, *args, **kwargs)
        if isinstance(app, FastAPI):
            app.dependency_overrides.setdefault(get_current_user, lambda: stub_admin)

    monkeypatch.setattr(TestClient, "__init__", _init_with_admin)


@pytest.fixture()
def auth_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "market": None,
                "analysis": None,
                "strategy": None,
                "trading": None,
                "portfolio": None,
                "system": None,
            }
        },
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_app(auth_session: Session) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_db_session] = lambda: auth_session
    return application


@pytest.fixture()
def auth_client(auth_app: FastAPI) -> TestClient:
    return TestClient(auth_app)


class FakeClock:
    """Đồng hồ giả điều khiển `app.core.clock.utc_now` để test ngày thị trường/T+2 mà không phụ thuộc giờ máy."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(clock, "utc_now", lambda: self.now)

    def set_utc(self, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> None:
        self.now = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

    def set_market(self, year: int, month: int, day: int, hour: int = 10, minute: int = 0) -> None:
        """Đặt giờ theo múi giờ thị trường (Asia/Ho_Chi_Minh)."""
        local = datetime(year, month, day, hour, minute, tzinfo=clock.market_timezone())
        self.now = local.astimezone(timezone.utc)


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Mặc định thứ 2 2026-11-16 10:00 giờ Việt Nam."""
    return FakeClock(monkeypatch)


@pytest.fixture()
def create_user(auth_session: Session) -> Callable[..., User]:
    def _create(
        username: str,
        role: str = "viewer",
        password: str = TEST_PASSWORD,
        must_change_password: bool = False,
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            must_change_password=must_change_password,
        )
        auth_session.add(user)
        auth_session.commit()
        return user

    return _create


@pytest.fixture()
def login_headers(auth_client: TestClient) -> Callable[..., dict]:
    def _login(username: str, password: str = TEST_PASSWORD) -> dict:
        response = auth_client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
