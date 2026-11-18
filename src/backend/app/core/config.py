# Ngày tạo: 2026-11-03
# Mục đích: Quản lý cấu hình ứng dụng qua biến môi trường (Pydantic Settings).
# Lý do: Tuyệt đối không hardcode secret hoặc thông tin kết nối database trong mã nguồn.

import re
from decimal import Decimal
from functools import lru_cache
from typing import List, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_LENGTH = 32
MIN_DB_PASSWORD_LENGTH = 12
_PLACEHOLDER_MARKERS = ("change_me", "changeme", "change-me", "your_", "your-", "example", "placeholder")
# Môi trường dev/test được phép lỏng; mọi giá trị APP_ENV khác (production, lan, staging...) bị coi là có thể truy cập qua mạng.
_RELAXED_ENVIRONMENTS = frozenset({"development", "test"})
# DB_PASSWORD được ghép thẳng vào URL SQLAlchemy và alembic.ini nên chỉ cho phép ký tự an toàn trong URL.
_URL_SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9._~-]+$")
_CORS_ORIGIN_PATTERN = re.compile(
    r"^https?://([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])(:\d{1,5})?$"
)
_TRUSTED_HOST_PATTERN = re.compile(r"^(\*\.)?[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")


class InsecureConfigurationError(RuntimeError):
    """Cấu hình bảo mật không hợp lệ; không dùng ValueError để Pydantic không in lại toàn bộ giá trị secret."""


def _is_placeholder_secret(secret: str) -> bool:
    """Nhận diện secret mẫu/mặc định hoặc chuỗi lặp một ký tự dễ đoán."""
    lowered = secret.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS) or len(set(secret)) < 8


