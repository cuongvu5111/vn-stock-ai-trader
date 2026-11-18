# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử đồng thời (nhiều session/thread, PostgreSQL thật) cho PaperBrokerAdapter:
#   - cùng một Order bị khớp song song không được vượt `quantity` (overfill);
#   - hai lệnh SELL cùng mã khớp song song không được bán vượt số cổ phiếu đã thanh toán T+N (oversell);
#   - hai lệnh BUY khác mã khớp song song không được mất cập nhật `Account.cash_balance` hay cùng vượt sức mua;
#   - hủy lệnh và khớp lệnh song song (cancel-vs-fill) không được ghi đè trạng thái cuối trái state machine
#     (Filled bị ghi đè Cancelled hoặc ngược lại) và sổ khớp lệnh/sổ cái tiền phải luôn khớp nhau;
#   - hai worker cùng tạo tài khoản mặc định lần đầu chỉ sinh đúng một Account (UNIQUE account_name, migration 0005).
# Lý do: SQLite bỏ qua `SELECT ... FOR UPDATE` nên chỉ PostgreSQL mới chứng minh được thứ tự khóa Order -> Stock -> Account.
#   Test tự chạy khi đặt MIGRATION_TEST_POSTGRES_URL (ví dụ postgresql+psycopg://postgres:<mật khẩu>@127.0.0.1:55432/postgres),
#   mỗi test dùng một database tạm riêng (alembic upgrade head) rồi xóa; không đặt biến này thì bị skip.
#   Để chắc chắn tái hiện được race khi thiếu khóa, mọi session dừng tại điểm ngay trước `INSERT INTO trading.executions`
#   (sau khi đã tính xong remaining/khả dụng/sức mua) cho tới khi cả hai cùng tới nơi. Có khóa thì session thứ hai bị chặn ở
#   lệnh khóa nên rào chắn hết hạn (BrokenBarrierError) và session thứ nhất chạy tiếp, session thứ hai tính lại sau commit.
#   Các test cancel-vs-fill dàn dựng thứ tự xen kẽ tất định: một thread dừng giữa chừng khi đang giữ khóa, thread kia được
#   khởi động và phải bị PostgreSQL chặn (pg_stat_activity.wait_event_type = 'Lock') rồi mới thả thread đầu.

import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.indicators.models import StockSignal
from app.market_data.models import Stock
from app.portfolio.models import Account, CashTransaction, Position
from app.portfolio.service import PortfolioService
from app.risk.service import RiskService
from app.schemas.trading import SimulateFillRequest
from app.system.models import AuditLog
from app.trading.models import Approval, Execution, Order, TradeProposal
from app.trading.paper_broker import PaperBrokerAdapter
from test_migration_0003_0004 import _cfg, make_url_with_database, PG_URL, requires_pg
from test_risk_paper_trading import _seed_stock_and_buy_signal

PRICE = Decimal("25000.0000")
SYMBOL = "FPT"
BUY_DAY = (2026, 11, 9)  # thứ 2: cổ phiếu mua về tài khoản (T+2) từ 2026-11-11
SELL_DAY = (2026, 11, 16)  # thứ 2 tuần sau: toàn bộ lô mua đã thanh toán
BARRIER_TIMEOUT_SECONDS = 3.0
CAPITAL = Decimal("30000000.00")
FEE_RATE = Decimal("0.0015")  # mặc định của RiskConfigPayload
TAX_RATE = Decimal("0.0010")
EXECUTIONS_INSERT = "INSERT INTO TRADING.EXECUTIONS"
AUDIT_INSERT = "INSERT INTO SYSTEM.AUDIT_LOGS"
ACCOUNT_INSERT = "INSERT INTO PORTFOLIO.ACCOUNTS"

