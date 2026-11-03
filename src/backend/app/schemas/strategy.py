# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Pydantic v2 DTOs cho phân hệ Strategies, Stock Scanner, Signals và Backtesting.

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SignalContractResponse(BaseModel):
    """Cấu trúc phản hồi chuẩn theo Signal Contract tại Mục 7.3."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[uuid.UUID] = None
    symbol: str
    strategy_id: str
    strategy_version: int
    signal_date: date
    data_as_of: date
    action: str
    score: Decimal
    reference_price: Decimal
    stop_loss: Optional[Decimal] = None
    reason: List[str]
    warnings: List[str]
    source_data_version: str
    status: str = "GENERATED"
    created_at: Optional[datetime] = None


class ScannerRunRequest(BaseModel):
    """Yêu cầu chạy bộ quét cổ phiếu (Stock Scanner) hoặc sinh tín hiệu."""

    symbols: Optional[List[str]] = Field(
        default=None,
        description="Danh sách mã cần quét (để trống nếu muốn quét toàn bộ mã active)",
    )
    strategy_type: str = Field(
        default="TREND_FOLLOWING",
        description="Loại chiến lược: TREND_FOLLOWING hoặc PULLBACK",
    )
    strategy_version: int = Field(default=1, ge=1)
    configuration_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Tham số chiến lược ghi đè (nếu muốn thử nghiệm cấu hình mới)",
    )
    as_of_date: Optional[date] = Field(
        default=None,
        description="Ngày dữ liệu chốt để quét (mặc định lấy phiên mới nhất của từng mã)",
    )
    calculation_version: str = Field(default="v1.0")
    only_actionable: bool = Field(
        default=False,
        description="Nếu True, chỉ trả về các tín hiệu BUY hoặc SELL (ẩn HOLD)",
    )


class ScannerRunResponse(BaseModel):
    """Kết quả một đợt chạy Stock Scanner / Signal Generation."""

    analysis_run_id: uuid.UUID
    strategy_type: str
    strategy_version: int
    total_scanned: int
    signals_generated: int
    signals: List[SignalContractResponse]


class SignalListResponse(BaseModel):
    """Danh sách tín hiệu lưu trong database."""

    total: int
    items: List[SignalContractResponse]


class BacktestCreateRequest(BaseModel):
    """Yêu cầu chạy mô phỏng Backtest lịch sử chống look-ahead bias."""

    symbol: str = Field(..., description="Mã cổ phiếu cần chạy Backtest")
    strategy_type: str = Field(
        default="TREND_FOLLOWING",
        description="TREND_FOLLOWING hoặc PULLBACK",
    )
    strategy_version: int = Field(default=1, ge=1)
    configuration_override: Optional[Dict[str, Any]] = None
    start_date: date = Field(..., description="Ngày bắt đầu kỳ Backtest")
    end_date: date = Field(..., description="Ngày kết thúc kỳ Backtest")
    initial_capital: Decimal = Field(
        default=Decimal("30000000.00"),
        gt=Decimal("0"),
        description="Vốn giả lập ban đầu (VNĐ)",
    )
    fee_rate: Decimal = Field(
        default=Decimal("0.0015"),
        ge=Decimal("0"),
        description="Tỷ lệ phí giao dịch mỗi chiều mua/bán (mặc định 0.15%)",
    )
    tax_rate: Decimal = Field(
        default=Decimal("0.0010"),
        ge=Decimal("0"),
        description="Thuế bán cổ phiếu tại Việt Nam (mặc định 0.10%)",
    )
    slippage_bps: Decimal = Field(
        default=Decimal("10.0000"),
        ge=Decimal("0"),
        description="Độ trượt giá giả lập tính theo basis points (10 bps = 0.10%)",
    )
    lot_size: int = Field(
        default=100,
        ge=1,
        description="Quy định lô giao dịch tối thiểu (mặc định 100 cổ phiếu/lô)",
    )
    benchmark_symbol: Optional[str] = Field(
        default=None,
        description="Mã benchmark để so sánh (nếu không truyền sẽ so sánh với Buy & Hold cùng mã)",
    )


class BacktestTradeItemResponse(BaseModel):
    """Chi tiết một lệnh giao dịch hoàn chỉnh trong kỳ Backtest."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[uuid.UUID] = None
    symbol: str
    signal_date: Optional[date] = None
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    fees: Decimal
    taxes: Decimal
    pnl: Decimal
    exit_reason: str


class BacktestRunResponse(BaseModel):
    """Báo cáo kết quả chi tiết của một phiên chạy Backtest."""

    id: uuid.UUID
    strategy_version_id: uuid.UUID
    symbol: str
    strategy_type: str
    strategy_version: int
    start_date: date
    end_date: date
    initial_capital: Decimal
    fee_rate: Decimal
    tax_rate: Decimal
    slippage_bps: Decimal
    status: str
    assumptions: Dict[str, Any]
    metrics: Dict[str, Any]
    trades: List[BacktestTradeItemResponse]
    created_at: Optional[datetime] = None