class Settings(BaseSettings):
    """Cấu hình trung tâm của hệ thống Personal AI Trading Assistant."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Personal AI Trading Assistant"
    APP_ENV: str = "development"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:4200,http://127.0.0.1:4200"
    # Danh sách Host header hợp lệ (phân tách bằng dấu phẩy, không kèm cổng). Để trống = không kiểm tra (chỉ dev/test).
    # Backend chỉ nhận request từ nginx nội bộ và loopback nên cần chặn Host lạ (DNS rebinding) ở môi trường LAN.
    TRUSTED_HOSTS: str = ""

    # Scheduler EOD: mặc định TẮT; chỉ bật tường minh ở môi trường LAN/production. Múi giờ cố định Asia/Ho_Chi_Minh,
    # chạy thứ 2-6 (xem app/system/scheduler.py), nên không có biến cấu hình múi giờ hay ngày chạy.
    SCHEDULER_ENABLED: bool = False
    DAILY_EOD_HOUR: int = Field(default=16, ge=0, le=23)
    DAILY_EOD_MINUTE: int = Field(default=30, ge=0, le=59)
    # Backend khởi động lại trễ hơn khoảng này sau giờ chạy thì lần chạy bị bỏ qua (misfire), không chạy bù muộn.
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = Field(default=3600, ge=1, le=86400)

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "trading_db"
    POSTGRES_USER: str = "trader"
    DB_PASSWORD: str = Field(default="change_me_local_only")
    DATABASE_URL_OVERRIDE: str = ""

    INITIAL_PAPER_CAPITAL: Decimal = Decimal("30000000.00")
    # Quy tắc dự án: ngày giao dịch luôn theo Asia/Ho_Chi_Minh. Migration 0004 hardcode múi giờ này khi backfill
    # trade_date nên runtime không được phép lệch; giá trị khác bị từ chối ngay lúc khởi động.
    MARKET_TIMEZONE: Literal["Asia/Ho_Chi_Minh"] = "Asia/Ho_Chi_Minh"
    # Số ngày làm việc từ ngày khớp (T) tới ngày cổ phiếu mua về tài khoản và được phép bán (T+N).
    SETTLEMENT_LAG_TRADING_DAYS: int = Field(default=2, ge=0, le=10)

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=1440)

    AUTH_MAX_FAILED_LOGINS: int = Field(default=5, ge=1, le=100)
    AUTH_LOCKOUT_MINUTES: int = Field(default=15, ge=1, le=1440)

    BOOTSTRAP_ADMIN_USERNAME: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    AI_ENABLED: bool = False
    AI_PROVIDER: str = "mock"
    AI_MODEL: str = "mock-v1"
    AI_API_KEY: str = ""

    LLM_URL: str = "https://api.openai.com/v1/chat/completions"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        """Mọi môi trường (kể cả test) phải cấu hình secret mạnh tường minh; không có fallback hardcode."""
        secret = self.JWT_SECRET_KEY.strip()
        if len(secret) < MIN_JWT_SECRET_LENGTH or _is_placeholder_secret(secret):
            raise InsecureConfigurationError(
                "JWT_SECRET_KEY thiếu, quá ngắn (<32 ký tự) hoặc đang là giá trị mặc định/placeholder. "
                "Hãy sinh secret ngẫu nhiên, ví dụ: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        self.JWT_SECRET_KEY = secret
        return self

    @property
    def docs_enabled(self) -> bool:
        """Swagger/ReDoc/OpenAPI chỉ được mở ở môi trường development."""
        return self.APP_ENV == "development"

    @property
    def resolved_llm_url(self) -> str:
        """Trả về URL endpoint của LLM (mặc định chuẩn OpenAI Chat Completions)."""
        return self.LLM_URL.strip() or "https://api.openai.com/v1/chat/completions"

    @property
    def resolved_llm_api_key(self) -> str:
        """Ưu tiên LLM_API_KEY, nếu trống thì dùng AI_API_KEY."""
        return self.LLM_API_KEY.strip() or self.AI_API_KEY.strip()

    @property
    def resolved_llm_model(self) -> str:
        """Ưu tiên LLM_MODEL, nếu trống thì dùng AI_MODEL."""
        return self.LLM_MODEL.strip() or self.AI_MODEL.strip() or "mock-v1"

    @property
    def cors_origin_list(self) -> List[str]:
        """Trả về danh sách các origin được phép gọi API."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def trusted_host_list(self) -> List[str]:
        """Trả về danh sách Host header được phép (rỗng = không bật kiểm tra)."""
        return [host.strip() for host in self.TRUSTED_HOSTS.split(",") if host.strip()]

    @property
    def is_relaxed_environment(self) -> bool:
        """`development`/`test` được bỏ qua các kiểm tra cứng hóa dành cho môi trường LAN/production."""
        return self.APP_ENV.strip().lower() in _RELAXED_ENVIRONMENTS

    def production_hardening_issues(self) -> List[str]:
        """
        Liệt kê các cấu hình không an toàn khi chạy ngoài dev/test. Chỉ nêu tên biến, không bao giờ in giá trị secret.
        Không đặt trong validator của Settings để việc dựng Settings (ví dụ trong test) không phụ thuộc môi trường triển khai.
        """
        if self.is_relaxed_environment:
            return []

        issues: List[str] = []
        if not self.DATABASE_URL_OVERRIDE:
            password = self.DB_PASSWORD
            if len(password) < MIN_DB_PASSWORD_LENGTH or _is_placeholder_secret(password):
                issues.append(
                    f"DB_PASSWORD thiếu, quá ngắn (<{MIN_DB_PASSWORD_LENGTH} ký tự) hoặc đang là placeholder"
                )
            elif not _URL_SAFE_PASSWORD.fullmatch(password):
                issues.append("DB_PASSWORD chỉ được chứa ký tự A-Z a-z 0-9 . _ ~ - (được ghép vào URL kết nối)")

        origins = self.cors_origin_list
        if not origins:
            issues.append("CORS_ORIGINS đang trống")
        if any(not _CORS_ORIGIN_PATTERN.fullmatch(origin) for origin in origins):
            issues.append("CORS_ORIGINS chứa origin không hợp lệ (cần dạng http(s)://host[:port], không wildcard/đường dẫn)")

        hosts = self.trusted_host_list
        if not hosts:
            issues.append("TRUSTED_HOSTS đang trống (cần liệt kê Host header hợp lệ của backend)")
        if any(not _TRUSTED_HOST_PATTERN.fullmatch(host) for host in hosts):
            issues.append("TRUSTED_HOSTS chứa giá trị không hợp lệ (không dùng '*', scheme, cổng hay đường dẫn)")

        if self.BOOTSTRAP_ADMIN_PASSWORD:
            from app.auth.security import MIN_PASSWORD_LENGTH  # import trễ để tránh vòng lặp config <-> auth

            if len(self.BOOTSTRAP_ADMIN_PASSWORD) < MIN_PASSWORD_LENGTH:
                issues.append(
                    f"BOOTSTRAP_ADMIN_PASSWORD ngắn hơn {MIN_PASSWORD_LENGTH} ký tự nên admin đầu tiên sẽ không được tạo"
                )
        return issues

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Tạo chuỗi kết nối PostgreSQL qua driver psycopg v3."""
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.DB_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


def enforce_production_hardening(settings: Settings) -> None:
    """Từ chối khởi động nếu cấu hình LAN/production còn mặc định yếu hoặc quá rộng."""
    issues = settings.production_hardening_issues()
    if issues:
        raise InsecureConfigurationError(
            f"Cấu hình không an toàn cho APP_ENV={settings.APP_ENV!r}: " + "; ".join(issues) + "."
        )


@lru_cache
def get_settings() -> Settings:
    """Khởi tạo singleton cho Settings để tái sử dụng trong toàn ứng dụng."""
    return Settings()
