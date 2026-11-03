# Ngày tạo: 2026-11-03
# Mục đích: Điểm khởi đầu (entrypoint) của ứng dụng FastAPI Modular Monolith.
# Lý do: Khởi tạo structured logging, CORS giới hạn cho local dashboard, CorrelationIdMiddleware và routers.

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.core.models_registry  # noqa: F401 - Đảm bảo toàn bộ 24 bảng SQLAlchemy được nạp vào Base.metadata
from app.api.router import api_v1_router
from app.api.v1.health import router as root_health_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import CorrelationIdMiddleware, configure_logging

settings = get_settings()
configure_logging(settings.LOG_LEVEL)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Quản lý vòng đời khởi động và tắt ứng dụng FastAPI."""
    logger.info(
        "application_started",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        trading_mode="PAPER_ONLY",
    )
    yield


def create_app() -> FastAPI:
    """Khởi tạo và cấu hình FastAPI instance."""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Personal AI Trading Assistant (VN Stock MVP) — "
            "Chỉ hỗ trợ dữ liệu lịch sử, phân tích, Backtest và Paper Trading."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    register_exception_handlers(application)

    # Hỗ trợ cả /api/v1/health (chuẩn API contract) và /health (tiện cho container probe)
    application.include_router(api_v1_router)
    application.include_router(root_health_router)

    return application


app = create_app()