pytestmark = requires_pg


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch):
    """Database PostgreSQL tạm đã `alembic upgrade head` (đúng schema/ràng buộc thật), xóa sau test."""
    admin = create_engine(make_url_with_database(PG_URL, None), isolation_level="AUTOCOMMIT")
    name = f"conc_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url_with_database(PG_URL, name)
    monkeypatch.setattr(get_settings(), "DATABASE_URL_OVERRIDE", url)
    # Cố định vốn ban đầu để số tiền kỳ vọng trong test không phụ thuộc .env của máy dev
    monkeypatch.setattr(get_settings(), "INITIAL_PAPER_CAPITAL", CAPITAL)
    command.upgrade(_cfg(), "head")
    engine = create_engine(url, pool_size=5)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _new_session(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def _open_order(
    session: Session, signal: StockSignal, side: str, quantity: int, symbol: str = SYMBOL
) -> uuid.UUID:
    """Tạo Order hợp lệ (có Approval APPROVED) trực tiếp qua broker, bỏ qua cổng Risk của proposal."""
    proposal = TradeProposal(
        signal_id=signal.id,
        symbol=symbol,
        side=side,
        proposed_quantity=quantity,
        limit_price=PRICE,
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
    return order.id


def _fill(session: Session, order_id: uuid.UUID, quantity: int, tag: str) -> Any:
    return PaperBrokerAdapter(session=session).execute_fill(
        order_id=order_id,
        payload=SimulateFillRequest(
            fill_quantity=quantity, fill_price=PRICE, execution_id=f"EXEC-CONC-{tag}-{uuid.uuid4().hex[:8]}"
        ),
        actor="concurrency_test",
    )


def _seed_symbols(engine: Engine, symbols: tuple[str, ...]) -> dict[str, StockSignal]:
    """Stock, tín hiệu, tài khoản Paper và cấu hình rủi ro mặc định tạo sẵn để các worker không tranh nhau tạo."""
    with _new_session(engine) as session:
        signals = {
            symbol: _seed_stock_and_buy_signal(session, symbol=symbol)[1] for symbol in symbols
        }
        PortfolioService(session).get_or_create_default_paper_account()
        RiskService(session).get_active_payload()
        session.commit()
        for signal in signals.values():
            session.refresh(signal)
        return signals


def _seed_common(engine: Engine) -> StockSignal:
    return _seed_symbols(engine, (SYMBOL,))[SYMBOL]


def _install_rendezvous(engine: Engine, parties: int, statement_prefix: str) -> None:
    """Giữ mọi session ngay trước câu SQL `statement_prefix` cho tới khi đủ `parties` session cùng tới nơi."""
    barrier = threading.Barrier(parties, timeout=BARRIER_TIMEOUT_SECONDS)

    @event.listens_for(engine, "before_cursor_execute")
    def _rendezvous(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith(statement_prefix):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass


def _install_insert_rendezvous(engine: Engine, parties: int) -> None:
    """Giữ mọi session ngay trước khi chèn Execution để buộc các kiểm tra remaining/khả dụng diễn ra chồng lấn."""
    _install_rendezvous(engine, parties, EXECUTIONS_INSERT)


class _PausePoints:
    """Dừng thread có tên cho trước ngay TRƯỚC một câu SQL (một lần) để dàn dựng thứ tự xen kẽ tất định."""

    def __init__(self, engine: Engine) -> None:
        self._points: list[tuple[str, str, threading.Event, threading.Event]] = []
        self._mutex = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._on_execute)

    def add(self, thread_name: str, statement_prefix: str) -> tuple[threading.Event, threading.Event]:
        """Trả về (reached, release): `reached` bật khi thread tới điểm dừng, thread chạy tiếp khi `release` được bật."""
        reached, release = threading.Event(), threading.Event()
        self._points.append((thread_name, statement_prefix, reached, release))
        return reached, release

    def _on_execute(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        name = threading.current_thread().name
        with self._mutex:
            point = next(
                (
                    p
                    for p in self._points
                    if p[0] == name and statement.lstrip().upper().startswith(p[1])
                ),
                None,
            )
            if point is not None:
                self._points.remove(point)
        if point is not None:
            point[2].set()
            assert point[3].wait(timeout=30), f"điểm dừng của thread {name} không được thả"


def _wait_until_lock_waiters(engine: Engine, expected: int = 1, timeout: float = 15.0) -> None:
    """Chờ tới khi PostgreSQL báo ít nhất `expected` backend đang bị chặn chờ khóa (wait_event_type = 'Lock')."""
    deadline = time.monotonic() + timeout
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
            if waiting >= expected:
                return
            time.sleep(0.05)
    pytest.fail(f"không có {expected} backend nào bị chặn chờ khóa sau {timeout}s")


class _Job:
    """Một thao tác chạy trong thread + session riêng; kết quả là ('ok'|'rejected'|'error', chi tiết)."""

    def __init__(
        self,
        engine: Engine,
        name: str,
        action: Callable[[Session], Any],
        start_line: threading.Barrier | None = None,
    ) -> None:
        self.name = name
        self.result: tuple[str, Any] = ("error", "chưa chạy")
        self._engine = engine
        self._action = action
        self._start_line = start_line
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        with _new_session(self._engine) as session:
            try:
                if self._start_line is not None:
                    self._start_line.wait()
                self.result = ("ok", self._action(session))
            except HTTPException as exc:
                session.rollback()
                self.result = ("rejected", exc.status_code)
            except Exception as exc:  # mọi lỗi khác (IntegrityError, deadlock...) phải làm test fail
                session.rollback()
                self.result = ("error", repr(exc))


def _join_jobs(jobs: list[_Job]) -> None:
    for job in jobs:
        job.thread.join(timeout=60)
    assert not any(job.thread.is_alive() for job in jobs), "thread bị treo (nghi deadlock)"


def _run_jobs(
    engine: Engine, actions: dict[str, Callable[[Session], Any]]
) -> dict[str, tuple[str, Any]]:
    """Chạy mọi thao tác song song, cùng xuất phát một lúc; trả về kết quả theo tên thao tác."""
    start_line = threading.Barrier(len(actions), timeout=10)
    jobs = [_Job(engine, name, action, start_line) for name, action in actions.items()]
    for job in jobs:
        job.thread.start()
    _join_jobs(jobs)
    return {job.name: job.result for job in jobs}


def _run_concurrent_fills(engine: Engine, fills: list[tuple[uuid.UUID, int]]) -> list[tuple[str, Any]]:
    """Mỗi lần khớp chạy trong thread + session riêng, cùng xuất phát một lúc; trả về ('ok'|'rejected'|'error', chi tiết)."""
    results = _run_jobs(
        engine,
        {
            str(index): (
                lambda session, order_id=order_id, quantity=quantity, index=index: _fill(
                    session, order_id, quantity, tag=str(index)
                ).filled_quantity
            )
            for index, (order_id, quantity) in enumerate(fills)
        },
    )
    return [results[str(index)] for index in range(len(fills))]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _buy_cost(quantity: int) -> Decimal:
    """Tiền mặt một lệnh BUY tiêu: giá trị khớp + phí, làm tròn đúng như PaperBrokerAdapter."""
    gross = _money(Decimal(quantity) * PRICE)
    return gross + _money(gross * FEE_RATE)


def _sell_proceeds(quantity: int) -> Decimal:
    """Tiền mặt một lệnh SELL thu về: giá trị khớp - phí - thuế bán."""
    gross = _money(Decimal(quantity) * PRICE)
    return gross - _money(gross * FEE_RATE) - _money(gross * TAX_RATE)


def _account_cash(engine: Engine) -> Decimal:
    with _new_session(engine) as session:
        return session.scalar(select(Account.cash_balance))


def _positions(engine: Engine) -> dict[str, int]:
    with _new_session(engine) as session:
        return dict(
            session.execute(
                select(Stock.symbol, Position.quantity).join(Stock, Position.stock_id == Stock.id)
            ).all()
        )


def _order_snapshot(engine: Engine, order_id: uuid.UUID) -> dict[str, Any]:
    """Trạng thái cuối của Order đọc thẳng từ DB, kèm tổng execution và số lần mỗi hành động audit được ghi."""
    with _new_session(engine) as session:
        order = session.get(Order, order_id)
        return {
            "status": order.status,
            "filled_quantity": order.filled_quantity,
            "executed": session.scalar(
                select(func.coalesce(func.sum(Execution.quantity), 0)).where(Execution.order_id == order_id)
            ),
            "audits": dict(
                Counter(
                    session.scalars(
                        select(AuditLog.action).where(
                            AuditLog.entity_type == "Order", AuditLog.entity_id == str(order_id)
                        )
                    )
                )
            ),
        }


def _assert_ledger_consistent(engine: Engine) -> None:
    """
    Sổ cái sau đồng thời vẫn khớp: vị thế từng mã = Σ BUY - Σ SELL không âm, mỗi execution có đúng một bút toán tiền,
    cash_balance = Σ sổ cái, và mọi Order có trạng thái đúng state machine so với tổng khớp (không Filled+Cancelled lẫn lộn).
    """
    with _new_session(engine) as session:
        net_by_symbol: dict[str, int] = defaultdict(int)
        for symbol, side, quantity in session.execute(
            select(Order.symbol, Order.side, func.sum(Execution.quantity))
            .join(Execution, Execution.order_id == Order.id)
            .group_by(Order.symbol, Order.side)
        ).all():
            net_by_symbol[symbol] += quantity if side == "BUY" else -quantity
        positions = {
            symbol: (quantity, available)
            for symbol, quantity, available in session.execute(
                select(Stock.symbol, Position.quantity, Position.available_quantity).join(
                    Stock, Position.stock_id == Stock.id
                )
            ).all()
        }
        for symbol in set(net_by_symbol) | set(positions):
            net = net_by_symbol.get(symbol, 0)
            quantity, available = positions.get(symbol, (0, 0))
            assert net >= 0, symbol
            assert quantity == net, symbol
            assert available <= quantity, symbol

        executions = set(session.scalars(select(Execution.id)))
        trade_cash = list(
            session.scalars(
                select(CashTransaction.reference_id).where(CashTransaction.reference_type == "EXECUTION")
            )
        )
        assert len(trade_cash) == len(set(trade_cash)) == len(executions)
        assert set(trade_cash) == executions
        assert session.scalar(select(func.count()).select_from(Account)) == 1
        assert session.scalar(select(Account.cash_balance)) == session.scalar(
            select(func.coalesce(func.sum(CashTransaction.amount), 0))
        )

        for order in session.scalars(select(Order)):
            executed = session.scalar(
                select(func.coalesce(func.sum(Execution.quantity), 0)).where(Execution.order_id == order.id)
            )
            assert order.filled_quantity == executed <= order.quantity, order.id
            if order.status == "Filled":
                assert executed == order.quantity, order.id
            elif order.status == "PartiallyFilled":
                assert 0 < executed < order.quantity, order.id
            elif order.status == "Submitted":
                assert executed == 0, order.id
            else:
                assert order.status == "Cancelled" and executed < order.quantity, order.id


@pytest.mark.parametrize(
    ("fill_a", "fill_b", "expected_ok", "expected_filled"),
    [(60, 60, 1, 60), (100, 100, 1, 100), (40, 40, 2, 80)],
    ids=["60+60-exceeds-100", "100+100-exceeds-100", "40+40-fits-no-false-block"],
)
def test_pg_concurrent_fills_of_same_order_never_exceed_quantity(
    pg_engine: Engine, fake_clock, fill_a: int, fill_b: int, expected_ok: int, expected_filled: int
) -> None:
    fake_clock.set_market(*SELL_DAY)
    signal = _seed_common(pg_engine)
    with _new_session(pg_engine) as session:
        order_id = _open_order(session, signal, "BUY", quantity=100)
    _install_insert_rendezvous(pg_engine, parties=2)

    results = _run_concurrent_fills(pg_engine, [(order_id, fill_a), (order_id, fill_b)])

    assert [r for r in results if r[0] == "error"] == []
    assert sum(1 for kind, _ in results if kind == "ok") == expected_ok, results
    assert all(detail == 400 for kind, detail in results if kind == "rejected"), results
    with _new_session(pg_engine) as session:
        order = session.get(Order, order_id)
        total_executed = session.scalar(
            select(func.coalesce(func.sum(Execution.quantity), 0)).where(Execution.order_id == order_id)
        )
        assert total_executed == expected_filled <= order.quantity
        assert order.filled_quantity == total_executed
        assert order.status == ("Filled" if total_executed == order.quantity else "PartiallyFilled")
    _assert_ledger_consistent(pg_engine)


@pytest.mark.parametrize(
    ("sell_a", "sell_b", "expected_ok", "expected_sold"),
    [(60, 60, 1, 60), (100, 100, 1, 100), (40, 40, 2, 80)],
    ids=["60+60-exceeds-100-available", "100+100-exceeds-100-available", "40+40-fits-no-false-block"],
)
def test_pg_two_sell_orders_same_symbol_never_sell_more_than_settled_available(
    pg_engine: Engine, fake_clock, sell_a: int, sell_b: int, expected_ok: int, expected_sold: int
) -> None:
    fake_clock.set_market(*BUY_DAY)
    signal = _seed_common(pg_engine)
    with _new_session(pg_engine) as session:
        buy_id = _open_order(session, signal, "BUY", quantity=100)
        _fill(session, buy_id, 100, tag="seed-buy")
    fake_clock.set_market(*SELL_DAY)
    with _new_session(pg_engine) as session:
        assert PortfolioService(session).get_settled_available_quantity(SYMBOL, as_of=clock.market_today()) == 100
        sell_ids = [_open_order(session, signal, "SELL", quantity=q) for q in (sell_a, sell_b)]
    _install_insert_rendezvous(pg_engine, parties=2)

    results = _run_concurrent_fills(pg_engine, [(sell_ids[0], sell_a), (sell_ids[1], sell_b)])

    assert [r for r in results if r[0] == "error"] == []
    assert sum(1 for kind, _ in results if kind == "ok") == expected_ok, results
    assert all(detail == 400 for kind, detail in results if kind == "rejected"), results
    with _new_session(pg_engine) as session:
        sold = session.scalar(
            select(func.coalesce(func.sum(Execution.quantity), 0))
            .join(Order, Execution.order_id == Order.id)
            .where(Order.side == "SELL")
        )
        assert sold == expected_sold <= 100
        position = session.scalar(select(Position))
        assert position.quantity == 100 - expected_sold
        assert position.available_quantity == 100 - expected_sold
    _assert_ledger_consistent(pg_engine)


@pytest.mark.parametrize(
    ("capital", "qty_a", "qty_b", "expected_ok"),
    [
        (CAPITAL, 600, 600, 1),
        (CAPITAL, 700, 500, 1),
        (CAPITAL, 400, 400, 2),
        (Decimal("20030000.00"), 400, 400, 2),
        (Decimal("20029999.99"), 400, 400, 1),
    ],
    ids=[
        "600+600-combined-30045000-exceeds-30000000",
        "700+500-combined-30045000-exceeds-30000000",
        "400+400-combined-20030000-affordable",
        "400+400-exactly-affordable-cash-ends-at-zero",
        "400+400-one-cent-short-only-one-succeeds",
    ],
)
def test_pg_concurrent_buys_of_different_symbols_never_lose_cash_or_exceed_buying_power(
    pg_engine: Engine,
    fake_clock,
    monkeypatch: pytest.MonkeyPatch,
    capital: Decimal,
    qty_a: int,
    qty_b: int,
    expected_ok: int,
) -> None:
    monkeypatch.setattr(get_settings(), "INITIAL_PAPER_CAPITAL", capital)
    fake_clock.set_market(*BUY_DAY)
    signals = _seed_symbols(pg_engine, ("FPT", "VCB"))
    with _new_session(pg_engine) as session:
        order_a = _open_order(session, signals["FPT"], "BUY", qty_a, symbol="FPT")
        order_b = _open_order(session, signals["VCB"], "BUY", qty_b, symbol="VCB")
    _install_insert_rendezvous(pg_engine, parties=2)

    results = _run_concurrent_fills(pg_engine, [(order_a, qty_a), (order_b, qty_b)])

    assert [r for r in results if r[0] == "error"] == []
    assert sum(1 for kind, _ in results if kind == "ok") == expected_ok, results
    assert all(detail == 400 for kind, detail in results if kind == "rejected"), results
    filled = {
        symbol: quantity
        for (kind, _), symbol, quantity in zip(results, ("FPT", "VCB"), (qty_a, qty_b))
        if kind == "ok"
    }
    assert _positions(pg_engine) == filled
    assert _account_cash(pg_engine) == capital - sum(_buy_cost(q) for q in filled.values())
    assert _account_cash(pg_engine) >= Decimal("0.00")
    with _new_session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Execution)) == expected_ok
        assert session.scalar(
            select(func.count()).select_from(CashTransaction).where(CashTransaction.transaction_type == "BUY_EXECUTION")
        ) == expected_ok
    _assert_ledger_consistent(pg_engine)


def test_pg_concurrent_sell_and_buy_of_different_symbols_do_not_lose_cash_update(
    pg_engine: Engine, fake_clock
) -> None:
    fake_clock.set_market(*BUY_DAY)
    signals = _seed_symbols(pg_engine, ("FPT", "VCB"))
    with _new_session(pg_engine) as session:
        seed_buy = _open_order(session, signals["FPT"], "BUY", 100, symbol="FPT")
        _fill(session, seed_buy, 100, tag="seed-buy")
    fake_clock.set_market(*SELL_DAY)
    with _new_session(pg_engine) as session:
        sell_order = _open_order(session, signals["FPT"], "SELL", 100, symbol="FPT")
        buy_order = _open_order(session, signals["VCB"], "BUY", 200, symbol="VCB")
    _install_insert_rendezvous(pg_engine, parties=2)

    results = _run_jobs(
        pg_engine,
        {
            "sell": lambda session: _fill(session, sell_order, 100, tag="sell").status,
            "buy": lambda session: _fill(session, buy_order, 200, tag="buy").status,
        },
    )

    assert results == {"sell": ("ok", "Filled"), "buy": ("ok", "Filled")}
    assert _account_cash(pg_engine) == CAPITAL - _buy_cost(100) - _buy_cost(200) + _sell_proceeds(100)
    assert _positions(pg_engine) == {"FPT": 0, "VCB": 200}
    _assert_ledger_consistent(pg_engine)


@pytest.mark.parametrize(
    ("holder", "prefill", "fill_qty", "expected_fill", "expected_cancel", "final_status", "executed_pieces", "audits"),
    [
        (
            "fill", 0, 100, ("ok", "Filled"), ("rejected", 409), "Filled", (100,),
            {"PAPER_ORDER_SUBMITTED": 1, "ORDER_FILLED": 1},
        ),
        (
            "fill", 0, 40, ("ok", "PartiallyFilled"), ("ok", "Cancelled"), "Cancelled", (40,),
            {"PAPER_ORDER_SUBMITTED": 1, "ORDER_PARTIALLYFILLED": 1, "PAPER_ORDER_CANCELLED": 1},
        ),
        (
            "fill", 40, 60, ("ok", "Filled"), ("rejected", 409), "Filled", (40, 60),
            {"PAPER_ORDER_SUBMITTED": 1, "ORDER_PARTIALLYFILLED": 1, "ORDER_FILLED": 1},
        ),
        (
            "fill", 40, 30, ("ok", "PartiallyFilled"), ("ok", "Cancelled"), "Cancelled", (40, 30),
            {"PAPER_ORDER_SUBMITTED": 1, "ORDER_PARTIALLYFILLED": 2, "PAPER_ORDER_CANCELLED": 1},
        ),
        (
            "cancel", 0, 100, ("rejected", 409), ("ok", "Cancelled"), "Cancelled", (),
            {"PAPER_ORDER_SUBMITTED": 1, "PAPER_ORDER_CANCELLED": 1},
        ),
        (
            "cancel", 40, 60, ("rejected", 409), ("ok", "Cancelled"), "Cancelled", (40,),
            {"PAPER_ORDER_SUBMITTED": 1, "ORDER_PARTIALLYFILLED": 1, "PAPER_ORDER_CANCELLED": 1},
        ),
    ],
    ids=[
        "fill-first-full-then-cancel-rejected-stays-Filled",
        "fill-first-partial-then-cancel-ok",
        "fill-first-completes-remaining-then-cancel-rejected-stays-Filled",
        "fill-first-partial-again-then-cancel-ok",
        "cancel-first-then-fill-rejected-stays-Cancelled",
        "cancel-first-after-partial-then-fill-rejected-stays-Cancelled",
    ],
)
def test_pg_cancel_and_fill_on_same_order_are_serialized_by_order_lock(
    pg_engine: Engine,
    fake_clock,
    holder: str,
    prefill: int,
    fill_qty: int,
    expected_fill: tuple[str, Any],
    expected_cancel: tuple[str, Any],
    final_status: str,
    executed_pieces: tuple[int, ...],
    audits: dict[str, int],
) -> None:
    """
    `holder` là bên giữ khóa Order trước: nó dừng giữa chừng khi đã cầm khóa (fill: ngay trước INSERT execution; cancel:
    ngay trước INSERT audit_logs), bên còn lại được khởi động và phải bị PostgreSQL chặn, rồi bên giữ khóa chạy nốt.
    Không có khóa FOR UPDATE ở cancel_order thì case fill-first sẽ ghi đè Filled thành Cancelled (hoặc Cancelled có execution).
    """
    fake_clock.set_market(*BUY_DAY)
    signal = _seed_common(pg_engine)
    with _new_session(pg_engine) as session:
        order_id = _open_order(session, signal, "BUY", quantity=100)
        if prefill:
            _fill(session, order_id, prefill, tag="prefill")
    pauses = _PausePoints(pg_engine)
    jobs = {
        "fill": _Job(
            pg_engine, "fill", lambda session: _fill(session, order_id, fill_qty, tag="staged").status
        ),
        "cancel": _Job(
            pg_engine,
            "cancel",
            lambda session: PaperBrokerAdapter(session=session)
            .cancel_order(order_id=order_id, actor="concurrency_test")
            .status,
        ),
    }
    holding, waiting = jobs[holder], jobs["cancel" if holder == "fill" else "fill"]
    reached, release = pauses.add(holder, EXECUTIONS_INSERT if holder == "fill" else AUDIT_INSERT)

    holding.thread.start()
    assert reached.wait(timeout=15), f"{holder} không tới điểm dừng"
    waiting.thread.start()
    _wait_until_lock_waiters(pg_engine)
    release.set()
    _join_jobs([holding, waiting])

    assert jobs["fill"].result == expected_fill
    assert jobs["cancel"].result == expected_cancel
    snapshot = _order_snapshot(pg_engine, order_id)
    assert snapshot["status"] == final_status
    assert snapshot["filled_quantity"] == snapshot["executed"] == sum(executed_pieces)
    assert snapshot["audits"] == audits
    assert _account_cash(pg_engine) == CAPITAL - sum(_buy_cost(q) for q in executed_pieces)
    assert _positions(pg_engine) == ({SYMBOL: sum(executed_pieces)} if executed_pieces else {})
    with _new_session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Execution)) == len(executed_pieces)
    _assert_ledger_consistent(pg_engine)


