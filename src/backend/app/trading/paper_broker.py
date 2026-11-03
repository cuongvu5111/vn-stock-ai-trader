# Ngày tạo: 2026-11-03
# Mục đích: Triển khai PaperBrokerAdapter mô phỏng đặt lệnh, khớp một phần (partial fill), khớp toàn bộ (full fill) và hủy lệnh.
# Lý do:
#   - MVP tuyệt đối không gửi lệnh thật (No Live Broker).
#   - Hỗ trợ deterministic simulation với phí, thuế, slippage và cập nhật nhất quán sang sổ cái Portfolio.

import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.portfolio.service import PortfolioService
from app.risk.service import RiskService, record_audit_log
from app.schemas.trading import ExecutionItemResponse, OrderResponse, SimulateFillRequest
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.state_machine import InvalidStateTransitionError, assert_order_transition

Q_MONEY_2 = Decimal("0.01")
Q_PRICE_4 = Decimal("0.0001")
TEN_THOUSAND = Decimal("10000")
ZERO = Decimal("0.00")


def _q2(val: Decimal) -> Decimal:
    return val.quantize(Q_MONEY_2, rounding=ROUND_HALF_UP)


def _q4(val: Decimal) -> Decimal:
    return val.quantize(Q_PRICE_4, rounding=ROUND_HALF_UP)


