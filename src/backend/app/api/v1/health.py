# Ngày tạo: 2026-11-03
# Mục đích: Cung cấp endpoint kiểm tra trạng thái hoạt động của Backend API và PostgreSQL.

from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import POSTGRES_SCHEMAS, check_database_connection
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health_status() -> HealthResponse:
    """Kiểm tra trạng thái sức khỏe của hệ thống và kết nối cơ sở dữ liệu."""
    settings = get_settings()
    db_ok, db_message = check_database_connection()
    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        trading_mode="PAPER_ONLY",
        live_broker_enabled=False,
        database_status=db_message,
        registered_schemas=list(POSTGRES_SCHEMAS),
        timestamp_utc=datetime.now(timezone.utc),
    )
