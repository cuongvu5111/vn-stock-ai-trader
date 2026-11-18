# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử xác thực: login, khóa tài khoản, thu hồi token, đổi mật khẩu, quản lý user, cấu hình bảo mật.

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.auth.security import create_access_token, hash_password
from app.auth.service import GENERIC_LOGIN_ERROR, as_utc, ensure_bootstrap_admin
from app.core.config import InsecureConfigurationError, Settings, get_settings
from app.main import create_app
from app.system.models import AuditLog
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.real_auth


def _audit_actions(session, action: str) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.action == action)).all())


def test_login_success_returns_token_without_secrets(auth_client, auth_session, create_user) -> None:
    create_user("alice", "trader")

    resp = auth_client.post("/api/v1/auth/login", json={"username": " Alice ", "password": TEST_PASSWORD})

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "trader"
    assert not {"password", "password_hash"} & set(body["user"])
    assert "password_hash" not in resp.text
    assert TEST_PASSWORD not in resp.text

    me = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert not {"password", "password_hash"} & set(me.json())

    logs = _audit_actions(auth_session, "AUTH_LOGIN_SUCCESS")
    assert len(logs) == 1 and logs[0].actor == "alice"
    assert body["access_token"] not in str(logs[0].after_state)
    user = auth_session.scalar(select(User).where(User.username == "alice"))
    assert user.last_login_at is not None
    assert as_utc(user.last_login_at).tzinfo is not None


def test_login_wrong_password_and_unknown_user_are_indistinguishable_and_audited(
    auth_client, auth_session, create_user
) -> None:
    create_user("alice", "trader")

    wrong = auth_client.post("/api/v1/auth/login", json={"username": "alice", "password": "sai-mat-khau-1"})
    unknown = auth_client.post("/api/v1/auth/login", json={"username": "ghost", "password": "sai-mat-khau-1"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"] == GENERIC_LOGIN_ERROR
    assert wrong.headers.get("WWW-Authenticate") == "Bearer"

    failed = _audit_actions(auth_session, "AUTH_LOGIN_FAILED")
    assert {a.actor for a in failed} == {"alice", "anonymous"}
    serialized = str([a.after_state for a in failed])
    assert "ghost" not in serialized and "sai-mat-khau-1" not in serialized
    assert auth_session.scalar(select(User).where(User.username == "alice")).failed_login_count == 1


def test_account_lockout_after_repeated_failures_and_recovery(
    auth_client, auth_session, create_user, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "AUTH_MAX_FAILED_LOGINS", 3)
    user = create_user("alice", "trader")

    for _ in range(3):
        assert auth_client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": "sai-mat-khau-1"}
        ).status_code == 401

    auth_session.refresh(user)
    assert user.locked_until is not None
    assert as_utc(user.locked_until) > datetime.now(timezone.utc)

    # Đang khóa: mật khẩu đúng vẫn bị từ chối bằng cùng thông điệp chung
    locked = auth_client.post("/api/v1/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    assert locked.status_code == 401
    assert locked.json()["error"]["message"] == GENERIC_LOGIN_ERROR
    reasons = [a.after_state["reason"] for a in _audit_actions(auth_session, "AUTH_LOGIN_FAILED")]
    assert "account_locked" in reasons

    # Hết thời gian khóa: đăng nhập lại được và bộ đếm được reset
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    auth_session.commit()
    ok = auth_client.post("/api/v1/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    assert ok.status_code == 200
    auth_session.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


def test_locked_account_with_valid_jwt_cannot_attempt_password_change(
    auth_client, auth_session, create_user, login_headers, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "AUTH_MAX_FAILED_LOGINS", 3)
    user = create_user("alice", "trader")
    headers = login_headers("alice")

    locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    user.failed_login_count = 3
    user.locked_until = locked_until
    auth_session.commit()
    token_version = user.token_version
    old_hash = user.password_hash
    new_password = "Mat-Khau-Moi-Rat-Dai-1"

    # Đúng hay sai mật khẩu hiện tại đều bị chặn trước verify: không đổi mật khẩu, không dò được, không đổi bộ đếm/khóa
    for current in (TEST_PASSWORD, "sai-mat-khau-1"):
        resp = auth_client.post(
            "/api/v1/auth/change-password",
            json={"current_password": current, "new_password": new_password},
            headers=headers,
        )
        assert resp.status_code == 423
        auth_session.refresh(user)
        assert user.password_hash == old_hash and user.token_version == token_version
        assert user.failed_login_count == 3
        assert as_utc(user.locked_until) == as_utc(locked_until)

    reasons = [a.after_state["reason"] for a in _audit_actions(auth_session, "AUTH_PASSWORD_CHANGE_FAILED")]
    assert reasons == ["account_locked", "account_locked"]
    assert not _audit_actions(auth_session, "AUTH_PASSWORD_CHANGED")

    # Hết khóa: bộ đếm được reset rồi mới tính lần sai mới (1), không cộng dồn từ lần khóa cũ
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    auth_session.commit()
    wrong = auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "sai-mat-khau-1", "new_password": new_password},
        headers=headers,
    )
    assert wrong.status_code == 400
    auth_session.refresh(user)
    assert user.failed_login_count == 1 and user.locked_until is None

def test_inactive_user_cannot_login_and_deactivation_revokes_existing_token(
    auth_client, auth_session, create_user, login_headers
) -> None:
    create_user("boss", "admin")
    target = create_user("alice", "trader")
    admin_headers = login_headers("boss")
    alice_headers = login_headers("alice")
    assert auth_client.get("/api/v1/portfolio", headers=alice_headers).status_code == 200

    resp = auth_client.patch(
        f"/api/v1/auth/users/{target.id}", json={"is_active": False}, headers=admin_headers
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    assert auth_client.get("/api/v1/portfolio", headers=alice_headers).status_code == 401
    login = auth_client.post("/api/v1/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    assert login.status_code == 401
    reasons = [a.after_state["reason"] for a in _audit_actions(auth_session, "AUTH_LOGIN_FAILED")]
    assert "account_inactive" in reasons


def test_invalid_expired_and_forged_tokens_are_rejected(auth_client, create_user) -> None:
    user = create_user("alice", "trader")
    settings = get_settings()

    expired, _ = create_access_token(
        settings, user.id, user.token_version, now=datetime.now(timezone.utc) - timedelta(hours=3)
    )
    forged = jwt.encode(
        {"sub": str(user.id), "ver": 0, "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "khoa-bi-mat-sai-" * 4,
        algorithm="HS256",
    )
    unsigned = jwt.encode({"sub": str(user.id), "ver": 0}, key="", algorithm="none")

    for token in (expired, forged, unsigned, "khong.phai.jwt"):
        resp = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, token

    assert auth_client.get("/api/v1/auth/me").status_code == 401
    assert auth_client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_change_password_revokes_tokens_and_clears_must_change_flag(
    auth_client, auth_session, create_user, login_headers
) -> None:
    create_user("alice", "trader", must_change_password=True)
    headers = login_headers("alice")

    # Đang bị buộc đổi mật khẩu: endpoint nghiệp vụ bị chặn, /me và change-password vẫn dùng được
    blocked = auth_client.get("/api/v1/portfolio", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert auth_client.get("/api/v1/auth/me", headers=headers).json()["must_change_password"] is True

    wrong = auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "sai-mat-khau-1", "new_password": "Mat-Khau-Moi-Rat-Dai-1"},
        headers=headers,
    )
    assert wrong.status_code == 400
    same = auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
        headers=headers,
    )
    assert same.status_code == 400
    short = auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "ngan"},
        headers=headers,
    )
    assert short.status_code == 422

    new_password = "Mat-Khau-Moi-Rat-Dai-1"
    ok = auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": new_password},
        headers=headers,
    )
    assert ok.status_code == 200
    assert new_password not in ok.text

    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert auth_client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": TEST_PASSWORD}
    ).status_code == 401
    new_headers = login_headers("alice", new_password)
    assert auth_client.get("/api/v1/portfolio", headers=new_headers).status_code == 200

    assert len(_audit_actions(auth_session, "AUTH_PASSWORD_CHANGED")) == 1
    assert len(_audit_actions(auth_session, "AUTH_PASSWORD_CHANGE_FAILED")) == 1
    audit_dump = str([(a.before_state, a.after_state) for a in auth_session.scalars(select(AuditLog)).all()])
    assert new_password not in audit_dump and TEST_PASSWORD not in audit_dump


