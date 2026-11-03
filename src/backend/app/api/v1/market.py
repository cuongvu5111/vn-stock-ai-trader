# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các REST API endpoints cho phân hệ Market Data (/api/v1/stocks, /api/v1/market/...).

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.market_data.service import MarketDataService
from app.schemas.market_data import (
    CsvImportRequest,
    ImportBatchResponse,
    MarketOverviewResponse,
    StockCreateRequest,
    StockHistoryResponse,
    StockListResponse,
    StockResponse,
    StockUpdateRequest,
    SyncRealMarketRequest,
    SyncRealMarketResponse,
)

router = APIRouter(tags=["Market Data"])


def get_market_service(session: Session = Depends(get_db_session)) -> MarketDataService:
    """Dependency khởi tạo MarketDataService với DB session hiện tại."""
    return MarketDataService(session=session)


@router.get("/stocks", response_model=StockListResponse)
def list_stocks(
    exchange: Optional[str] = Query(default=None, description="Lọc theo sàn: HOSE, HNX, UPCOM"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái kích hoạt"),
    q: Optional[str] = Query(default=None, description="Tìm kiếm theo mã cổ phiếu"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: MarketDataService = Depends(get_market_service),
) -> StockListResponse:
    """Lấy danh sách cổ phiếu có bộ lọc và phân trang."""
    return service.list_stocks(
        exchange=exchange,
        is_active=is_active,
        query_text=q,
        limit=limit,
        offset=offset,
    )


@router.post("/stocks", response_model=StockResponse, status_code=status.HTTP_201_CREATED)
def create_stock(
    payload: StockCreateRequest,
    service: MarketDataService = Depends(get_market_service),
) -> StockResponse:
    """Thêm mới một mã cổ phiếu vào danh mục theo dõi."""
    return service.create_stock(payload)


@router.patch("/stocks/{symbol}", response_model=StockResponse)
def update_stock(
    symbol: str,
    payload: StockUpdateRequest,
    service: MarketDataService = Depends(get_market_service),
) -> StockResponse:
    """Cập nhật thông tin sàn, tên công ty, ngành hoặc trạng thái của mã cổ phiếu."""
    return service.update_stock(symbol=symbol, payload=payload)


@router.get("/stocks/{symbol}/history", response_model=StockHistoryResponse)
def get_stock_history(
    symbol: str,
    start_date: Optional[date] = Query(default=None, description="Ngày bắt đầu (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Ngày kết thúc (YYYY-MM-DD)"),
    limit: int = Query(default=500, ge=1, le=2000),
    service: MarketDataService = Depends(get_market_service),
) -> StockHistoryResponse:
    """Truy vấn lịch sử giá OHLCV theo ngày của một mã cổ phiếu kèm thông tin nguồn và batch."""
    return service.get_stock_history(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get("/market/overview", response_model=MarketOverviewResponse)
def get_market_overview(
    service: MarketDataService = Depends(get_market_service),
) -> MarketOverviewResponse:
    """Xem tổng quan dữ liệu thị trường và các lô import gần nhất."""
    return service.get_market_overview()


@router.post(
    "/market/imports",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_market_import(
    payload: CsvImportRequest,
    service: MarketDataService = Depends(get_market_service),
) -> ImportBatchResponse:
    """Tạo job import dữ liệu OHLCV từ nội dung CSV (Idempotent, có kiểm tra chất lượng & checksum)."""
    return service.import_csv_content(
        csv_text=payload.csv_content,
        file_name=payload.file_name,
        source_name=payload.source_name,
        license_notes=payload.license_notes,
        auto_create_stocks=payload.auto_create_stocks,
        is_sample=payload.is_sample,
    )


@router.get("/market/imports/{batch_id}", response_model=ImportBatchResponse)
def get_market_import_status(
    batch_id: uuid.UUID,
    service: MarketDataService = Depends(get_market_service),
) -> ImportBatchResponse:
    """Kiểm tra trạng thái, thống kê số bản ghi và chi tiết lỗi của một lô import CSV."""
    return service.get_import_batch(batch_id=batch_id)


@router.post("/market/sync-real", response_model=SyncRealMarketResponse)
def sync_real_market_data(
    payload: SyncRealMarketRequest,
    service: MarketDataService = Depends(get_market_service),
) -> SyncRealMarketResponse:
    """Đồng bộ dữ liệu OHLCV thực tế của chứng khoán Việt Nam (VNDirect DChart) và xóa dữ liệu SAMPLE."""
    return service.sync_real_market_data(payload=payload)
