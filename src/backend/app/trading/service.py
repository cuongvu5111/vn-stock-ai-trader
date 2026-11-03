# Ngày tạo: 2026-11-03
# Mục đích: Điều phối luồng tạo TradeProposal, kiểm tra hạn hiệu lực, Human Approval/Rejection,
#           chống duyệt trùng (Concurrency Protection) và Re-validate toàn bộ Risk trước khi đẩy sang Paper Broker.

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.indicators.models import StockSignal
from app.market_data.models import Stock
from app.portfolio.service import PortfolioService
from app.risk.engine import RiskEvaluationResult, evaluate_trade_risk_and_sizing
from app.risk.service import RiskService, record_audit_log
from app.schemas.trading import (
    OrderListResponse,
    ProposalApproveRequest,
    ProposalCreateRequest,
    ProposalListResponse,
    ProposalRejectRequest,
    TradeProposalResponse,
)
from app.trading.models import Approval, Order, TradeProposal
from app.trading.paper_broker import PaperBrokerAdapter
from app.trading.state_machine import InvalidStateTransitionError, assert_proposal_transition

ZERO = Decimal("0.00")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TradingWorkflowService:
    """Service quản lý vòng đời TradeProposal -> Human Approval -> Risk Re-validation -> Paper Order."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.risk_service = RiskService(session=session)
        self.portfolio_service = PortfolioService(session=session)
        self.paper_broker = PaperBrokerAdapter(session=session)

    def _evaluate_risk_for_symbol(
        self,
        symbol: str,
        side: str,
        entry_price: Decimal,
        stop_loss: Optional[Decimal],
        exclude_proposal_id: Optional[uuid.UUID] = None,
        requested_quantity: Optional[int] = None,
    ) -> RiskEvaluationResult:
        """Thu thập trạng thái danh mục hiện tại và gọi Risk Engine để đánh giá."""
        risk_cfg = self.risk_service.get_active_payload()
        overview = self.portfolio_service.get_portfolio_overview()

        pos_for_symbol = next((p for p in overview.positions if p.symbol == symbol), None)
        current_sym_mkt_val = pos_for_symbol.market_value if pos_for_symbol else ZERO
        avail_sell_qty = pos_for_symbol.available_quantity if pos_for_symbol else 0
        is_new_pos = pos_for_symbol is None or pos_for_symbol.quantity == 0

        # Kiểm tra có proposal hoặc order nào đang mở xung đột cho cùng symbol không
        prop_stmt = select(TradeProposal).where(
            TradeProposal.symbol == symbol,
            TradeProposal.status == "PendingApproval",
        )
        if exclude_proposal_id is not None:
            prop_stmt = prop_stmt.where(TradeProposal.id != exclude_proposal_id)
        active_prop = self.session.scalar(prop_stmt)

        active_order = self.session.scalar(
            select(Order).where(
                Order.symbol == symbol,
                Order.status.in_(["Submitted", "PartiallyFilled"]),
            )
        )
        has_conflict = (active_prop is not None) or (active_order is not None)

        daily_loss = max(ZERO, -(overview.unrealized_pnl + overview.realized_pnl))

        return evaluate_trade_risk_and_sizing(
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            nav=overview.nav,
            available_cash=overview.cash_balance,
            current_symbol_market_value=current_sym_mkt_val,
            total_portfolio_market_value=overview.market_value,
            open_positions_count=overview.open_positions_count,
            is_new_symbol_position=is_new_pos,
            available_position_qty_for_sell=avail_sell_qty,
            daily_loss_amount=daily_loss,
            has_conflicting_order_or_proposal=has_conflict,
            config=risk_cfg,
            requested_quantity=requested_quantity,
        )

    def create_proposal_from_signal(
        self, payload: ProposalCreateRequest, actor: str = "system_proposal_generator"
    ) -> TradeProposalResponse:
        """
        Tạo mới `TradeProposal` từ một `StockSignal`:
        - Chạy Risk Engine + Position Sizing.
        - Nếu Kill Switch đang bật hoặc khối lượng hợp lệ bằng 0 -> từ chối tạo Proposal (400 Bad Request).
        """
        signal = self.session.get(StockSignal, payload.signal_id)
        if signal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy tín hiệu với ID '{payload.signal_id}'.",
            )

        if signal.action not in {"BUY", "SELL"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chỉ có thể tạo TradeProposal cho tín hiệu BUY hoặc SELL (hiện tại: {signal.action}).",
            )

        stock = self.session.get(Stock, signal.stock_id)
        if stock is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy mã cổ phiếu của tín hiệu.",
            )

        # Không tạo trùng proposal PendingApproval cho cùng signal_id
        existing_prop = self.session.scalar(
            select(TradeProposal).where(
                TradeProposal.signal_id == signal.id,
                TradeProposal.status == "PendingApproval",
            )
        )
        if existing_prop is not None:
            return self._to_proposal_response(existing_prop)

        entry_price = payload.limit_price_override or signal.reference_price or Decimal("0")
        stop_loss = payload.stop_loss_override or signal.stop_loss

        risk_eval = self._evaluate_risk_for_symbol(
            symbol=stock.symbol,
            side=signal.action,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        if not risk_eval.passed or risk_eval.proposed_quantity <= 0:
            record_audit_log(
                session=self.session,
                actor=actor,
                action="PROPOSAL_BLOCKED_BY_RISK_ENGINE",
                entity_type="StockSignal",
                entity_id=str(signal.id),
                before_state=None,
                after_state={"reasons": risk_eval.reasons, "details": risk_eval.details},
            )
            self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Risk Engine từ chối tạo Proposal: {'; '.join(risk_eval.reasons)}",
            )

        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + timedelta(minutes=payload.expiry_minutes)

        proposal = TradeProposal(
            signal_id=signal.id,
            symbol=stock.symbol,
            side=signal.action,
            proposed_quantity=risk_eval.proposed_quantity,
            limit_price=entry_price,
            stop_loss=stop_loss,
            estimated_cost=risk_eval.estimated_cost,
            risk_amount=risk_eval.risk_amount,
            risk_check_result={
                "initial_check_passed": True,
                "checked_at_utc": now_utc.isoformat(),
                "reasons": risk_eval.reasons,
                "sizing_details": risk_eval.details,
            },
            status="PendingApproval",
            expires_at=expires_at,
        )
        self.session.add(proposal)
        self.session.flush()

        record_audit_log(
            session=self.session,
            actor=actor,
            action="PROPOSAL_CREATED",
            entity_type="TradeProposal",
            entity_id=str(proposal.id),
            before_state=None,
            after_state={
                "symbol": proposal.symbol,
                "side": proposal.side,
                "proposed_quantity": proposal.proposed_quantity,
                "limit_price": str(proposal.limit_price),
                "stop_loss": str(proposal.stop_loss) if proposal.stop_loss else None,
                "status": proposal.status,
                "expires_at": proposal.expires_at.isoformat(),
            },
        )

        self.session.commit()
        self.session.refresh(proposal)
        return self._to_proposal_response(proposal)

    def approve_proposal(
        self, proposal_id: uuid.UUID, payload: ProposalApproveRequest
    ) -> TradeProposalResponse:
        """
        Quy trình phê duyệt đề xuất giao dịch bởi con người (Mục 9.4 & 10.1):
        1. Khóa dòng Proposal trong transaction (`with_for_update()`) để chống duyệt trùng đồng thời.
        2. Kiểm tra trạng thái hiện tại phải là `PendingApproval`.
        3. Kiểm tra hạn hiệu lực (`expires_at`); nếu quá hạn -> chuyển sang `Expired` và báo lỗi.
        4. Kiểm tra khớp snapshot (`expected_quantity`, `expected_limit_price`, `expected_stop_loss`).
        5. Tạo bản ghi `trading.approvals` (`decision="APPROVED"`).
        6. Chuyển qua bước `RiskValidation` và **Re-validate toàn bộ Risk** tại thời điểm duyệt:
           - Nếu vi phạm (ví dụ Kill Switch vừa bật hoặc hết tiền) -> chuyển sang `Blocked` và không tạo Order.
           - Nếu đạt -> chuyển sang `Submitted` và gọi `PaperBrokerAdapter` tạo đúng 1 `Order`.
        """
        proposal = self.session.scalar(
            select(TradeProposal)
            .where(TradeProposal.id == proposal_id)
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy TradeProposal với ID '{proposal_id}'.",
            )

        if proposal.status != "PendingApproval":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal '{proposal_id}' không còn ở trạng thái chờ duyệt (trạng thái hiện tại: {proposal.status}).",
            )

        now_utc = datetime.now(timezone.utc)
        if now_utc >= _ensure_utc(proposal.expires_at):
            assert_proposal_transition(proposal.status, "Expired")
            proposal.status = "Expired"
            record_audit_log(
                session=self.session,
                actor=payload.approved_by,
                action="PROPOSAL_EXPIRED_ON_APPROVE_ATTEMPT",
                entity_type="TradeProposal",
                entity_id=str(proposal.id),
                before_state={"status": "PendingApproval"},
                after_state={"status": "Expired", "expires_at": proposal.expires_at.isoformat()},
            )
            self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Đề xuất giao dịch đã hết hạn (Expired) và không thể phê duyệt.",
            )

        # Kiểm tra tính toàn vẹn snapshot đề xuất (Mục 9.4)
        if payload.expected_quantity is not None and payload.expected_quantity != proposal.proposed_quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Snapshot không khớp: khối lượng đề xuất ({proposal.proposed_quantity}) khác với khối lượng xác nhận ({payload.expected_quantity}).",
            )
        if payload.expected_limit_price is not None and payload.expected_limit_price != proposal.limit_price:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Snapshot không khớp: limit_price đã thay đổi, yêu cầu duyệt lại.",
            )
        if payload.expected_stop_loss is not None and payload.expected_stop_loss != proposal.stop_loss:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Snapshot không khớp: stop_loss đã thay đổi, yêu cầu duyệt lại.",
            )

        assert_proposal_transition(proposal.status, "Approved")
        proposal.status = "Approved"

        approval = Approval(
            proposal_id=proposal.id,
            decision="APPROVED",
            approved_by=payload.approved_by,
            comment=payload.comment,
        )
        self.session.add(approval)
        self.session.flush()

        # Bước bắt buộc: Re-validate toàn bộ Risk tại thời điểm Approve (Mục 9.3)
        assert_proposal_transition(proposal.status, "RiskValidation")
        proposal.status = "RiskValidation"

        reval_result = self._evaluate_risk_for_symbol(
            symbol=proposal.symbol,
            side=proposal.side,
            entry_price=proposal.limit_price or Decimal("0"),
            stop_loss=proposal.stop_loss,
            exclude_proposal_id=proposal.id,
            requested_quantity=proposal.proposed_quantity,
        )

        risk_history = dict(proposal.risk_check_result or {})
        risk_history["approval_revalidation"] = {
            "passed": reval_result.passed,
            "revalidated_at_utc": now_utc.isoformat(),
            "reasons": reval_result.reasons,
            "details": reval_result.details,
        }
        proposal.risk_check_result = risk_history

        if not reval_result.passed:
            assert_proposal_transition(proposal.status, "Blocked")
            proposal.status = "Blocked"
            record_audit_log(
                session=self.session,
                actor=payload.approved_by,
                action="PROPOSAL_BLOCKED_ON_REVALIDATION",
                entity_type="TradeProposal",
                entity_id=str(proposal.id),
                before_state={"status": "RiskValidation"},
                after_state={"status": "Blocked", "reasons": reval_result.reasons},
            )
            self.session.commit()
            self.session.refresh(proposal)
            return self._to_proposal_response(proposal)

        assert_proposal_transition(proposal.status, "Submitted")
        proposal.status = "Submitted"

        try:
            order = self.paper_broker.create_paper_order_from_approved_proposal(
                proposal=proposal,
                approval=approval,
                order_type="LIMIT",
                auto_fill_immediately=payload.auto_submit_and_fill_in_paper,
            )
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phát hiện xung đột duyệt lệnh đồng thời (Concurrency protection).",
            ) from exc

        record_audit_log(
            session=self.session,
            actor=payload.approved_by,
            action="PROPOSAL_APPROVED_AND_ORDER_CREATED",
            entity_type="TradeProposal",
            entity_id=str(proposal.id),
            before_state={"status": "PendingApproval"},
            after_state={"status": proposal.status, "order_id": str(order.id)},
        )

        self.session.commit()
        self.session.refresh(proposal)
        return self._to_proposal_response(proposal, order_id=order.id)

    def reject_proposal(
        self, proposal_id: uuid.UUID, payload: ProposalRejectRequest
    ) -> TradeProposalResponse:
        """Từ chối đề xuất giao dịch và ghi nhận quyết định vào `trading.approvals` + `system.audit_logs`."""
        proposal = self.session.scalar(
            select(TradeProposal)
            .where(TradeProposal.id == proposal_id)
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy TradeProposal với ID '{proposal_id}'.",
            )

        try:
            assert_proposal_transition(proposal.status, "Rejected")
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        proposal.status = "Rejected"
        self.session.add(
            Approval(
                proposal_id=proposal.id,
                decision="REJECTED",
                approved_by=payload.rejected_by,
                comment=payload.comment,
            )
        )

        record_audit_log(
            session=self.session,
            actor=payload.rejected_by,
            action="PROPOSAL_REJECTED",
            entity_type="TradeProposal",
            entity_id=str(proposal.id),
            before_state={"status": "PendingApproval"},
            after_state={"status": "Rejected", "comment": payload.comment},
        )

        self.session.commit()
        self.session.refresh(proposal)
        return self._to_proposal_response(proposal)

    def list_proposals(self, status_filter: Optional[str] = None, limit: int = 100) -> ProposalListResponse:
        stmt = select(TradeProposal)
        if status_filter:
            stmt = stmt.where(TradeProposal.status == status_filter.strip())
        rows = self.session.scalars(
            stmt.order_by(TradeProposal.created_at.desc()).limit(limit)
        ).all()
        return ProposalListResponse(
            total=len(rows),
            items=[self._to_proposal_response(r) for r in rows],
        )

    def list_orders(self, status_filter: Optional[str] = None, limit: int = 100) -> OrderListResponse:
        stmt = select(Order)
        if status_filter:
            stmt = stmt.where(Order.status == status_filter.strip())
        rows = self.session.scalars(
            stmt.order_by(Order.created_at.desc()).limit(limit)
        ).all()
        return OrderListResponse(
            total=len(rows),
            items=[self.paper_broker.build_order_response(o) for o in rows],
        )

    def _to_proposal_response(
        self, proposal: TradeProposal, order_id: Optional[uuid.UUID] = None
    ) -> TradeProposalResponse:
        resolved_order_id = order_id
        if resolved_order_id is None:
            ord_row = self.session.scalar(
                select(Order.id).where(Order.proposal_id == proposal.id)
            )
            resolved_order_id = ord_row

        res = TradeProposalResponse.model_validate(proposal)
        res.order_id = resolved_order_id
        return res
