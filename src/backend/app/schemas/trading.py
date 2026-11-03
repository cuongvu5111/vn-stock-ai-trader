# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Pydantic v2 DTOs cho Risk Management, Trade Proposals, Human Approvals, Paper Orders và Portfolio.

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RiskConfigPayload(BaseModel):
    """Cấu hình các hạn mức rủi ro và Kill Switch (Mục 9.1)."""

    max_position_percent: Decimal = Field(default=Decimal("20"), gt=Decimal("0"), le=Decimal("100"))
    max_risk_per_trade_percent: Decimal = Field(default=Decimal("1"), gt=Decimal("0"), le=Decimal("10"))
    max_daily_loss_percent: Decimal = Field(default=Decimal("2"), gt=Decimal("0"), le=Decimal("20"))
    max_open_positions: int = Field(default=5, ge=1, le=50)
    max_portfolio_allocation_percent: Decimal = Field(default=Decimal("70"), gt=Decimal("0"), le=Decimal("100"))
    require_human_approval: bool = Field(default=True)
    trading_enabled: bool = Field(default=True, description="Kill Switch: False = chặn toàn bộ lệnh mới")
    fee_rate: Decimal = Field(default=Decimal("0.0015"), ge=Decimal("0"))
    tax_rate: Decimal = Field(default=Decimal("0.0010"), ge=Decimal("0"))
    slippage_bps: Decimal = Field(default=Decimal("10.0000"), ge=Decimal("0"))
    lot_size: int = Field(default=100, ge=1)


class RiskConfigUpdateRequest(BaseModel):
    """Yêu cầu cập nhật cấu hình rủi ro hoặc kích hoạt Kill Switch (bắt buộc ghi Audit Log)."""

    actor: str = Field(default="trader_user", min_length=1, max_length=100)
    reason: str = Field(default="Cập nhật cấu hình hạn mức rủi ro / Kill Switch", min_length=3)
    configuration: RiskConfigPayload


class AuditLogItemResponse(BaseModel):
    """Một bản ghi nhật ký kiểm toán (`system.audit_logs`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    before_state: Optional[Dict[str, Any]]
    after_state: Optional[Dict[str, Any]]
    correlation_id: Optional[str]
    created_at: datetime


class RiskStatusResponse(BaseModel):
    """Trạng thái rủi ro hiện hành của hệ thống kèm lịch sử audit."""

    config_id: uuid.UUID
    config_name: str
    configuration: RiskConfigPayload
    kill_switch_active: bool
    recent_audit_logs: List[AuditLogItemResponse]


class ProposalCreateRequest(BaseModel):
    """Yêu cầu tạo đề xuất giao dịch (`TradeProposal`) từ một tín hiệu."""

    signal_id: uuid.UUID
    order_type: str = Field(default="LIMIT", description="LIMIT hoặc MARKET")
    limit_price_override: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    stop_loss_override: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    expiry_minutes: int = Field(
        default=240,
        ge=1,
        le=4320,
        description="Thời hạn hiệu lực của đề xuất tính bằng phút (mặc định 4 giờ)",
    )


class ProposalApproveRequest(BaseModel):
    """Yêu cầu phê duyệt đề xuất giao dịch bởi con người (Human Approval)."""

    approved_by: str = Field(..., min_length=1, max_length=100, description="Định danh người phê duyệt")
    comment: Optional[str] = Field(default=None, max_length=500)
    expected_quantity: Optional[int] = Field(
        default=None,
        description="Nếu truyền vào, hệ thống kiểm tra khớp đúng proposed_quantity trong snapshot của proposal",
    )
    expected_limit_price: Optional[Decimal] = Field(
        default=None,
        description="Nếu truyền vào, hệ thống kiểm tra khớp đúng limit_price của proposal",
    )
    expected_stop_loss: Optional[Decimal] = Field(
        default=None,
        description="Nếu truyền vào, hệ thống kiểm tra khớp đúng stop_loss của proposal",
    )
    auto_submit_and_fill_in_paper: bool = Field(
        default=False,
        description="Nếu False, lệnh được gửi sang Paper Broker ở trạng thái Submitted để khớp riêng (hỗ trợ partial fill).",
    )


class ProposalRejectRequest(BaseModel):
    """Yêu cầu từ chối đề xuất giao dịch."""

    rejected_by: str = Field(..., min_length=1, max_length=100)
    comment: Optional[str] = Field(default="Người dùng từ chối đề xuất.", max_length=500)


class TradeProposalResponse(BaseModel):
    """Thông tin chi tiết một TradeProposal."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    signal_id: uuid.UUID
    symbol: str
    side: str
    proposed_quantity: int
    limit_price: Optional[Decimal]
    stop_loss: Optional[Decimal]
    estimated_cost: Optional[Decimal]
    risk_amount: Optional[Decimal]
    risk_check_result: Optional[Dict[str, Any]]
    status: str
    expires_at: datetime
    created_at: datetime
    order_id: Optional[uuid.UUID] = None