def test_admin_user_management_lifecycle(auth_client, auth_session, create_user, login_headers) -> None:
    admin = create_user("boss", "admin")
    admin_headers = login_headers("boss")

    created = auth_client.post(
        "/api/v1/auth/users",
        json={"username": "  Bob.Trader ", "password": "Mat-Khau-Cua-Bob-1", "role": "trader"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["username"] == "bob.trader" and body["role"] == "trader"
    assert body["must_change_password"] is True
    assert not {"password", "password_hash"} & set(body)
    assert "Mat-Khau-Cua-Bob-1" not in created.text

    duplicate = auth_client.post(
        "/api/v1/auth/users",
        json={"username": "BOB.TRADER", "password": "Mat-Khau-Cua-Bob-1"},
        headers=admin_headers,
    )
    assert duplicate.status_code == 409
    bad_name = auth_client.post(
        "/api/v1/auth/users",
        json={"username": "bad name!", "password": "Mat-Khau-Cua-Bob-1"},
        headers=admin_headers,
    )
    assert bad_name.status_code == 422
    bad_role = auth_client.post(
        "/api/v1/auth/users",
        json={"username": "eve", "password": "Mat-Khau-Cua-Bob-1", "role": "superuser"},
        headers=admin_headers,
    )
    assert bad_role.status_code == 422

    listing = auth_client.get("/api/v1/auth/users", headers=admin_headers)
    assert listing.status_code == 200
    assert [u["username"] for u in listing.json()["items"]] == ["bob.trader", "boss"]

    # Đổi vai trò + reset mật khẩu thu hồi token cũ của người bị tác động
    bob_id = body["id"]
    bob_headers = login_headers("bob.trader", "Mat-Khau-Cua-Bob-1")
    patched = auth_client.patch(
        f"/api/v1/auth/users/{bob_id}",
        json={"role": "viewer", "new_password": "Mat-Khau-Reset-Moi-2", "unlock": True},
        headers=admin_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "viewer" and patched.json()["must_change_password"] is True
    assert auth_client.get("/api/v1/auth/me", headers=bob_headers).status_code == 401

    # Admin không được tự hạ quyền/vô hiệu hóa chính mình
    assert auth_client.patch(
        f"/api/v1/auth/users/{admin.id}", json={"role": "viewer"}, headers=admin_headers
    ).status_code == 400
    assert auth_client.patch(
        f"/api/v1/auth/users/{admin.id}", json={"is_active": False}, headers=admin_headers
    ).status_code == 400
    missing = auth_client.patch(
        "/api/v1/auth/users/00000000-0000-0000-0000-000000000000", json={"unlock": True}, headers=admin_headers
    )
    assert missing.status_code == 404

    actions = {a.action for a in auth_session.scalars(select(AuditLog)).all()}
    assert {"AUTH_USER_CREATED", "AUTH_USER_UPDATED"} <= actions
    audit_dump = str([(a.before_state, a.after_state) for a in auth_session.scalars(select(AuditLog)).all()])
    assert "Mat-Khau-Cua-Bob-1" not in audit_dump and "Mat-Khau-Reset-Moi-2" not in audit_dump


def test_non_admin_cannot_manage_users(auth_client, create_user, login_headers) -> None:
    create_user("trader1", "trader")
    create_user("viewer1", "viewer")
    for username in ("trader1", "viewer1"):
        headers = login_headers(username)
        assert auth_client.get("/api/v1/auth/users", headers=headers).status_code == 403
        assert auth_client.post(
            "/api/v1/auth/users",
            json={"username": "newbie", "password": "Mat-Khau-Rat-Dai-12"},
            headers=headers,
        ).status_code == 403


def test_user_table_rejects_invalid_role_and_duplicate_username(auth_session) -> None:
    auth_session.add(User(username="x1", password_hash=hash_password("Mat-Khau-Rat-Dai-12"), role="hacker"))
    with pytest.raises(IntegrityError):
        auth_session.commit()
    auth_session.rollback()

    auth_session.add(User(username="dup", password_hash="h", role="viewer"))
    auth_session.commit()
    auth_session.add(User(username="dup", password_hash="h", role="viewer"))
    with pytest.raises(IntegrityError):
        auth_session.commit()


def test_bootstrap_admin_is_idempotent_and_never_overwrites(auth_session, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "")
    assert ensure_bootstrap_admin(auth_session, settings) is None

    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "Root")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "ngan")
    assert ensure_bootstrap_admin(auth_session, settings) is None

    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "Mat-Khau-Bootstrap-1")
    first = ensure_bootstrap_admin(auth_session, settings)
    assert first is not None and first.username == "root" and first.role == "admin"
    first_hash = first.password_hash
    assert "Mat-Khau-Bootstrap-1" not in first_hash

    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "Mat-Khau-Khac-Hoan-Toan-2")
    again = ensure_bootstrap_admin(auth_session, settings)
    assert again.id == first.id and again.password_hash == first_hash
    assert len(auth_session.scalars(select(User)).all()) == 1
    audit_dump = str([a.after_state for a in auth_session.scalars(select(AuditLog)).all()])
    assert "Mat-Khau-Bootstrap-1" not in audit_dump


