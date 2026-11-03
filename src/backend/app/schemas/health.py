# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa Pydantic schema cho phản hồi Health Check của hệ thống.

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Thông tin trạng thái sức khỏe của API, Database và chế độ vận hành."""

    status: str = Field(description="Trạng thái tổng thể: healthy hoặc degraded")
    app_name: str
    version: str
    environment: str
    trading_mode: str = Field(default="PAPER_ONLY", description="MVP chỉ hỗ trợ PAPER_ONLY")
    live_broker_enabled: bool = Field(default=False, description="Luôn bằng False trong MVP")
    database_status: str
    registered_schemas: List[str]
    timestamp_utc: datetime