class ProposalListResponse(BaseModel):
    total: int
    items: List[TradeProposalResponse]


class ExecutionItemResponse(BaseModel):
    """Chi tiết một lần khớp lệnh (`trading.executions`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    execution_id: str
    quantity: int
    price: Decimal
    fee: Decimal
    tax: Decimal
    executed_at: datetime


class OrderResponse(BaseModel):
    """Thông tin một lệnh Paper kèm danh sách các lần khớp (`executions`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proposal_id: Optional[uuid.UUID]
    broker_name: str
    broker_order_id: Optional[str]
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: int
    filled_quantity: int
    limit_price: Optional[Decimal]
    average_fill_price: Optional[Decimal]
    status: str
    created_at: datetime
    updated_at: datetime
    executions: List[ExecutionItemResponse] = Field(default_factory=list)


class OrderListResponse(BaseModel):
    total: int
    items: List[OrderResponse]


class SimulateFillRequest(BaseModel):
    """Yêu cầu mô phỏng khớp lệnh (toàn phần hoặc một phần) trên Paper Broker."""

    fill_quantity: int = Field(..., ge=1, description="Khối lượng khớp trong đợt này")
    fill_price: Optional[Decimal] = Field(
        default=None,
        gt=Decimal("0"),
        description="Giá khớp (nếu để trống sẽ dùng limit_price của lệnh có cộng/trừ slippage)",
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="Mã định danh khớp lệnh duy nhất (tự sinh nếu để trống)",
    )


class PositionItemResponse(BaseModel):
    """Thông tin một vị thế cổ phiếu trong danh mục."""

    symbol: str
    exchange: str
    quantity: int
    available_quantity: int
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    weight_pct: Decimal


class PortfolioOverviewResponse(BaseModel):
    """Tổng quan danh mục đầu tư Paper Trading."""

    account_id: uuid.UUID
    account_name: str
    account_type: str
    currency: str
    initial_capital: Decimal
    cash_balance: Decimal
    market_value: Decimal
    nav: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    allocation_pct: Decimal
    open_positions_count: int
    positions: List[PositionItemResponse]


class DailySnapshotItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    snapshot_date: date
    cash_balance: Decimal
    market_value: Decimal
    nav: Decimal
    unrealized_pnl: Optional[Decimal]
    realized_pnl: Optional[Decimal]


class PortfolioSnapshotsResponse(BaseModel):
    total: int
    items: List[DailySnapshotItemResponse]


class ReconciliationReportResponse(BaseModel):
    """Báo cáo kết quả đối soát và tái dựng danh mục từ sổ cái gốc."""

    account_id: uuid.UUID
    is_consistent_before_rebuild: bool
    previous_cash_balance: Decimal
    rebuilt_cash_balance: Decimal
    discrepancies: List[str]
    positions_rebuilt_count: int
    reconciled_at: datetime


class CashTransactionItemResponse(BaseModel):
    """Một bút toán trong sổ cái tiền mặt (`portfolio.cash_transactions`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    transaction_type: str
    amount: Decimal
    reference_type: Optional[str]
    reference_id: Optional[uuid.UUID]
    description: Optional[str]
    created_at: datetime


class CashLedgerListResponse(BaseModel):
    total: int
    items: List[CashTransactionItemResponse]
