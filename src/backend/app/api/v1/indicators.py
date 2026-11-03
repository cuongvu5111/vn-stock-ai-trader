# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa REST API endpoints cho phân hệ Technical Analysis (/api/v1/indicators/calculate & /api/v1/stocks/{symbol}/indicators).

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.indicators.service import IndicatorService
from app.schemas.indicators import (
    CalculateIndicatorsRequest,
    IndicatorCalculationRunResponse,
    StockIndicatorHistoryResponse,
)

router = APIRouter(tags=["Technical Analysis"])


def get_indicator_service(session: Session = Depends(get_db_session)) -> IndicatorService:
    """Dependency khởi tạo IndicatorService."""
    return IndicatorService(session=session)


@router.post("/indicators/calculate", response_model=IndicatorCalculationRunResponse)
def calculate_indicators(
    payload: CalculateIndicatorsRequest,
    service: IndicatorService = Depends(get_indicator_service),
) -> IndicatorCalculationRunResponse:
    """Tính toán và lưu trữ chỉ báo kỹ thuật deterministic theo ngày và phiên bản công thức."""
    return service.calculate_and_persist(
        symbols=payload.symbols,
        as_of_date=payload.as_of_date,
        calculation_version=payload.calculation_version,
    )


@router.get("/stocks/{symbol}/indicators", response_model=StockIndicatorHistoryResponse)
def get_stock_indicators(
    symbol: str,
    start_date: Optional[date] = Query(default=None, description="Ngày bắt đầu (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Ngày kết thúc (YYYY-MM-DD)"),
    calculation_version: str = Query(default="v1.0", description="Phiên bản tính toán chỉ báo"),
    limit: int = Query(default=500, ge=1, le=2000),
    service: IndicatorService = Depends(get_indicator_service),
) -> StockIndicatorHistoryResponse:
    """Truy vấn chuỗi chỉ báo kỹ thuật của một mã cổ phiếu."""
    return service.get_stock_indicators(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        calculation_version=calculation_version,
        limit=limit,
    )
