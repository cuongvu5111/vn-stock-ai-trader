# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử hành vi khóa của PaperBrokerAdapter ngay cả khi không có PostgreSQL (SQLite bỏ qua FOR UPDATE nên test
#   ghi lại các câu SELECT ... FOR UPDATE được biên dịch sang dialect PostgreSQL và kiểm tra đọc lại sau khóa):
#   - `cancel_order` phải khóa dòng Order TRƯỚC mọi kiểm tra/ghi trạng thái và đọc lại trạng thái mới nhất;
#   - `execute_fill` luôn khóa theo thứ tự Order -> Stock -> Account (không bao giờ ngược lại) cho cả BUY và SELL;
#   - sức mua BUY được kiểm tra trên số dư đọc lại SAU khi khóa Account, không dùng bản sao cũ trong identity map.
# Lý do: Đây là các bất biến chống race cancel-vs-fill và lost-update tiền mặt; bản chạy thật nhiều thread trên PostgreSQL
#   nằm ở test_paper_broker_concurrency.py (cần MIGRATION_TEST_POSTGRES_URL).

import re
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.portfolio.models import Account, CashTransaction
from app.portfolio.service import PortfolioService
from app.schemas.trading import SimulateFillRequest
from app.trading.models import Execution, Order
from app.trading.paper_broker import PaperBrokerAdapter
from test_paper_broker_concurrency import BUY_DAY, PRICE, SELL_DAY, SYMBOL, _open_order
from test_risk_paper_trading import _seed_stock_and_buy_signal

LOCK_RANK = {"trading.orders": 0, "market.stocks": 1, "portfolio.accounts": 2}


def _trace_locks_and_flushes(session: Session) -> list[str]:
    """Ghi lại theo thứ tự: mỗi SELL ... FOR UPDATE (theo bảng) và mỗi lần flush ghi dữ liệu."""
    trace: list[str] = []

    @event.listens_for(session, "do_orm_execute")
    def _on_execute(state) -> None:
        if not state.is_select:
            return
        compiled = str(state.statement.compile(dialect=postgresql.dialect()))
        if "FOR UPDATE" not in compiled:
            return
        table = re.search(r"FROM (\w+\.\w+)", compiled).group(1)
        trace.append(f"LOCK:{table}:populate_existing={bool(state.execution_options.get('populate_existing'))}")

    @event.listens_for(session, "before_flush")
    def _on_flush(sess, _ctx, _instances) -> None:
        if sess.new or sess.dirty:
            trace.append("FLUSH")

    return trace


def _lock_tables(trace: list[str]) -> list[str]:
    return [entry.split(":")[1] for entry in trace if entry.startswith("LOCK:")]


def _fill(session: Session, order_id, quantity: int, tag: str = "A") -> None:
    PaperBrokerAdapter(session=session).execute_fill(
        order_id=order_id,
        payload=SimulateFillRequest(fill_quantity=quantity, fill_price=PRICE, execution_id=f"EXEC-LOCK-{tag}-{quantity}"),
        actor="locking_test",
    )


def test_cancel_order_locks_order_row_before_any_check_or_write(auth_session: Session, fake_clock) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol=SYMBOL)
    order_id = _open_order(auth_session, signal, "BUY", quantity=100)
    trace = _trace_locks_and_flushes(auth_session)

    PaperBrokerAdapter(session=auth_session).cancel_order(order_id=order_id, actor="locking_test")

    assert trace[0] == "LOCK:trading.orders:populate_existing=True"
    assert trace.index("LOCK:trading.orders:populate_existing=True") < trace.index("FLUSH")
    assert _lock_tables(trace) == ["trading.orders"]  # hủy lệnh không giữ khóa nào khác nên không thể deadlock


