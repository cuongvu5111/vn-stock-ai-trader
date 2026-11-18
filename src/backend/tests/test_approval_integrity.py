# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử toàn vẹn phê duyệt — mỗi Order phải gắn đúng một Approval APPROVED của cùng Proposal, không tạo Order
#           khi Approval sai/thiếu/trùng, Daily Workflow không bao giờ tạo Approval/Order, duyệt lần hai bị 409,
#           Kill Switch bật giữa lúc tạo và duyệt chặn Order, và approver_user_id lấy từ phiên đăng nhập.

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core import clock
from app.portfolio.models import CashTransaction
from app.schemas.trading import RiskConfigPayload
from app.system.models import AuditLog
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.paper_broker import PaperBrokerAdapter
from test_risk_paper_trading import _seed_stock_and_buy_signal


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _proposal(session, signal, symbol: str = "FPT", side: str = "BUY") -> TradeProposal:
    proposal = TradeProposal(
        signal_id=signal.id,
        symbol=symbol,
        side=side,
        proposed_quantity=200,
        limit_price=Decimal("25000.0000"),
        stop_loss=Decimal("24000.0000"),
        status="Submitted",
        expires_at=clock.utc_now() + timedelta(hours=2),
    )
    session.add(proposal)
    session.flush()
    return proposal


def _approval(session, proposal: TradeProposal, decision: str = "APPROVED") -> Approval:
    approval = Approval(proposal_id=proposal.id, decision=decision, approved_by="tester")
    session.add(approval)
    session.flush()
    return approval


def _assert_forbidden_without_order(session, proposal: TradeProposal, approval: Approval) -> None:
    orders_before = _count(session, Order)
    with pytest.raises(HTTPException) as exc_info:
        PaperBrokerAdapter(session=session).create_paper_order_from_approved_proposal(
            proposal=proposal, approval=approval
        )
    assert exc_info.value.status_code == 403
    assert "Human Approval" in exc_info.value.detail
    assert _count(session, Order) == orders_before


