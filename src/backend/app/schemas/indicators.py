# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa Pydantic v2 DTOs cho phân hệ Technical Analysis (/api/v1/indicators/calculate & /api/v1/stocks/{symbol}/indicators).

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CalculateIndicatorsRequest(BaseModel):
    """Yêu cầu chạy tính toán chỉ báo kỹ thuật cho danh sách mã cổ phiếu."""

    symbols: Optional[List[str]] = Field(
        default=None,
        description="Danh sách mã cần tính (để trống nếu muốn tính cho toàn bộ mã đang active)",
    )
    as_of_date: Optional[date] = Field(
        default=None,
        description="Giới hạn ngày dữ liệu tối đa được phép nhìn thấy (chống look-ahead bias)",
    )
    calculation_version: str = Field(
        default="v1.0",
        min_length=1,
        max_length=30,
        description="Phiên bản công thức tính chỉ báo",
    )


class IndicatorCalculationRunResponse(BaseModel):
    """Kết quả một đợt chạy tính toán và lưu trữ chỉ báo kỹ thuật."""

    analysis_run_id: uuid.UUID
    status: str
    calculation_version: str
    data_as_of: Optional[date]
    symbols_processed: int
    rows_upserted: int
    warnings: Dict[str, str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TechnicalIndicatorItemResponse(BaseModel):
    """Bản ghi chỉ báo kỹ thuật của một mã cổ phiếu tại một ngày giao dịch."""

    model_config = ConfigDict(from_attributes=True)

    trading_date: date
    ma20: Optional[Decimal]
    ma50: Optional[Decimal]
    ma200: Optional[Decimal]
    ema20: Optional[Decimal]
    ema50: Optional[Decimal]
    rsi14: Optional[Decimal]
    macd: Optional[Decimal]
    macd_signal: Optional[Decimal]
    macd_histogram: Optional[Decimal]
    atr14: Optional[Decimal]
    volume_avg20: Optional[Decimal]
    calculation_version: str
    warm_up_core_ready: bool = Field(
        description="True nếu các chỉ báo ngắn-trung hạn cốt lõi (MA20, RSI14, ATR14, VolAvg20) đã đủ dữ liệu warm-up"
    )


class StockIndicatorHistoryResponse(BaseModel):
    """Chuỗi lịch sử chỉ báo kỹ thuật của một mã cổ phiếu."""

    symbol: str
    exchange: str
    calculation_version: str
    start_date: Optional[date]
    end_date: Optional[date]
    total_records: int
    items: List[TechnicalIndicatorItemResponse]