class PaperBrokerAdapter:
    """
    Adapter mô phỏng môi trường giao dịch giấy (Paper Broker).
    Chỉ chấp nhận tạo Order khi có bản ghi `Approval(decision='APPROVED')` hợp lệ.
    """

    broker_name: str = "PAPER"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.risk_service = RiskService(session=session)
        self.portfolio_service = PortfolioService(session=session)

    def submit_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: Decimal | None = None,
    ) -> Dict[str, Any]:
        """Phương thức chuẩn theo BrokerAdapter Protocol."""
        return {
            "broker_name": self.broker_name,
            "broker_order_id": f"PB-{uuid.uuid4().hex[:12].upper()}",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": str(limit_price) if limit_price else None,
            "status": "Submitted",
        }

    def create_paper_order_from_approved_proposal(
        self,
        proposal: TradeProposal,
        approval: Approval,
        order_type: str = "LIMIT",
        auto_fill_immediately: bool = False,
    ) -> Order:
        """
        Tạo bản ghi `trading.orders` từ một `TradeProposal` đã được phê duyệt (`Approved`).
        Bắt buộc kiểm tra `approval.decision == "APPROVED"` và `client_order_id` unique.
        """
        if approval.decision != "APPROVED" or approval.proposal_id != proposal.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không thể tạo Paper Order khi Proposal chưa có bản ghi Human Approval hợp lệ.",
            )

        client_order_id = f"PROP-{proposal.id}"
        existing_order = self.session.scalar(
            select(Order).where(Order.client_order_id == client_order_id)
        )
        if existing_order is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal '{proposal.id}' đã được tạo Order trước đó (client_order_id={client_order_id}).",
            )

        broker_meta = self.submit_order(
            client_order_id=client_order_id,
            symbol=proposal.symbol,
            side=proposal.side,
            order_type=order_type,
            quantity=proposal.proposed_quantity,
            limit_price=proposal.limit_price,
        )

        order = Order(
            proposal_id=proposal.id,
            broker_name=self.broker_name,
            broker_order_id=broker_meta["broker_order_id"],
            client_order_id=client_order_id,
            symbol=proposal.symbol,
            side=proposal.side,
            order_type=order_type.upper(),
            quantity=proposal.proposed_quantity,
            filled_quantity=0,
            limit_price=proposal.limit_price,
            average_fill_price=None,
            status="Submitted",
        )
        self.session.add(order)
        self.session.flush()

        record_audit_log(
            session=self.session,
            actor=approval.approved_by,
            action="PAPER_ORDER_SUBMITTED",
            entity_type="Order",
            entity_id=str(order.id),
            before_state=None,
            after_state={
                "proposal_id": str(proposal.id),
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "limit_price": str(order.limit_price),
                "status": order.status,
            },
        )

        if auto_fill_immediately:
            self.execute_fill(
                order_id=order.id,
                payload=SimulateFillRequest(
                    fill_quantity=order.quantity,
                    fill_price=order.limit_price,
                ),
                actor="paper_broker_auto_sim",
            )

        return order

    def execute_fill(
        self,
        order_id: uuid.UUID,
        payload: SimulateFillRequest,
        actor: str = "paper_broker_simulator",
    ) -> OrderResponse:
        """
        Mô phỏng khớp lệnh (toàn phần hoặc một phần - Partial Fill) cho một Order:
        - Kiểm tra trạng thái hợp lệ (`Submitted` hoặc `PartiallyFilled`).
        - Kiểm tra `fill_quantity <= remaining_quantity`.
        - Tính phí (`fee_rate`), thuế bán (`tax_rate`), độ trượt giá (`slippage_bps` nếu không truyền `fill_price`).
        - Tạo bản ghi `trading.executions` với `execution_id` unique.
        - Cập nhật `filled_quantity`, `average_fill_price`, `Order.status` (`PartiallyFilled` hoặc `Filled`).
        - Cập nhật Sổ cái tiền mặt (`cash_transactions`) và vị thế (`positions`).
        """
        order = self.session.get(Order, order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy lệnh Paper với ID '{order_id}'.",
            )

        remaining_qty = order.quantity - order.filled_quantity
        if payload.fill_quantity > remaining_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Khối lượng khớp ({payload.fill_quantity}) vượt quá khối lượng còn lại chưa khớp ({remaining_qty})."
                ),
            )

        target_status = "Filled" if (order.filled_quantity + payload.fill_quantity == order.quantity) else "PartiallyFilled"
        try:
            assert_order_transition(order.status, target_status)
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        risk_cfg = self.risk_service.get_active_payload()
        slippage_rate = risk_cfg.slippage_bps / TEN_THOUSAND

        if payload.fill_price is not None:
            exec_price = _q4(payload.fill_price)
        else:
            base_price = order.limit_price or Decimal("10000.0000")
            if order.side == "BUY":
                exec_price = _q4(base_price * (Decimal("1") + slippage_rate))
            else:
                exec_price = _q4(base_price * (Decimal("1") - slippage_rate))

        gross_val = _q2(Decimal(payload.fill_quantity) * exec_price)
        fee = _q2(gross_val * risk_cfg.fee_rate)
        tax = _q2(gross_val * risk_cfg.tax_rate) if order.side == "SELL" else ZERO

        # Kiểm tra sức mua thực tế trước khi khớp BUY
        if order.side == "BUY":
            account = self.portfolio_service.get_or_create_default_paper_account()
            required_cash = _q2(gross_val + fee)
            if account.cash_balance < required_cash:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Không đủ tiền mặt để khớp lệnh ({account.cash_balance} < {required_cash}).",
                )

        exec_uid = payload.execution_id or f"EXEC-{uuid.uuid4().hex[:16].upper()}"
        existing_exec = self.session.scalar(
            select(Execution).where(Execution.execution_id == exec_uid)
        )
        if existing_exec is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Mã execution_id '{exec_uid}' đã tồn tại (Idempotency protection).",
            )

        execution = Execution(
            order_id=order.id,
            execution_id=exec_uid,
            quantity=payload.fill_quantity,
            price=exec_price,
            fee=fee,
            tax=tax,
        )
        self.session.add(execution)
        self.session.flush()

        # Cập nhật giá khớp trung bình gia quyền và trạng thái Order
        prev_filled = order.filled_quantity
        prev_avg = order.average_fill_price or Decimal("0.0000")
        new_filled = prev_filled + payload.fill_quantity
        new_avg_price = _q4(
            ((Decimal(prev_filled) * prev_avg) + (Decimal(payload.fill_quantity) * exec_price))
            / Decimal(new_filled)
        )

        before_state = {
            "status": order.status,
            "filled_quantity": prev_filled,
            "average_fill_price": str(order.average_fill_price) if order.average_fill_price else None,
        }

        order.filled_quantity = new_filled
        order.average_fill_price = new_avg_price
        order.status = target_status

        # Cập nhật Sổ cái tiền mặt và Vị thế danh mục trong cùng transaction
        self.portfolio_service.apply_execution_to_ledger_and_positions(
            order=order,
            execution=execution,
        )

        record_audit_log(
            session=self.session,
            actor=actor,
            action=f"ORDER_{target_status.upper()}",
            entity_type="Order",
            entity_id=str(order.id),
            before_state=before_state,
            after_state={
                "status": order.status,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": str(order.average_fill_price),
                "execution_id": execution.execution_id,
            },
        )

        self.session.commit()
        self.session.refresh(order)
        return self.build_order_response(order)

    def cancel_order(self, order_id: uuid.UUID, actor: str = "trader_user") -> OrderResponse:
        """Hủy lệnh Paper đang ở trạng thái `Submitted` hoặc `PartiallyFilled`."""
        order = self.session.get(Order, order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy lệnh Paper với ID '{order_id}'.",
            )

        try:
            assert_order_transition(order.status, "Cancelled")
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        before_status = order.status
        order.status = "Cancelled"

        record_audit_log(
            session=self.session,
            actor=actor,
            action="PAPER_ORDER_CANCELLED",
            entity_type="Order",
            entity_id=str(order.id),
            before_state={"status": before_status, "filled_quantity": order.filled_quantity},
            after_state={"status": "Cancelled", "filled_quantity": order.filled_quantity},
        )

        self.session.commit()
        self.session.refresh(order)
        return self.build_order_response(order)

    def build_order_response(self, order: Order) -> OrderResponse:
        execs = self.session.scalars(
            select(Execution)
            .where(Execution.order_id == order.id)
            .order_by(Execution.executed_at.asc())
        ).all()
        res = OrderResponse.model_validate(order)
        res.executions = [ExecutionItemResponse.model_validate(e) for e in execs]
        return res