def test_valid_approval_creates_order_linked_to_that_approval(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    approval = _approval(auth_session, proposal)

    order = PaperBrokerAdapter(session=auth_session).create_paper_order_from_approved_proposal(
        proposal=proposal, approval=approval
    )

    assert order.approval_id == approval.id
    assert order.proposal_id == proposal.id
    audit = auth_session.scalar(select(AuditLog).where(AuditLog.action == "PAPER_ORDER_SUBMITTED"))
    assert audit.after_state["approval_id"] == str(approval.id)


def test_no_order_when_approval_is_rejected(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    rejected = _approval(auth_session, proposal, decision="REJECTED")

    _assert_forbidden_without_order(auth_session, proposal, rejected)


def test_no_order_when_approval_belongs_to_another_proposal(auth_session) -> None:
    _, signal_a = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    _, signal_b = _seed_stock_and_buy_signal(auth_session, symbol="VCB")
    proposal_a = _proposal(auth_session, signal_a, "FPT")
    proposal_b = _proposal(auth_session, signal_b, "VCB")
    approval_a = _approval(auth_session, proposal_a)
    _approval(auth_session, proposal_b)

    _assert_forbidden_without_order(auth_session, proposal_b, approval_a)


def test_no_order_when_approval_is_not_persisted(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)

    transient = Approval(proposal_id=proposal.id, decision="APPROVED", approved_by="tester")
    _assert_forbidden_without_order(auth_session, proposal, transient)

    fabricated = Approval(
        id=uuid.uuid4(), proposal_id=proposal.id, decision="APPROVED", approved_by="tester"
    )
    _assert_forbidden_without_order(auth_session, proposal, fabricated)


def test_no_order_when_forged_approval_copy_contradicts_stored_rejection(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    approval = _approval(auth_session, proposal, decision="REJECTED")
    auth_session.commit()

    # Bản ghi trong DB vẫn là REJECTED; bản sao tự dựng mang decision APPROVED không được coi là phê duyệt
    forged = Approval(id=approval.id, proposal_id=proposal.id, decision="APPROVED", approved_by="tester")

    _assert_forbidden_without_order(auth_session, proposal, forged)


def test_no_order_when_persistent_rejection_is_flipped_in_memory_only(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    approval = _approval(auth_session, proposal, decision="REJECTED")
    auth_session.commit()

    approval.decision = "APPROVED"  # chưa flush: DB vẫn là REJECTED

    _assert_forbidden_without_order(auth_session, proposal, approval)


def test_same_approval_cannot_create_second_order(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    approval = _approval(auth_session, proposal)
    broker = PaperBrokerAdapter(session=auth_session)
    broker.create_paper_order_from_approved_proposal(proposal=proposal, approval=approval)

    with pytest.raises(HTTPException) as exc_info:
        broker.create_paper_order_from_approved_proposal(proposal=proposal, approval=approval)

    assert exc_info.value.status_code == 409
    assert _count(auth_session, Order) == 1


def test_database_rejects_duplicate_or_missing_approval_id(auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal = _proposal(auth_session, signal)
    approval = _approval(auth_session, proposal)

    def make_order(client_order_id: str, approval_id) -> Order:
        return Order(
            proposal_id=proposal.id,
            approval_id=approval_id,
            client_order_id=client_order_id,
            symbol="FPT",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            status="Submitted",
        )

    auth_session.add(make_order("ORD-1", approval.id))
    auth_session.flush()

    auth_session.add(make_order("ORD-2", approval.id))
    with pytest.raises(IntegrityError):
        auth_session.flush()
    auth_session.rollback()

    auth_session.add(make_order("ORD-3", None))
    with pytest.raises(IntegrityError):
        auth_session.flush()


def test_approve_api_links_order_to_approval_and_second_approve_is_409(auth_client, auth_session) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    created = auth_client.post("/api/v1/proposals", json={"signal_id": str(signal.id)})
    proposal_id = created.json()["id"]

    first = auth_client.post(f"/api/v1/proposals/{proposal_id}/approve", json={})
    assert first.status_code == 200 and first.json()["status"] == "Submitted"
    second = auth_client.post(f"/api/v1/proposals/{proposal_id}/approve", json={})

    assert second.status_code == 409
    approval = auth_session.scalar(select(Approval))
    order = auth_session.scalar(select(Order))
    assert _count(auth_session, Approval) == 1
    assert _count(auth_session, Order) == 1
    assert order.approval_id == approval.id
    assert str(order.id) == first.json()["order_id"]
    listed = auth_client.get("/api/v1/orders").json()["items"][0]
    assert listed["approval_id"] == str(approval.id)


@pytest.mark.parametrize("auto_fill", [False, True])
def test_kill_switch_enabled_between_create_and_approve_blocks_order(
    auth_client, auth_session, monkeypatch, auto_fill
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session)
    proposal_id = auth_client.post("/api/v1/proposals", json={"signal_id": str(signal.id)}).json()["id"]

    def _must_not_be_called(*_args, **_kwargs):
        raise AssertionError("PaperBroker không được gọi khi Kill Switch đang bật")

    monkeypatch.setattr(PaperBrokerAdapter, "create_paper_order_from_approved_proposal", _must_not_be_called)
    kill = auth_client.put(
        "/api/v1/risk",
        json={
            "reason": "Kill Switch giữa lúc tạo và duyệt",
            "configuration": RiskConfigPayload(trading_enabled=False).model_dump(mode="json"),
        },
    )
    assert kill.status_code == 200

    approved = auth_client.post(
        f"/api/v1/proposals/{proposal_id}/approve", json={"auto_submit_and_fill_in_paper": auto_fill}
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "Blocked"
    assert approved.json()["order_id"] is None
    assert _count(auth_session, Order) == 0
    assert _count(auth_session, Execution) == 0
    buy_ledger_entries = auth_session.scalar(
        select(func.count()).select_from(CashTransaction).where(CashTransaction.transaction_type == "BUY_EXECUTION")
    )
    assert buy_ledger_entries == 0
    blocked_audit = auth_session.scalar(
        select(AuditLog).where(AuditLog.action == "PROPOSAL_BLOCKED_ON_REVALIDATION")
    )
    assert "KILL_SWITCH_ACTIVE" in blocked_audit.after_state["reasons"][0]

    again = auth_client.post(f"/api/v1/proposals/{proposal_id}/approve", json={})
    assert again.status_code == 409


def test_daily_workflow_never_creates_approval_or_order(auth_client, auth_session) -> None:
    response = auth_client.post(
        "/api/v1/system/daily-workflow",
        json={"import_sample_csv_if_empty": True, "run_ai_analysis": False, "create_proposals": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["proposals_created"] >= 1
    assert _count(auth_session, Approval) == 0
    assert _count(auth_session, Order) == 0
    assert _count(auth_session, Execution) == 0
    statuses = set(auth_session.scalars(select(TradeProposal.status)).all())
    assert statuses == {"PendingApproval"}


@pytest.mark.real_auth
def test_approve_and_reject_store_authenticated_user_id_and_username_snapshot(
    auth_client, auth_session, create_user, login_headers
) -> None:
    alice = create_user("alice", "trader")
    headers = login_headers("alice")
    _, approve_signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    _, reject_signal = _seed_stock_and_buy_signal(auth_session, symbol="VCB")

    def new_proposal(signal) -> str:
        resp = auth_client.post("/api/v1/proposals", json={"signal_id": str(signal.id)}, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    approve = auth_client.post(
        f"/api/v1/proposals/{new_proposal(approve_signal)}/approve",
        json={"approved_by": "mallory"},
        headers=headers,
    )
    reject = auth_client.post(
        f"/api/v1/proposals/{new_proposal(reject_signal)}/reject",
        json={"rejected_by": "mallory"},
        headers=headers,
    )
    assert approve.status_code == 200 and reject.status_code == 200

    approvals = {a.decision: a for a in auth_session.scalars(select(Approval)).all()}
    assert set(approvals) == {"APPROVED", "REJECTED"}
    for approval in approvals.values():
        assert approval.approved_by == "alice"
        assert approval.approver_user_id == alice.id
    order = auth_session.scalar(select(Order))
    assert order.approval_id == approvals["APPROVED"].id
    assert _count(auth_session, Order) == 1