@pytest.mark.parametrize(
    "fill_qty", [100, 40], ids=["full-fill-vs-cancel", "partial-fill-vs-cancel"]
)
def test_pg_free_running_cancel_vs_fill_races_never_break_state_machine_or_ledger(
    pg_engine: Engine, fake_clock, fill_qty: int
) -> None:
    fake_clock.set_market(*BUY_DAY)
    signal = _seed_common(pg_engine)
    with _new_session(pg_engine) as session:
        order_ids = [_open_order(session, signal, "BUY", quantity=100) for _ in range(8)]

    filled_pieces = 0
    for order_id in order_ids:
        results = _run_jobs(
            pg_engine,
            {
                "fill": lambda session, oid=order_id: _fill(session, oid, fill_qty, tag="free").status,
                "cancel": lambda session, oid=order_id: PaperBrokerAdapter(session=session)
                .cancel_order(order_id=oid, actor="concurrency_test")
                .status,
            },
        )
        snapshot = _order_snapshot(pg_engine, order_id)

        assert "error" not in {kind for kind, _ in results.values()}, results
        outcome = (results["fill"], results["cancel"])
        fill_first = (
            (("ok", "Filled"), ("rejected", 409))
            if fill_qty == 100
            else (("ok", "PartiallyFilled"), ("ok", "Cancelled"))
        )
        cancel_first = (("rejected", 409), ("ok", "Cancelled"))
        assert outcome in (fill_first, cancel_first), results
        if outcome == fill_first:
            filled_pieces += 1
            assert snapshot["status"] == ("Filled" if fill_qty == 100 else "Cancelled")
            assert snapshot["filled_quantity"] == snapshot["executed"] == fill_qty
        else:
            assert snapshot["status"] == "Cancelled"
            assert snapshot["filled_quantity"] == snapshot["executed"] == 0

    assert _account_cash(pg_engine) == CAPITAL - filled_pieces * _buy_cost(fill_qty)
    assert _positions(pg_engine) == ({SYMBOL: filled_pieces * fill_qty} if filled_pieces else {})
    _assert_ledger_consistent(pg_engine)


