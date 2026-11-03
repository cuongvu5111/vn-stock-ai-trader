# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các REST API endpoints cho phân hệ AI Analysis (/api/v1/ai/...).

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.service import AiAnalysisService
from app.core.database import get_db_session
from app.schemas.ai import AiAnalyzeRequest, AiReportListResponse, AiReportResponse

router = APIRouter(tags=["AI Analysis (Explainable & Isolated)"])


def get_ai_service(session: Session = Depends(get_db_session)) -> AiAnalysisService:
    return AiAnalysisService(session=session)


@router.post("/ai/analyze", response_model=AiReportResponse)
def analyze_signal_with_ai(
    payload: AiAnalyzeRequest,
    service: AiAnalysisService = Depends(get_ai_service),
) -> AiReportResponse:
    """Tạo báo cáo giải thích tín hiệu bằng AI từ dữ liệu đầu vào có nguồn (`input_snapshot`)."""
    return service.analyze_and_persist(payload)


@router.get("/ai/reports", response_model=AiReportListResponse)
def list_ai_reports(
    symbol: Optional[str] = Query(default=None, description="Lọc theo mã cổ phiếu"),
    signal_id: Optional[uuid.UUID] = Query(default=None, description="Lọc theo ID tín hiệu"),
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái report"),
    limit: int = Query(default=50, ge=1, le=200),
    service: AiAnalysisService = Depends(get_ai_service),
) -> AiReportListResponse:
    """Lấy danh sách các báo cáo AI đã tạo."""
    return service.list_reports(
        symbol=symbol,
        signal_id=signal_id,
        status_filter=status,
        limit=limit,
    )


@router.get("/ai/reports/{report_id}", response_model=AiReportResponse)
def get_ai_report_detail(
    report_id: uuid.UUID,
    service: AiAnalysisService = Depends(get_ai_service),
) -> AiReportResponse:
    """Xem chi tiết một báo cáo AI kèm input_snapshot, model, prompt_version và nguồn trích dẫn."""
    return service.get_report(report_id=report_id)
