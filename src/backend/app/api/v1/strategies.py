# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các REST API endpoints cho Stock Scanner, Signals và Backtesting (/api/v1/...).

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.backtesting.service import BacktestService
from app.core.database import get_db_session
from app.schemas.strategy import (
    BacktestCreateRequest,
    BacktestRunResponse,
    ScannerRunRequest,
    ScannerRunResponse,
    SignalListResponse,
)
from app.screening.service import ScannerService

router = APIRouter(tags=["Strategies, Scanner & Backtesting"])


def get_scanner_service(session: Session = Depends(get_db_session)) -> ScannerService:
    return ScannerService(session=session)


def get_backtest_service(session: Session = Depends(get_db_session)) -> BacktestService:
    return BacktestService(session=session)


@router.post("/scanner/run", response_model=ScannerRunResponse)
def run_stock_scanner(
    payload: ScannerRunRequest,
    service: ScannerService = Depends(get_scanner_service),
) -> ScannerRunResponse:
    """Chạy Stock Scanner theo chiến lược và lưu tín hiệu vào `analysis.stock_signals`."""
    return service.run_scanner(payload)


@router.post("/signals/generate", response_model=ScannerRunResponse)
def generate_signals(
    payload: ScannerRunRequest,
    service: ScannerService = Depends(get_scanner_service),
) -> ScannerRunResponse:
    """Sinh tín hiệu giao dịch cho danh sách mã chỉ định theo phiên bản chiến lược."""
    return service.run_scanner(payload)


@router.get("/signals", response_model=SignalListResponse)
def list_signals(
    symbol: Optional[str] = Query(default=None, description="Lọc theo mã cổ phiếu"),
    action: Optional[str] = Query(default=None, description="Lọc theo BUY / SELL / HOLD"),
    trading_date: Optional[date] = Query(default=None, description="Lọc theo ngày tín hiệu"),
    limit: int = Query(default=100, ge=1, le=500),
    service: ScannerService = Depends(get_scanner_service),
) -> SignalListResponse:
    """Truy vấn danh sách các tín hiệu giao dịch đã được tạo."""
    return service.list_signals(
        symbol=symbol,
        action=action,
        trading_date=trading_date,
        limit=limit,
    )


@router.post(
    "/backtests",
    response_model=BacktestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_backtest_run(
    payload: BacktestCreateRequest,
    service: BacktestService = Depends(get_backtest_service),
) -> BacktestRunResponse:
    """Tạo và chạy phiên Backtest chống look-ahead (khớp lệnh từ phiên T+1)."""
    return service.create_and_run_backtest(payload)


@router.get("/backtests/{backtest_id}", response_model=BacktestRunResponse)
def get_backtest_result(
    backtest_id: uuid.UUID,
    service: BacktestService = Depends(get_backtest_service),
) -> BacktestRunResponse:
    """Lấy chi tiết kết quả, metrics và danh sách lệnh của một phiên chạy Backtest."""
    return service.get_backtest_run(backtest_id=backtest_id)
