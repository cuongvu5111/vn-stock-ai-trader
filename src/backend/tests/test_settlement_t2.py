# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử thanh toán T+2 end-to-end qua API/Service: số lượng khả dụng của BUY, chặn SELL khi chưa thanh toán,
#           khớp từng phần, đối soát dựng lại available_quantity và ngày chốt NAV theo múi giờ thị trường.
# Lý do: Cổ phiếu mua hôm nay (T) chưa được bán tới hết T+2 ngày làm việc; mọi ngày suy từ giờ thị trường (UTC+7).

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.config import get_settings
from app.indicators.models import StockSignal
from app.portfolio.models import Account, CashTransaction, Position
from app.system.models import AuditLog
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.paper_broker import PaperBrokerAdapter
from test_risk_paper_trading import _seed_stock_and_buy_signal

# Tuần làm việc dùng chung: 2026-11-16 là thứ 2
MON = (2026, 11, 16)
TUE = (2026, 11, 17)
WED = (2026, 11, 18)
THU = (2026, 11, 19)
FRI = (2026, 11, 20)
SAT = (2026, 11, 21)
SUN = (2026, 11, 22)
NEXT_MON = (2026, 11, 23)
NEXT_TUE = (2026, 11, 24)
PRICE = "25000.0000"


def _buy_order(client, signal) -> str:
    proposal = client.post("/api/v1/proposals", json={"signal_id": str(signal.id)})
    assert proposal.status_code == 200, proposal.text
    approved = client.post(f"/api/v1/proposals/{proposal.json()['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Submitted"
    return approved.json()["order_id"]


def _fill(client, order_id: str, quantity: int, price: str = PRICE):
    return client.post(
        f"/api/v1/orders/{order_id}/simulate-fill",
        json={"fill_quantity": quantity, "fill_price": price},
    )


def _position(client, symbol: str) -> Dict[str, Any] | None:
    body = client.get("/api/v1/portfolio").json()
    return next((p for p in body["positions"] if p["symbol"] == symbol), None)


def _open_sell_order(session, signal: StockSignal, symbol: str, quantity: int) -> str:
    """Tạo lệnh SELL hợp lệ (có Approval APPROVED) trực tiếp qua broker, bỏ qua cổng Risk của proposal."""
    proposal = TradeProposal(
        signal_id=signal.id,
        symbol=symbol,
        side="SELL",
        proposed_quantity=quantity,
        limit_price=Decimal(PRICE),
        status="Submitted",
        expires_at=clock.utc_now() + timedelta(hours=4),
    )
    session.add(proposal)
    session.flush()
    approval = Approval(proposal_id=proposal.id, decision="APPROVED", approved_by="tester")
    session.add(approval)
    session.flush()
    order = PaperBrokerAdapter(session=session).create_paper_order_from_approved_proposal(
        proposal=proposal, approval=approval
    )
    session.commit()
    return str(order.id)


def _ledger_state(session) -> Dict[str, Any]:
    return {
        "executions": session.scalar(select(func.count()).select_from(Execution)),
        "cash_transactions": session.scalar(select(func.count()).select_from(CashTransaction)),
        "cash_balance": session.scalar(select(Account.cash_balance)),
        "positions": sorted(session.execute(select(Position.quantity, Position.available_quantity)).all()),
        "orders": sorted(session.execute(select(Order.status, Order.filled_quantity)).all()),
        "audits": session.scalar(select(func.count()).select_from(AuditLog)),
    }


def _stored_positions(session) -> List[tuple]:
    return session.execute(select(Position.quantity, Position.available_quantity)).all()


def test_buy_is_unavailable_on_trade_day_and_t_plus_1_then_available_on_t_plus_2(
    auth_client, auth_session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    order_id = _buy_order(auth_client, signal)
    filled = _fill(auth_client, order_id, 200)
    assert filled.status_code == 200, filled.text

    execution = filled.json()["executions"][0]
    assert execution["trade_date"] == "2026-11-16"
    assert execution["settlement_date"] == "2026-11-18"

    expectations = [(MON, 0), (TUE, 0), (WED, 200), (THU, 200)]
    for day, expected_available in expectations:
        fake_clock.set_market(*day)
        body = auth_client.get("/api/v1/portfolio").json()
        position = body["positions"][0]
        assert body["as_of_date"] == date(*day).isoformat()
        assert position["quantity"] == 200
        assert position["available_quantity"] == expected_available, day
        assert position["pending_settlement_quantity"] == 200 - expected_available


def test_t_plus_2_skips_weekend_for_thursday_and_friday_buys(auth_client, auth_session, fake_clock) -> None:
    _, thu_signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    _, fri_signal = _seed_stock_and_buy_signal(auth_session, symbol="VCB")

    fake_clock.set_market(*THU)
    assert _fill(auth_client, _buy_order(auth_client, thu_signal), 200).status_code == 200
    fake_clock.set_market(*FRI)
    assert _fill(auth_client, _buy_order(auth_client, fri_signal), 200).status_code == 200

    expectations = [
        (FRI, 0, 0),
        (SAT, 0, 0),
        (SUN, 0, 0),
        (NEXT_MON, 200, 0),
        (NEXT_TUE, 200, 200),
    ]
    for day, fpt_available, vcb_available in expectations:
        fake_clock.set_market(*day)
        assert _position(auth_client, "FPT")["available_quantity"] == fpt_available, day
        assert _position(auth_client, "VCB")["available_quantity"] == vcb_available, day

    executions = {e.settlement_date for e in auth_session.scalars(select(Execution)).all()}
    assert executions == {date(*NEXT_MON), date(*NEXT_TUE)}


def test_partial_fills_on_different_days_settle_independently(auth_client, auth_session, fake_clock) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    order_id = _buy_order(auth_client, signal)
    assert _fill(auth_client, order_id, 100).status_code == 200
    fake_clock.set_market(*TUE)
    assert _fill(auth_client, order_id, 100).status_code == 200

    for day, expected_available in [(TUE, 0), (WED, 100), (THU, 200)]:
        fake_clock.set_market(*day)
        position = _position(auth_client, "FPT")
        assert position["quantity"] == 200
        assert position["available_quantity"] == expected_available, day


def test_sell_before_settlement_is_rejected_without_any_mutation(auth_client, auth_session, fake_clock) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    assert _fill(auth_client, _buy_order(auth_client, signal), 200).status_code == 200

    fake_clock.set_market(*TUE)
    sell_order_id = _open_sell_order(auth_session, signal, "FPT", 100)
    before = _ledger_state(auth_session)

    rejected = _fill(auth_client, sell_order_id, 100)

    assert rejected.status_code == 400
    assert "T+2" in rejected.json()["error"]["message"]
    assert _ledger_state(auth_session) == before
    sell_order = auth_session.get(Order, uuid.UUID(sell_order_id))
    assert sell_order.status == "Submitted" and sell_order.filled_quantity == 0


def test_sell_after_settlement_is_allowed_but_cannot_exceed_settled_quantity(
    auth_client, auth_session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    order_id = _buy_order(auth_client, signal)
    assert _fill(auth_client, order_id, 100).status_code == 200
    fake_clock.set_market(*TUE)
    assert _fill(auth_client, order_id, 100).status_code == 200

    # Thứ 4: chỉ lô mua thứ 2 vừa tới T+2 -> 100 khả dụng, lô mua thứ 3 chưa về
    fake_clock.set_market(*WED)
    sell_order_id = _open_sell_order(auth_session, signal, "FPT", 150)
    state_before = _ledger_state(auth_session)
    too_much = _fill(auth_client, sell_order_id, 150)
    assert too_much.status_code == 400
    assert _ledger_state(auth_session) == state_before

    allowed = _fill(auth_client, sell_order_id, 100)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "PartiallyFilled"
    position = _position(auth_client, "FPT")
    assert position["quantity"] == 100
    assert position["available_quantity"] == 0

    # Thứ 5: 50 còn lại của lệnh bán đã được thanh toán nốt
    fake_clock.set_market(*THU)
    assert _position(auth_client, "FPT")["available_quantity"] == 100
    final = _fill(auth_client, sell_order_id, 50)
    assert final.status_code == 200
    assert final.json()["status"] == "Filled"
    position = _position(auth_client, "FPT")
    assert position["quantity"] == 50 and position["available_quantity"] == 50


def test_risk_engine_blocks_sell_proposal_until_position_is_settled(
    auth_client, auth_session, fake_clock
) -> None:
    stock, buy_signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    sell_signal = StockSignal(
        stock_id=stock.id,
        trading_date=date(2026, 5, 29),
        action="SELL",
        score=Decimal("70.00"),
        reference_price=Decimal(PRICE),
        stop_loss=None,
        reason={"strategy_name": "TrendFollowingStrategy", "reasons": ["Thủng EMA50"]},
        status="GENERATED",
    )
    auth_session.add(sell_signal)
    auth_session.commit()

    fake_clock.set_market(*MON)
    assert _fill(auth_client, _buy_order(auth_client, buy_signal), 200).status_code == 200

    blocked = auth_client.post("/api/v1/proposals", json={"signal_id": str(sell_signal.id)})
    assert blocked.status_code == 400
    assert "INSUFFICIENT_POSITION_FOR_SELL" in blocked.json()["error"]["message"]

    fake_clock.set_market(*WED)
    proposal = auth_client.post("/api/v1/proposals", json={"signal_id": str(sell_signal.id)})
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["proposed_quantity"] == 200
    approved = auth_client.post(f"/api/v1/proposals/{proposal.json()['id']}/approve", json={})
    assert approved.status_code == 200 and approved.json()["status"] == "Submitted"
    filled = _fill(auth_client, approved.json()["order_id"], 200)
    assert filled.status_code == 200 and filled.json()["status"] == "Filled"
    assert auth_client.get("/api/v1/portfolio").json()["open_positions_count"] == 0


def test_approve_revalidation_blocks_sell_when_quantity_is_not_settled(
    auth_client, auth_session, fake_clock
) -> None:
    stock, buy_signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    sell_signal = StockSignal(
        stock_id=stock.id,
        trading_date=date(2026, 5, 29),
        action="SELL",
        score=Decimal("70.00"),
        reference_price=Decimal(PRICE),
        reason={"reasons": ["Thủng EMA50"]},
        status="GENERATED",
    )
    auth_session.add(sell_signal)
    auth_session.commit()

    # Thứ 4: 100 đã thanh toán (mua thứ 2) và 100 chưa (mua thứ 4) -> đề xuất bán 100 hợp lệ
    fake_clock.set_market(*MON)
    order_id = _buy_order(auth_client, buy_signal)
    assert _fill(auth_client, order_id, 100).status_code == 200
    fake_clock.set_market(*WED)
    assert _fill(auth_client, order_id, 100).status_code == 200
    proposal = auth_client.post("/api/v1/proposals", json={"signal_id": str(sell_signal.id)})
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["proposed_quantity"] == 100

    # Dữ liệu sổ khớp thay đổi trước khi duyệt: lô đã thanh toán bị bán bớt -> Re-validation phải chặn
    sell_order_id = _open_sell_order(auth_session, sell_signal, "FPT", 100)
    assert _fill(auth_client, sell_order_id, 100).status_code == 200
    orders_before = auth_session.scalar(select(func.count()).select_from(Order))

    approved = auth_client.post(f"/api/v1/proposals/{proposal.json()['id']}/approve", json={})

    assert approved.status_code == 200
    assert approved.json()["status"] == "Blocked"
    assert approved.json()["order_id"] is None
    assert auth_session.scalar(select(func.count()).select_from(Order)) == orders_before


def test_reconcile_rebuilds_available_quantity_from_ledger_by_settlement_date(
    auth_client, auth_session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    order_id = _buy_order(auth_client, signal)
    assert _fill(auth_client, order_id, 100).status_code == 200
    fake_clock.set_market(*TUE)
    assert _fill(auth_client, order_id, 100).status_code == 200

    # Dữ liệu tổng hợp bị sửa sai: coi như toàn bộ 200 đã khả dụng
    auth_session.query(Position).update({Position.available_quantity: 200})
    auth_session.commit()

    for day, expected_available in [(TUE, 0), (WED, 100), (THU, 200)]:
        fake_clock.set_market(*day)
        report = auth_client.post("/api/v1/portfolio/reconcile")
        assert report.status_code == 200
        assert report.json()["as_of_date"] == date(*day).isoformat()
        assert report.json()["positions_rebuilt_count"] == 1
        assert _stored_positions(auth_session) == [(200, expected_available)], day


def test_reconcile_preserves_total_and_available_after_partial_sell(
    auth_client, auth_session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    assert _fill(auth_client, _buy_order(auth_client, signal), 200).status_code == 200

    fake_clock.set_market(*WED)
    sell_order_id = _open_sell_order(auth_session, signal, "FPT", 100)
    assert _fill(auth_client, sell_order_id, 100).status_code == 200
    assert _stored_positions(auth_session) == [(100, 100)]

    report = auth_client.post("/api/v1/portfolio/reconcile")

    assert report.status_code == 200
    assert report.json()["is_consistent_before_rebuild"] is True
    assert _stored_positions(auth_session) == [(100, 100)]
    position = _position(auth_client, "FPT")
    assert position["quantity"] == 100 and position["available_quantity"] == 100


def test_overview_refresh_never_mutates_execution_history(auth_client, auth_session, fake_clock) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    assert _fill(auth_client, _buy_order(auth_client, signal), 200).status_code == 200

    def history() -> List[tuple]:
        return auth_session.execute(
            select(
                Execution.id,
                Execution.quantity,
                Execution.price,
                Execution.trade_date,
                Execution.settlement_date,
            )
        ).all()

    before = history()
    cash_before = _ledger_state(auth_session)["cash_transactions"]
    for day in (TUE, WED, THU, NEXT_MON):
        fake_clock.set_market(*day)
        auth_client.get("/api/v1/portfolio")
        auth_client.post("/api/v1/portfolio/reconcile")

    assert history() == before
    assert _ledger_state(auth_session)["cash_transactions"] == cash_before


def test_execution_dates_follow_market_calendar_across_utc_midnight(
    auth_client, auth_session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*TUE)
    order_id = _buy_order(auth_client, signal)

    # 20:00 UTC ngày 17/11 đã là 03:00 ngày 18/11 giờ Việt Nam
    fake_clock.set_utc(2026, 11, 17, 20, 0)
    assert _fill(auth_client, order_id, 100).status_code == 200
    # 17:30 UTC thứ 6 là 00:30 thứ 7 giờ Việt Nam -> thanh toán vào thứ 3 tuần sau
    fake_clock.set_utc(2026, 11, 20, 17, 30)
    assert _fill(auth_client, order_id, 100).status_code == 200

    first, second = auth_session.scalars(select(Execution).order_by(Execution.executed_at)).all()
    assert (first.trade_date, first.settlement_date) == (date(2026, 11, 18), date(2026, 11, 20))
    assert (second.trade_date, second.settlement_date) == (date(2026, 11, 21), date(2026, 11, 24))
    assert first.executed_at.replace(tzinfo=None) == datetime(2026, 11, 17, 20, 0)


@pytest.mark.parametrize(
    ("lag", "available_by_day"),
    [(0, {MON: 200}), (1, {MON: 0, TUE: 200}), (3, {WED: 0, THU: 200})],
)
def test_settlement_lag_is_configurable(
    auth_client, auth_session, fake_clock, monkeypatch, lag, available_by_day
) -> None:
    monkeypatch.setattr(get_settings(), "SETTLEMENT_LAG_TRADING_DAYS", lag)
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    fake_clock.set_market(*MON)
    assert _fill(auth_client, _buy_order(auth_client, signal), 200).status_code == 200

    for day, expected in available_by_day.items():
        fake_clock.set_market(*day)
        assert _position(auth_client, "FPT")["available_quantity"] == expected, (lag, day)


def test_default_snapshot_date_uses_market_today_not_utc_date(auth_client, fake_clock) -> None:
    fake_clock.set_utc(2026, 11, 17, 23, 30)
    first = auth_client.post("/api/v1/portfolio/snapshots")
    assert first.status_code == 200
    assert first.json()["snapshot_date"] == "2026-11-18"

    fake_clock.set_utc(2026, 11, 18, 16, 59)
    same_day = auth_client.post("/api/v1/portfolio/snapshots")
    assert same_day.json()["snapshot_date"] == "2026-11-18"
    assert same_day.json()["id"] == first.json()["id"]

    fake_clock.set_utc(2026, 11, 18, 17, 0)
    assert auth_client.post("/api/v1/portfolio/snapshots").json()["snapshot_date"] == "2026-11-19"

    explicit = auth_client.post("/api/v1/portfolio/snapshots?snapshot_date=2026-11-10")
    assert explicit.json()["snapshot_date"] == "2026-11-10"


def test_service_snapshot_default_date_at_23_30_utc(auth_session, fake_clock) -> None:
    from app.portfolio.service import PortfolioService

    fake_clock.set_utc(2026, 11, 17, 23, 30)

    snapshot = PortfolioService(session=auth_session).create_or_update_daily_snapshot()

    assert snapshot.snapshot_date == date(2026, 11, 18)

