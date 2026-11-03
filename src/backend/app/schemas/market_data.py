# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Pydantic v2 DTOs cho phân hệ Market Data (Stocks, Daily Prices, CSV Imports, Overview).
# Lý do: Chuẩn hóa dữ liệu vào/ra API và đảm bảo mọi giá cổ phiếu đều dùng kiểu Decimal.

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StockCreateRequest(BaseModel):
    """Dữ liệu đầu vào khi thêm mới một mã cổ phiếu."""

    symbol: str = Field(..., min_length=1, max_length=20, description="Mã cổ phiếu (VD: FPT, VCB)")
    exchange: str = Field(..., description="Sàn niêm yết: HOSE, HNX, UPCOM")
    company_name: Optional[str] = Field(default=None, max_length=255)
    sector: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    is_sample: bool = Field(
        default=False,
        description="Nếu True, tự động gắn tiền tố [SAMPLE] vào tên công ty để phân biệt dữ liệu mẫu",
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned.isalnum():
            raise ValueError("Mã cổ phiếu chỉ được chứa chữ cái và chữ số.")
        return cleaned

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if cleaned not in {"HOSE", "HNX", "UPCOM"}:
            raise ValueError("Sàn giao dịch phải thuộc HOSE, HNX hoặc UPCOM.")
        return cleaned


class StockUpdateRequest(BaseModel):
    """Dữ liệu đầu vào khi cập nhật thông tin mã cổ phiếu."""

    exchange: Optional[str] = None
    company_name: Optional[str] = Field(default=None, max_length=255)
    sector: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None

    @field_validator("exchange")
    @classmethod
    def validate_exchange(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip().upper()
        if cleaned not in {"HOSE", "HNX", "UPCOM"}:
            raise ValueError("Sàn giao dịch phải thuộc HOSE, HNX hoặc UPCOM.")
        return cleaned


class StockResponse(BaseModel):
    """Thông tin chi tiết một mã cổ phiếu trả về từ API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    exchange: str
    company_name: Optional[str]
    sector: Optional[str]
    is_active: bool
    created_at: datetime


class StockListResponse(BaseModel):
    """Danh sách cổ phiếu có phân trang."""

    total: int
    limit: int
    offset: int
    items: List[StockResponse]


class DailyPriceItemResponse(BaseModel):
    """Một bản ghi giá OHLCV theo ngày kèm thông tin truy xuất nguồn (provenance)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    import_batch_id: Optional[uuid.UUID]
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Optional[Decimal]
    volume: int
    created_at: datetime


class StockHistoryResponse(BaseModel):
    """Lịch sử giá OHLCV của một mã cổ phiếu trong khoảng thời gian."""

    symbol: str
    exchange: str
    company_name: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    total_records: int
    items: List[DailyPriceItemResponse]


class CsvImportRequest(BaseModel):
    """Yêu cầu import dữ liệu OHLCV từ nội dung CSV gửi qua JSON."""

    csv_content: str = Field(..., min_length=1, description="Nội dung CSV bao gồm cả dòng tiêu đề")
    file_name: str = Field(default="inline_upload.csv", description="Tên file hoặc định danh lô dữ liệu")
    source_name: str = Field(default="CSV_SAMPLE_SOURCE", description="Tên nguồn dữ liệu trong market.data_sources")
    license_notes: Optional[str] = Field(
        default="SAMPLE / SIMULATED DATA ONLY — Dữ liệu phục vụ nghiên cứu & Paper Trading.",
        description="Ghi chú bản quyền hoặc nhãn SAMPLE",
    )
    auto_create_stocks: bool = Field(
        default=True,
        description="Tự động khởi tạo mã cổ phiếu nếu chưa có trong danh mục",
    )
    is_sample: bool = Field(
        default=True,
        description="Đánh dấu dữ liệu mẫu (SAMPLE) khi tự động tạo mã cổ phiếu mới",
    )


class ImportBatchResponse(BaseModel):
    """Kết quả chi tiết của một lô import CSV."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: Optional[uuid.UUID]
    source_name: Optional[str] = None
    file_name: Optional[str]
    checksum: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    status: Optional[str]
    rows_read: Optional[int]
    rows_inserted: Optional[int]
    rows_rejected: Optional[int]
    error_detail: Optional[Dict[str, Any]]


class MarketOverviewResponse(BaseModel):
    """Thông tin tổng quan về dữ liệu thị trường hiện có trong hệ thống."""

    total_stocks: int
    active_stocks: int
    total_daily_price_records: int
    latest_trading_date: Optional[date]
    data_sources_count: int
    recent_import_batches: List[ImportBatchResponse]


class SyncRealMarketRequest(BaseModel):
    """Yêu cầu đồng bộ dữ liệu lịch sử & giá mới nhất thực tế từ thị trường chứng khoán Việt Nam."""

    symbols: Optional[List[str]] = Field(
        default=None,
        description="Danh sách mã cần đồng bộ (mặc định: FPT, HPG, VCB, ACB, MBB, TCB, SSI, MWG, CTG, VNM)",
    )
    lookback_days: int = Field(default=220, ge=30, le=1000)
    purge_sample_data: bool = Field(
        default=True,
        description="Xóa toàn bộ các bản ghi dữ liệu mẫu [SAMPLE] trước khi nạp dữ liệu thật",
    )


class SyncRealMarketResponse(BaseModel):
    """Kết quả đồng bộ dữ liệu thị trường thực tế."""

    batch_id: uuid.UUID
    source_name: str
    symbols_synced: List[str]
    rows_inserted_or_updated: int
    latest_trading_date: Optional[date]
    sample_records_purged: bool
    errors: Dict[str, str]
