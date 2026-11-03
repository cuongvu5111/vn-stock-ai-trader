# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Pydantic v2 DTOs cho Job Runs và Daily Workflow (Mục 13).

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobRunItemResponse(BaseModel):
    """Thông tin một đợt chạy background/daily job (`system.job_runs`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_name: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    status: Optional[str]
    records_processed: Optional[int]
    error_detail: Optional[Dict[str, Any]]


class JobRunListResponse(BaseModel):
    total: int
    items: List[JobRunItemResponse]


class DailyWorkflowRunRequest(BaseModel):
    """Yêu cầu thực thi chuỗi công việc EOD hàng ngày (Idempotent Daily Workflow - Mục 13)."""

    import_sample_csv_if_empty: bool = Field(
        default=True,
        description="Nếu hệ thống chưa có dữ liệu giá OHLCV thì tự động import file sample_ohlcv_data.csv",
    )
    as_of_date: Optional[date] = Field(
        default=None,
        description="Ngày dữ liệu tính toán (nếu để trống sẽ lấy ngày giao dịch mới nhất trong DB)",
    )
    run_ai_analysis: bool = Field(
        default=True,
        description="Có chạy phân tích AI giải thích cho các tín hiệu BUY/SELL sinh ra hay không",
    )
    create_proposals: bool = Field(
        default=True,
        description="Tự động tạo TradeProposal ở trạng thái PendingApproval cho các tín hiệu hợp lệ (không auto-approve)",
    )


class DailyWorkflowRunResponse(BaseModel):
    """Kết quả tổng hợp sau khi chạy Daily EOD Workflow."""

    job_run_id: uuid.UUID
    status: str
    as_of_date: Optional[date]
    imported_rows: int
    indicators_upserted: int
    signals_generated: int
    ai_reports_created: int
    proposals_created: int
    proposals_blocked_or_skipped: int
    snapshot_nav: Optional[str]
    steps_summary: List[str]
    started_at: datetime
    completed_at: datetime
