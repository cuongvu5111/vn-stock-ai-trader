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

from app.core import clock
from app.core.config import get_settings
from app.portfolio.service import PortfolioService
from app.risk.service import RiskService, record_audit_log
from app.schemas.trading import ExecutionItemResponse, OrderResponse, SimulateFillRequest
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.settlement import add_trading_days
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
        Bắt buộc `approval` đã lưu trong DB, `decision == "APPROVED"`, đúng `proposal_id`, chưa sinh Order nào
        trước đó (unique `approval_id`) và `client_order_id` unique. Order luôn lưu `approval_id` để truy vết.
        """
        # Đối chiếu cả đối tượng truyền vào lẫn dòng đang lưu trong DB (chọn cột, không qua identity map):
        # không tin một Approval tự dựng hoặc bị sửa trong bộ nhớ mà chưa được ghi nhận.
        stored_approval = (
            self.session.execute(
                select(Approval.decision, Approval.proposal_id).where(Approval.id == approval.id)
            ).one_or_none()
            if approval.id is not None
            else None
        )
        if (
            stored_approval is None
            or approval.decision != "APPROVED"
            or approval.proposal_id != proposal.id
            or stored_approval.decision != "APPROVED"
            or stored_approval.proposal_id != proposal.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không thể tạo Paper Order khi Proposal chưa có bản ghi Human Approval hợp lệ.",
            )

        order_of_approval = self.session.scalar(select(Order.id).where(Order.approval_id == approval.id))
        if order_of_approval is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Approval '{approval.id}' đã được dùng để tạo Order '{order_of_approval}', không thể tạo thêm.",
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
            approval_id=approval.id,
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
                "approval_id": str(approval.id),
                "approver_user_id": str(approval.approver_user_id) if approval.approver_user_id else None,
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
        - SELL chỉ được khớp tối đa số lượng đã thanh toán T+N (`settled available`); vi phạm thì từ chối trước khi ghi bất kỳ bút toán nào.
        - Tạo bản ghi `trading.executions` với `execution_id` unique, `trade_date` (giờ thị trường) và `settlement_date` (T+N).
        - Cập nhật `filled_quantity`, `average_fill_price`, `Order.status` (`PartiallyFilled` hoặc `Filled`).
        - Cập nhật Sổ cái tiền mặt (`cash_transactions`) và vị thế (`positions`).

        Đồng thời nhiều worker: khóa dòng Order (`FOR UPDATE`), rồi dòng Stock của mã, rồi dòng Account, luôn theo thứ tự
        Order -> Stock -> Account (-> Position khi ghi sổ cái) để không deadlock. Mọi kiểm tra còn lại/trạng thái/khả dụng
        T+N/sức mua chỉ được tính SAU khi giữ khóa và TRƯỚC khi chèn Execution, nên không thể khớp vượt quantity của Order,
        bán vượt số cổ phiếu đã thanh toán giữa nhiều lệnh SELL cùng mã, hay mua vượt tiền mặt giữa nhiều lệnh BUY khác mã.
        Khóa giữ tới commit/rollback ở cuối hàm (hoặc ở caller khi hàm ném lỗi).
        """
        # populate_existing: nếu Order đã nằm trong identity map của session thì vẫn phải đọc lại
        # filled_quantity/status mới nhất mà worker khác vừa commit trong lúc chờ khóa.
        order = self.session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
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

        # Khóa Stock sau khi Order đã kiểm tra hợp lệ (lệnh bị từ chối không giữ khóa mã); mọi fill cùng mã xếp hàng tại đây
        self.portfolio_service.lock_symbol_for_update(order.symbol)
        # Khóa Account sau Order/Stock (thứ tự cố định Order -> Stock -> Account) và giữ tới commit/rollback: số dư được
        # đọc lại dưới khóa nên kiểm tra sức mua và ghi sổ cái luôn dựa trên tiền mặt mới nhất, hai BUY khác mã
        # không thể cùng vượt sức mua hay ghi đè cash_balance của nhau (SELL cũng cộng tiền nên khóa chung đường này).
        account = self.portfolio_service.get_or_create_default_paper_account(for_update=True)

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
            required_cash = _q2(gross_val + fee)
            if account.cash_balance < required_cash:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Không đủ tiền mặt để khớp lệnh ({account.cash_balance} < {required_cash}).",
                )

        # Một mốc thời gian duy nhất cho executed_at và trade_date để không lệch ngày quanh nửa đêm giờ thị trường
        executed_at = clock.utc_now()
        trade_date = clock.market_today(executed_at)
        settlement_date = add_trading_days(trade_date, get_settings().SETTLEMENT_LAG_TRADING_DAYS)

        # Cổ phiếu mua chưa về tài khoản (chưa tới T+N) thì không được bán; chặn trước khi tạo Execution/ledger
        if order.side == "SELL":
            settled_available = self.portfolio_service.get_settled_available_quantity(
                order.symbol, as_of=trade_date
            )
            if payload.fill_quantity > settled_available:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Khối lượng bán ({payload.fill_quantity}) vượt số cổ phiếu đã thanh toán T+"
                        f"{get_settings().SETTLEMENT_LAG_TRADING_DAYS} có thể bán của {order.symbol} "
                        f"({settled_available}) tại ngày {trade_date.isoformat()}."
                    ),
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
            executed_at=executed_at,
            trade_date=trade_date,
            settlement_date=settlement_date,
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
                "trade_date": trade_date.isoformat(),
                "settlement_date": settlement_date.isoformat(),
            },
        )

        self.session.commit()
        self.session.refresh(order)
        return self.build_order_response(order)

    def cancel_order(self, order_id: uuid.UUID, actor: str = "trader_user") -> OrderResponse:
        """
        Hủy lệnh Paper đang ở trạng thái `Submitted` hoặc `PartiallyFilled`.

        Khóa dòng Order (`FOR UPDATE`) TRƯỚC khi kiểm tra chuyển trạng thái để serialize với `execute_fill`: khóa Order là
        khóa đầu tiên của thứ tự Order -> Stock -> Account nên hủy không giữ khóa nào khác và không thể deadlock. Trạng
        thái được đọc lại sau khi giành khóa (`populate_existing`), nên lệnh vừa bị khớp xong (`Filled`) bị từ chối 409
        thay vì bị ghi đè `Cancelled`, và lần khớp tới sau lệnh đã hủy bị từ chối bởi state machine của `execute_fill`.
        """
        order = self.session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
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
