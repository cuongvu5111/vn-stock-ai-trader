# Ngày tạo: 2026-11-03
# Mục đích: Cung cấp REST API endpoints cho Risk Management, Trade Proposals, Human Approvals, Paper Orders và Portfolio.

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.portfolio.service import PortfolioService
from app.risk.service import RiskService
from app.schemas.trading import (
    CashLedgerListResponse,
    DailySnapshotItemResponse,
    OrderListResponse,
    OrderResponse,
    PortfolioOverviewResponse,
    PortfolioSnapshotsResponse,
    ProposalApproveRequest,
    ProposalCreateRequest,
    ProposalListResponse,
    ProposalRejectRequest,
    ReconciliationReportResponse,
    RiskConfigUpdateRequest,
    RiskStatusResponse,
    SimulateFillRequest,
    TradeProposalResponse,
)
from app.trading.paper_broker import PaperBrokerAdapter
from app.trading.service import TradingWorkflowService

router = APIRouter(tags=["Risk, Trading & Portfolio"])


@router.get("/risk", response_model=RiskStatusResponse, summary="Lấy trạng thái cấu hình rủi ro và Kill Switch")
def get_risk_status(session: Session = Depends(get_db_session)) -> RiskStatusResponse:
    service = RiskService(session=session)
    return service.get_risk_status()


@router.put("/risk", response_model=RiskStatusResponse, summary="Cập nhật cấu hình rủi ro hoặc kích hoạt Kill Switch")
def update_risk_config(
    payload: RiskConfigUpdateRequest,
    session: Session = Depends(get_db_session),
) -> RiskStatusResponse:
    service = RiskService(session=session)
    return service.update_risk_config(request=payload)


@router.post("/proposals", response_model=TradeProposalResponse, summary="Tạo TradeProposal từ một tín hiệu")
def create_proposal(
    payload: ProposalCreateRequest,
    session: Session = Depends(get_db_session),
) -> TradeProposalResponse:
    service = TradingWorkflowService(session=session)
    return service.create_proposal_from_signal(payload=payload)


@router.get("/proposals", response_model=ProposalListResponse, summary="Danh sách các đề xuất giao dịch (TradeProposals)")
def list_proposals(
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái (PendingApproval, Submitted, Blocked, ...)"),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> ProposalListResponse:
    service = TradingWorkflowService(session=session)
    return service.list_proposals(status_filter=status, limit=limit)


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=TradeProposalResponse,
    summary="Phê duyệt đề xuất giao dịch bởi con người (Human Approval) và Re-validate Risk",
)
def approve_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalApproveRequest,
    session: Session = Depends(get_db_session),
) -> TradeProposalResponse:
    service = TradingWorkflowService(session=session)
    return service.approve_proposal(proposal_id=proposal_id, payload=payload)


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=TradeProposalResponse,
    summary="Từ chối đề xuất giao dịch",
)
def reject_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalRejectRequest,
    session: Session = Depends(get_db_session),
) -> TradeProposalResponse:
    service = TradingWorkflowService(session=session)
    return service.reject_proposal(proposal_id=proposal_id, payload=payload)


@router.get("/orders", response_model=OrderListResponse, summary="Danh sách các lệnh Paper kèm chi tiết khớp lệnh")
def list_orders(
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái (Submitted, PartiallyFilled, Filled, Cancelled)"),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> OrderListResponse:
    service = TradingWorkflowService(session=session)
    return service.list_orders(status_filter=status, limit=limit)


@router.post(
    "/orders/{order_id}/simulate-fill",
    response_model=OrderResponse,
    summary="Mô phỏng khớp lệnh (toàn phần hoặc một phần - Partial Fill) trên Paper Broker",
)
def simulate_order_fill(
    order_id: uuid.UUID,
    payload: SimulateFillRequest,
    session: Session = Depends(get_db_session),
) -> OrderResponse:
    broker = PaperBrokerAdapter(session=session)
    return broker.execute_fill(order_id=order_id, payload=payload)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Hủy lệnh Paper đang mở",
)
def cancel_order(
    order_id: uuid.UUID,
    actor: str = Query(default="trader_user"),
    session: Session = Depends(get_db_session),
) -> OrderResponse:
    broker = PaperBrokerAdapter(session=session)
    return broker.cancel_order(order_id=order_id, actor=actor)


@router.get("/portfolio", response_model=PortfolioOverviewResponse, summary="Tổng quan danh mục đầu tư Paper Trading")
def get_portfolio_overview(session: Session = Depends(get_db_session)) -> PortfolioOverviewResponse:
    service = PortfolioService(session=session)
    return service.get_portfolio_overview()


@router.get(
    "/portfolio/snapshots",
    response_model=PortfolioSnapshotsResponse,
    summary="Lịch sử bản chụp NAV cuối ngày (Daily Snapshots)",
)
def list_portfolio_snapshots(
    limit: int = Query(default=90, ge=1, le=365),
    session: Session = Depends(get_db_session),
) -> PortfolioSnapshotsResponse:
    service = PortfolioService(session=session)
    return service.list_snapshots(limit=limit)


@router.post(
    "/portfolio/snapshots",
    response_model=DailySnapshotItemResponse,
    summary="Chốt bản chụp NAV cuối ngày hiện tại",
)
def create_portfolio_snapshot(
    snapshot_date: Optional[date] = Query(default=None),
    session: Session = Depends(get_db_session),
) -> DailySnapshotItemResponse:
    service = PortfolioService(session=session)
    return service.create_or_update_daily_snapshot(snapshot_date=snapshot_date)


@router.post(
    "/portfolio/reconcile",
    response_model=ReconciliationReportResponse,
    summary="Đối soát và tái dựng toàn bộ Cash Balance & Positions từ sổ cái gốc (CashTransactions & Executions)",
)
def reconcile_portfolio(
    actor: str = Query(default="trader_user"),
    session: Session = Depends(get_db_session),
) -> ReconciliationReportResponse:
    service = PortfolioService(session=session)
    return service.reconcile_and_rebuild_portfolio(actor=actor)


@router.get(
    "/portfolio/ledger",
    response_model=CashLedgerListResponse,
    summary="Lịch sử bút toán sổ cái tiền mặt (portfolio.cash_transactions)",
)
def list_portfolio_ledger(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> CashLedgerListResponse:
    service = PortfolioService(session=session)
    return service.list_cash_transactions(limit=limit)
