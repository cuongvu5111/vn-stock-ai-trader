# Ngày tạo: 2026-11-03
# Mục đích: Cung cấp REST API cho lịch sử JobRun và kích hoạt quy trình Daily EOD Workflow (Mục 13).

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.schemas.system import (
    DailyWorkflowRunRequest,
    DailyWorkflowRunResponse,
    JobRunListResponse,
)
from app.system.service import SystemWorkflowService

router = APIRouter(prefix="/system", tags=["System & Daily Workflow"])


@router.get("/jobs", response_model=JobRunListResponse, summary="Lịch sử các đợt chạy Job (system.job_runs)")
def list_job_runs(
    limit: int = Query(default=30, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> JobRunListResponse:
    service = SystemWorkflowService(session=session)
    return service.list_job_runs(limit=limit)


@router.post(
    "/daily-workflow",
    response_model=DailyWorkflowRunResponse,
    summary="Chạy quy trình EOD hàng ngày (Import -> Indicators -> Scanner -> AI -> Proposals chờ duyệt -> Snapshot)",
)
def run_daily_workflow(
    payload: DailyWorkflowRunRequest,
    session: Session = Depends(get_db_session),
) -> DailyWorkflowRunResponse:
    service = SystemWorkflowService(session=session)
    return service.run_daily_eod_workflow(payload=payload)
