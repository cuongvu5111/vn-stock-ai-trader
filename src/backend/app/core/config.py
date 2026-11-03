# Ngày tạo: 2026-11-03
# Mục đích: Quản lý cấu hình ứng dụng qua biến môi trường (Pydantic Settings).
# Lý do: Tuyệt đối không hardcode secret hoặc thông tin kết nối database trong mã nguồn.

from decimal import Decimal
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "trading_db"
    POSTGRES_USER: str = "trader"
    DB_PASSWORD: str = Field(default="change_me_local_only")
    DATABASE_URL_OVERRIDE: str = ""

    INITIAL_PAPER_CAPITAL: Decimal = Decimal("30000000.00")
    MARKET_TIMEZONE: str = "Asia/Ho_Chi_Minh"

    AI_ENABLED: bool = False
    AI_PROVIDER: str = "mock"
    AI_MODEL: str = "mock-v1"
    AI_API_KEY: str = ""

    LLM_URL: str = "https://api.openai.com/v1/chat/completions"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

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
    def sqlalchemy_database_uri(self) -> str:
        """Tạo chuỗi kết nối PostgreSQL qua driver psycopg v3."""
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.DB_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Khởi tạo singleton cho Settings để tái sử dụng trong toàn ứng dụng."""
    return Settings()
