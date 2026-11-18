# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử cứng hóa cấu hình cho chế độ LAN/production: DB_PASSWORD, CORS_ORIGINS, TRUSTED_HOSTS,
#   BOOTSTRAP_ADMIN_PASSWORD và middleware TrustedHost; dev/test vẫn chạy với cấu hình mặc định.
# Lý do: backend chỉ nhận request qua nginx nội bộ/loopback nên Host lạ phải bị chặn; cấu hình yếu phải làm backend từ chối khởi động.

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import InsecureConfigurationError, Settings, enforce_production_hardening

STRONG_SECRET = "Xk9#mP2$vL8@nQ4!wR7&tY1^uI5*oE3-zA6+bC0"
STRONG_DB_PASSWORD = "Qw7_Lm2-Zx9.Pr4~Tn8"
STRONG_ADMIN_PASSWORD = "Mat-Khau-Admin-Rat-Manh-1"


def production_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "APP_ENV": "production",
        "JWT_SECRET_KEY": STRONG_SECRET,
        "DB_PASSWORD": STRONG_DB_PASSWORD,
        "CORS_ORIGINS": "http://192.168.1.10:8080,http://localhost:4200",
        "TRUSTED_HOSTS": "localhost,127.0.0.1,trading-backend",
        "BOOTSTRAP_ADMIN_PASSWORD": STRONG_ADMIN_PASSWORD,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("env", ["development", "test", "Development"])
def test_relaxed_environments_skip_hardening_even_with_defaults(env: str) -> None:
    settings = Settings(_env_file=None, APP_ENV=env, JWT_SECRET_KEY=STRONG_SECRET)

    assert settings.production_hardening_issues() == []
    enforce_production_hardening(settings)


def test_valid_production_configuration_passes() -> None:
    settings = production_settings()

    assert settings.production_hardening_issues() == []
    enforce_production_hardening(settings)


@pytest.mark.parametrize("env", ["production", "lan", "staging"])
def test_non_dev_environment_rejects_default_configuration(env: str) -> None:
    settings = Settings(_env_file=None, APP_ENV=env, JWT_SECRET_KEY=STRONG_SECRET)

    issues = " ".join(settings.production_hardening_issues())
    assert "DB_PASSWORD" in issues
    assert "TRUSTED_HOSTS" in issues
    with pytest.raises(InsecureConfigurationError):
        enforce_production_hardening(settings)


@pytest.mark.parametrize(
    "password", ["change_me_local_only", "short", "a" * 20, "mat-khau@co/ky:tu#la", "p ass word 1234567"]
)
def test_production_rejects_weak_or_url_unsafe_db_password(password: str) -> None:
    issues = production_settings(DB_PASSWORD=password).production_hardening_issues()

    assert any(issue.startswith("DB_PASSWORD") for issue in issues)
    assert all(password not in issue for issue in issues)


def test_production_db_password_check_skipped_when_url_override_used() -> None:
    settings = production_settings(DB_PASSWORD="change_me_local_only", DATABASE_URL_OVERRIDE="postgresql+psycopg://u:p@db/x")

    assert not any(issue.startswith("DB_PASSWORD") for issue in settings.production_hardening_issues())


@pytest.mark.parametrize(
    "origins", ["*", "http://*.lan", "http://192.168.1.10:8080/app", "192.168.1.10:8080", "ftp://host", "http://ok.lan,*", ""]
)
def test_production_rejects_wildcard_or_malformed_cors_origins(origins: str) -> None:
    issues = production_settings(CORS_ORIGINS=origins).production_hardening_issues()

    assert any(issue.startswith("CORS_ORIGINS") for issue in issues)


@pytest.mark.parametrize("hosts", ["", "*", "localhost,*", "http://localhost", "localhost:8000", "host/path", "evil..com/"])
def test_production_rejects_empty_or_wildcard_trusted_hosts(hosts: str) -> None:
    issues = production_settings(TRUSTED_HOSTS=hosts).production_hardening_issues()

    assert any(issue.startswith("TRUSTED_HOSTS") for issue in issues)


def test_production_accepts_subdomain_wildcard_trusted_host() -> None:
    assert production_settings(TRUSTED_HOSTS="localhost,*.trading.lan").production_hardening_issues() == []


def test_production_flags_too_short_bootstrap_admin_password_without_leaking_it() -> None:
    issues = production_settings(BOOTSTRAP_ADMIN_PASSWORD="ngan123").production_hardening_issues()

    assert any(issue.startswith("BOOTSTRAP_ADMIN_PASSWORD") for issue in issues)
    assert all("ngan123" not in issue for issue in issues)


def test_enforce_error_message_lists_variable_names_but_no_secret_values() -> None:
    settings = production_settings(DB_PASSWORD="change_me_local_only", TRUSTED_HOSTS="")

    with pytest.raises(InsecureConfigurationError) as exc_info:
        enforce_production_hardening(settings)

    message = str(exc_info.value)
    assert "DB_PASSWORD" in message and "TRUSTED_HOSTS" in message
    assert "change_me_local_only" not in message and STRONG_SECRET not in message


def test_create_app_refuses_insecure_production_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(main_module.settings, "TRUSTED_HOSTS", "")

    with pytest.raises(InsecureConfigurationError):
        main_module.create_app()


def test_trusted_host_middleware_rejects_unknown_host_but_allows_internal_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module.settings, "TRUSTED_HOSTS", "localhost,127.0.0.1,trading-backend")
    monkeypatch.setattr(
        "app.api.v1.health.check_database_connection", lambda: (True, "connected_mock_for_unit_test")
    )
    client = TestClient(main_module.create_app())

    assert client.get("/api/v1/health", headers={"host": "evil.example"}).status_code == 400
    for host in ("localhost:8000", "127.0.0.1:8000", "trading-backend"):
        assert client.get("/api/v1/health", headers={"host": host}).status_code == 200


def test_trusted_host_middleware_not_installed_when_unset() -> None:
    client = TestClient(main_module.create_app())

    assert not any(m.cls.__name__ == "TrustedHostMiddleware" for m in client.app.user_middleware)