def test_cancel_order_rereads_status_after_lock_instead_of_stale_identity_map(
    auth_session: Session, fake_clock
) -> None:
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol=SYMBOL)
    order_id = _open_order(auth_session, signal, "BUY", quantity=100)
    stale = auth_session.get(Order, order_id)
    assert stale.status == "Submitted"
    # Worker khác vừa khớp xong và commit; bản sao trong identity map của session này vẫn là "Submitted"
    auth_session.connection().execute(
        text("UPDATE orders SET status = 'Filled', filled_quantity = quantity WHERE id = :id"),
        {"id": order_id.hex},
    )

    with pytest.raises(HTTPException) as exc_info:
        PaperBrokerAdapter(session=auth_session).cancel_order(order_id=order_id, actor="locking_test")

    assert exc_info.value.status_code == 409
    auth_session.commit()  # cancel_order không được ghi đè trạng thái Filled bằng Cancelled
    assert auth_session.scalar(select(Order.status)) == "Filled"


def test_cancel_order_unknown_id_is_404(auth_session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        PaperBrokerAdapter(session=auth_session).cancel_order(order_id=uuid.uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_execute_fill_locks_order_then_stock_then_account(auth_session: Session, fake_clock, side: str) -> None:
    fake_clock.set_market(*BUY_DAY)
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol=SYMBOL)
    if side == "SELL":
        buy_id = _open_order(auth_session, signal, "BUY", quantity=100)
        _fill(auth_session, buy_id, 100, tag="BUY")
        fake_clock.set_market(*SELL_DAY)
    order_id = _open_order(auth_session, signal, side, quantity=100)
    trace = _trace_locks_and_flushes(auth_session)

    _fill(auth_session, order_id, 100, tag=side)

    locks = _lock_tables(trace)
    assert locks[:3] == ["trading.orders", "market.stocks", "portfolio.accounts"]
    ranks = [LOCK_RANK[table] for table in locks]
    assert ranks == sorted(ranks), f"vi phạm thứ tự khóa Order -> Stock -> Account: {locks}"
    # Account bị khóa trước khi có bất kỳ thay đổi nào được flush (kiểm tra sức mua và ghi sổ cái nằm sau khóa)
    assert trace.index("LOCK:portfolio.accounts:populate_existing=True") < trace.index("FLUSH")


def test_buy_fill_checks_cash_on_balance_reread_after_account_lock(auth_session: Session, fake_clock) -> None:
    fake_clock.set_market(*BUY_DAY)
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol=SYMBOL)
    order_id = _open_order(auth_session, signal, "BUY", quantity=100)
    stale_account = PortfolioService(auth_session).get_or_create_default_paper_account()
    auth_session.commit()
    initial_cash = stale_account.cash_balance
    # Worker khác đã tiêu gần hết tiền và commit; bản sao trong identity map vẫn còn đủ tiền
    auth_session.connection().execute(text("UPDATE accounts SET cash_balance = 1.00"))

    with pytest.raises(HTTPException) as exc_info:
        _fill(auth_session, order_id, 100)

    assert exc_info.value.status_code == 400
    assert "Không đủ tiền mặt" in exc_info.value.detail
    auth_session.commit()  # giữ nguyên số dư đã bị worker khác tiêu để kiểm tra không có gì bị ghi đè
    assert auth_session.scalar(select(func.count()).select_from(Execution)) == 0
    assert auth_session.scalar(select(Account.cash_balance)) == Decimal("1.00")
    assert initial_cash > Decimal("1.00")
    assert auth_session.scalar(select(func.count()).select_from(CashTransaction)) == 1  # chỉ còn bút toán vốn ban đầu


def test_default_account_creation_is_idempotent_and_locked_read_returns_same_row(auth_session: Session) -> None:
    service = PortfolioService(auth_session)

    first = service.get_or_create_default_paper_account(for_update=True)
    second = service.get_or_create_default_paper_account(for_update=True)
    plain = service.get_or_create_default_paper_account()

    assert first.id == second.id == plain.id
    assert auth_session.scalar(select(func.count()).select_from(Account)) == 1
    assert (
        auth_session.scalar(
            select(func.count()).select_from(CashTransaction).where(CashTransaction.transaction_type == "INITIAL_DEPOSIT")
        )
        == 1
    )