@pytest.mark.parametrize("secret", ["", "ngan", "change_me_" + "x" * 30, "a" * 40, "your_secret_" + "k9" * 20])
@pytest.mark.parametrize("env", ["development", "production", "lan", "test"])
def test_settings_reject_missing_weak_or_placeholder_jwt_secret(env: str, secret: str) -> None:
    with pytest.raises(InsecureConfigurationError) as exc_info:
        Settings(_env_file=None, APP_ENV=env, JWT_SECRET_KEY=secret)
    assert secret not in str(exc_info.value) or secret == ""


def test_settings_accept_strong_secret_in_any_env_and_reject_missing_in_test() -> None:
    strong = "Xk9#mP2$vL8@nQ4!wR7&tY1^uI5*oE3-zA6+bC0"
    for env in ("production", "test"):
        assert Settings(_env_file=None, APP_ENV=env, JWT_SECRET_KEY=strong).JWT_SECRET_KEY == strong
    for secret in ("", "short"):
        with pytest.raises(InsecureConfigurationError):
            Settings(_env_file=None, APP_ENV="test", JWT_SECRET_KEY=secret)


def test_settings_have_no_hardcoded_jwt_fallback(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    with pytest.raises(InsecureConfigurationError):
        Settings(_env_file=None)


def test_swagger_docs_only_available_in_development(monkeypatch) -> None:
    test_env_client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert test_env_client.get(path).status_code == 404

    monkeypatch.setattr(get_settings(), "APP_ENV", "development")
    dev_client = TestClient(create_app())
    assert dev_client.get("/docs").status_code == 200
    assert dev_client.get("/openapi.json").status_code == 200