def test_pg_two_concurrent_cancels_of_same_order_cancel_exactly_once(pg_engine: Engine, fake_clock) -> None:
    fake_clock.set_market(*BUY_DAY)
    signal = _seed_common(pg_engine)
    with _new_session(pg_engine) as session:
        order_id = _open_order(session, signal, "BUY", quantity=100)
    _install_rendezvous(pg_engine, parties=2, statement_prefix=AUDIT_INSERT)

    def cancel(session: Session) -> str:
        return PaperBrokerAdapter(session=session).cancel_order(order_id=order_id).status

    results = _run_jobs(pg_engine, {"cancel_a": cancel, "cancel_b": cancel})

    assert sorted(results.values(), key=str) == [("ok", "Cancelled"), ("rejected", 409)]
    assert _order_snapshot(pg_engine, order_id)["audits"] == {
        "PAPER_ORDER_SUBMITTED": 1,
        "PAPER_ORDER_CANCELLED": 1,
    }
    assert _order_snapshot(pg_engine, order_id)["status"] == "Cancelled"
    _assert_ledger_consistent(pg_engine)


def test_pg_mixed_fills_and_cancels_across_symbols_do_not_deadlock_or_lose_cash(
    pg_engine: Engine, fake_clock
) -> None:
    """12 thread cùng lúc (BUY độc lập 4 mã + 4 cặp cancel-vs-fill) mỗi vòng: không deadlock, tiền và sổ cái chính xác."""
    fake_clock.set_market(*BUY_DAY)
    symbols = ("FPT", "VCB", "HPG", "MWG")
    signals = _seed_symbols(pg_engine, symbols)
    quantity = 40

    for _ in range(2):
        with _new_session(pg_engine) as session:
            solo = {s: _open_order(session, signals[s], "BUY", quantity, symbol=s) for s in symbols}
            raced = {s: _open_order(session, signals[s], "BUY", quantity, symbol=s) for s in symbols}
        actions: dict[str, Callable[[Session], Any]] = {}
        for symbol in symbols:
            actions[f"solo-{symbol}"] = (
                lambda session, oid=solo[symbol]: _fill(session, oid, quantity, tag="solo").status
            )
            actions[f"fill-{symbol}"] = (
                lambda session, oid=raced[symbol]: _fill(session, oid, quantity, tag="raced").status
            )
            actions[f"cancel-{symbol}"] = (
                lambda session, oid=raced[symbol]: PaperBrokerAdapter(session=session)
                .cancel_order(order_id=oid, actor="concurrency_test")
                .status
            )

        results = _run_jobs(pg_engine, actions)

        assert "error" not in {kind for kind, _ in results.values()}, results
        for symbol in symbols:
            assert results[f"solo-{symbol}"] == ("ok", "Filled")
            fill, cancel = results[f"fill-{symbol}"], results[f"cancel-{symbol}"]
            assert (fill, cancel) in (
                (("ok", "Filled"), ("rejected", 409)),
                (("rejected", 409), ("ok", "Cancelled")),
            ), results
            status = _order_snapshot(pg_engine, raced[symbol])["status"]
            assert status == ("Filled" if fill[0] == "ok" else "Cancelled")

    with _new_session(pg_engine) as session:
        executions = session.scalar(select(func.count()).select_from(Execution))
    assert _account_cash(pg_engine) == CAPITAL - executions * _buy_cost(quantity)
    assert sum(_positions(pg_engine).values()) == executions * quantity
    _assert_ledger_consistent(pg_engine)


def test_pg_concurrent_first_time_default_account_creation_makes_exactly_one_account(
    pg_engine: Engine,
) -> None:
    _install_rendezvous(pg_engine, parties=2, statement_prefix=ACCOUNT_INSERT)

    def create_and_commit(session: Session) -> uuid.UUID:
        account_id = PortfolioService(session).get_or_create_default_paper_account(for_update=True).id
        session.commit()
        return account_id

    results = _run_jobs(pg_engine, {"worker_a": create_and_commit, "worker_b": create_and_commit})

    assert {kind for kind, _ in results.values()} == {"ok"}, results
    assert results["worker_a"][1] == results["worker_b"][1]
    with _new_session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(CashTransaction)
                .where(CashTransaction.transaction_type == "INITIAL_DEPOSIT")
            )
            == 1
        )
    assert _account_cash(pg_engine) == CAPITAL
