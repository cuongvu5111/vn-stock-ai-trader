# Ngày tạo: 2026-11-03
# Mục đích: Kiểm thử toàn diện Sprint 6 — Risk Engine, Position Sizing, State Machine,
#           Human Approval (Double-Approve / Expired / Re-validation), Partial Fills và Portfolio Reconciliation.

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.indicators.models  # noqa: F401
import app.market_data.models  # noqa: F401
import app.portfolio.models  # noqa: F401
import app.strategies.models  # noqa: F401
import app.system.models  # noqa: F401
import app.trading.models  # noqa: F401
from app.core.database import Base, get_db_session
from app.indicators.models import StockSignal
from app.main import create_app
from app.market_data.models import DailyPrice, DataSource, Stock
from app.portfolio.models import Account, Position
from app.risk.engine import evaluate_trade_risk_and_sizing
from app.schemas.trading import RiskConfigPayload
from app.trading.models import Approval, Order, TradeProposal
from app.trading.paper_broker import PaperBrokerAdapter


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(BigInteger, "sqlite")
def compile_bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "market": None,
                "analysis": None,
                "strategy": None,
                "trading": None,
                "portfolio": None,
                "system": None,
            }
        },
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_stock_and_buy_signal(
    session: Session,
    symbol: str = "FPT",
    reference_price: Decimal = Decimal("25000.0000"),
    stop_loss: Decimal = Decimal("24000.0000"),
) -> tuple[Stock, StockSignal]:
    ds = session.scalar(select(DataSource).where(DataSource.name == "SAMPLE_CSV"))
    if ds is None:
        ds = DataSource(
            name="SAMPLE_CSV",
            provider_type="CSV",
            license_notes="SAMPLE CSV for unit tests",
        )
        session.add(ds)
        session.flush()

    stock = Stock(
        symbol=symbol,
        exchange="HOSE",
        company_name=f"[SAMPLE] Công ty {symbol}",
        is_active=True,
    )
    session.add(stock)
    session.flush()

    session.add(
        DailyPrice(
            stock_id=stock.id,
            source_id=ds.id,
            trading_date=date(2026, 5, 29),
            open=reference_price,
            high=reference_price + Decimal("500"),
            low=reference_price - Decimal("500"),
            close=reference_price,
            volume=1500000,
        )
    )

    sig = StockSignal(
        stock_id=stock.id,
        trading_date=date(2026, 5, 29),
        action="BUY",
        score=Decimal("82.50"),
        reference_price=reference_price,
        stop_loss=stop_loss,
        reason={
            "strategy_name": "TrendFollowingStrategy",
            "reasons": ["EMA20 > EMA50", "Close vượt đỉnh 20 phiên"],
            "invalidation_condition": "Đóng cửa thủng 24,000 VND",
        },
        status="GENERATED",
    )
    session.add(sig)
    session.commit()
    session.refresh(stock)
    session.refresh(sig)
    return stock, sig


def test_position_sizing_formula_m9_2() -> None:
    """Kiểm tra công thức định cỡ vị thế chuẩn Mục 9.2 (lot size 100, risk cap 1%, pos cap 20%)."""
    cfg = RiskConfigPayload(
        max_position_percent=Decimal("20"),
        max_risk_per_trade_percent=Decimal("1"),
        max_daily_loss_percent=Decimal("2"),
        max_open_positions=5,
        max_portfolio_allocation_percent=Decimal("70"),
        lot_size=100,
    )
    # NAV = 30,000,000 VND
    # entry = 25,000, stop_loss = 24,000 -> risk_per_share = 1,000
    # max_risk_amount = 1% * 30,000,000 = 300,000 -> qty_by_risk = 300
    # max_pos_value = 20% * 30,000,000 = 6,000,000 -> qty_by_position_cap = 6,000,000 / 25,000 = 240
    # final_qty = floor_to_lot(min(300, 240, ...), 100) = 200 cổ phiếu
    res = evaluate_trade_risk_and_sizing(
        side="BUY",
        entry_price=Decimal("25000"),
        stop_loss=Decimal("24000"),
        nav=Decimal("30000000"),
        available_cash=Decimal("30000000"),
        current_symbol_market_value=Decimal("0"),
        total_portfolio_market_value=Decimal("0"),
        open_positions_count=0,
        is_new_symbol_position=True,
        available_position_qty_for_sell=0,
        daily_loss_amount=Decimal("0"),
        has_conflicting_order_or_proposal=False,
        config=cfg,
    )
    assert res.passed is True
    assert res.proposed_quantity == 200
    assert res.details["qty_by_risk"] == 300
    assert res.details["qty_by_position_cap"] == 240


def test_cannot_create_paper_order_without_valid_human_approval(db_session: Session) -> None:
    """Đảm bảo PaperBrokerAdapter từ chối tạo Order nếu chưa có bản ghi Approval hợp lệ."""
    _, sig = _seed_stock_and_buy_signal(db_session)
    proposal = TradeProposal(
        signal_id=sig.id,
        symbol="FPT",
        side="BUY",
        proposed_quantity=200,
        limit_price=Decimal("25000.0000"),
        stop_loss=Decimal("24000.0000"),
        estimated_cost=Decimal("5007500.00"),
        risk_amount=Decimal("200000.00"),
        status="PendingApproval",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db_session.add(proposal)
    db_session.flush()

    fake_rejected_approval = Approval(
        proposal_id=proposal.id,
        decision="REJECTED",
        approved_by="tester",
    )
    db_session.add(fake_rejected_approval)
    db_session.flush()

    broker = PaperBrokerAdapter(session=db_session)
    with pytest.raises(Exception) as exc_info:
        broker.create_paper_order_from_approved_proposal(
            proposal=proposal,
            approval=fake_rejected_approval,
        )
    assert "Human Approval" in str(exc_info.value)


def test_double_approve_creates_only_one_order(db_session: Session) -> None:
    """Approve cùng một Proposal hai lần chỉ tạo tối đa 1 Order và trả về 409 ở lần thứ hai."""
    _, sig = _seed_stock_and_buy_signal(db_session)
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    create_resp = client.post(
        "/api/v1/proposals",
        json={"signal_id": str(sig.id), "expiry_minutes": 120},
    )
    assert create_resp.status_code == 200
    prop_data = create_resp.json()
    proposal_id = prop_data["id"]
    assert prop_data["status"] == "PendingApproval"
    assert prop_data["proposed_quantity"] == 200

    # Lần Approve thứ nhất -> thành công, chuyển sang Submitted và tạo 1 Order
    approve_1 = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={
            "approved_by": "cuong_trader",
            "comment": "Đồng ý mua FPT theo tín hiệu Trend Following",
            "expected_quantity": 200,
        },
    )
    assert approve_1.status_code == 200
    body_1 = approve_1.json()
    assert body_1["status"] == "Submitted"
    assert body_1["order_id"] is not None

    # Lần Approve thứ hai -> bị chặn với 409 Conflict
    approve_2 = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={
            "approved_by": "cuong_trader",
            "comment": "Bấm nhầm lần 2",
        },
    )
    assert approve_2.status_code == 409

    # Kiểm tra trong DB chỉ có đúng 1 Order được tạo
    orders = db_session.scalars(select(Order)).all()
    assert len(orders) == 1


def test_expired_proposal_cannot_be_approved(db_session: Session) -> None:
    """Proposal đã quá hạn expires_at không thể approve và tự động chuyển sang trạng thái Expired."""
    _, sig = _seed_stock_and_buy_signal(db_session, symbol="VCB")
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    create_resp = client.post(
        "/api/v1/proposals",
        json={"signal_id": str(sig.id), "expiry_minutes": 60},
    )
    assert create_resp.status_code == 200
    proposal_id = uuid.UUID(create_resp.json()["id"])

    # Tua thời gian hết hạn về quá khứ
    prop_row = db_session.get(TradeProposal, proposal_id)
    assert prop_row is not None
    prop_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    approve_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={"approved_by": "cuong_trader"},
    )
    assert approve_resp.status_code == 409
    assert "Expired" in approve_resp.json()["error"]["message"]

    db_session.refresh(prop_row)
    assert prop_row.status == "Expired"
    assert len(db_session.scalars(select(Order)).all()) == 0


def test_risk_revalidation_on_approve_and_kill_switch(db_session: Session) -> None:
    """
    Kiểm tra:
    1. Sau khi tạo Proposal ở trạng thái PendingApproval, nếu người dùng bật Kill Switch (`trading_enabled=False`),
       lúc nhấn Approve hệ thống phải Re-validate Risk, chuyển Proposal sang `Blocked` và KHÔNG tạo Order.
    2. Khi Kill Switch đang bật, mọi yêu cầu tạo Proposal mới đều bị chặn.
    """
    _, sig = _seed_stock_and_buy_signal(db_session, symbol="ACB")
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    # 1. Tạo Proposal khi hệ thống đang bình thường
    create_resp = client.post("/api/v1/proposals", json={"signal_id": str(sig.id)})
    assert create_resp.status_code == 200
    proposal_id = create_resp.json()["id"]

    # 2. Kích hoạt Kill Switch (trading_enabled = False)
    risk_cfg = RiskConfigPayload(trading_enabled=False)
    put_risk = client.put(
        "/api/v1/risk",
        json={
            "actor": "risk_officer",
            "reason": "Thị trường biến động mạnh, kích hoạt Kill Switch",
            "configuration": risk_cfg.model_dump(mode="json"),
        },
    )
    assert put_risk.status_code == 200
    assert put_risk.json()["kill_switch_active"] is True

    # 3. Nhấn Approve trên Proposal đã tạo trước đó -> Re-validation chặn lại -> status = Blocked
    approve_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={"approved_by": "cuong_trader"},
    )
    assert approve_resp.status_code == 200
    approved_body = approve_resp.json()
    assert approved_body["status"] == "Blocked"
    assert approved_body["order_id"] is None
    assert len(db_session.scalars(select(Order)).all()) == 0

    # 4. Thử tạo một Proposal mới khi Kill Switch đang bật -> bị chặn 400 Bad Request
    _, sig2 = _seed_stock_and_buy_signal(db_session, symbol="MBB")
    blocked_create = client.post("/api/v1/proposals", json={"signal_id": str(sig2.id)})
    assert blocked_create.status_code == 400
    assert "KILL_SWITCH" in blocked_create.json()["error"]["message"]


def test_partial_fills_and_portfolio_reconciliation(db_session: Session) -> None:
    """
    Kiểm tra:
    - Khớp lệnh từng phần (Partial Fill 100 cp @ 25,000 rồi 100 cp @ 25,200) cập nhật chính xác
      filled_quantity, average_fill_price, Order.status, cash_balance và positions.
    - Khi cố tình làm lệch cash_balance và positions trong DB, gọi `/api/v1/portfolio/reconcile`
      sẽ phát hiện sai lệch và tái dựng lại đúng tuyệt đối từ `cash_transactions` & `executions`.
    """
    _, sig = _seed_stock_and_buy_signal(db_session, symbol="HPG")
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    create_resp = client.post("/api/v1/proposals", json={"signal_id": str(sig.id)})
    proposal_id = create_resp.json()["id"]

    approve_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={"approved_by": "cuong_trader", "auto_submit_and_fill_in_paper": False},
    )
    order_id = approve_resp.json()["order_id"]
    assert order_id is not None

    # Đợt khớp 1: 100 cổ phiếu @ 25,000 VND
    # Gross = 2,500,000 | Fee (0.15%) = 3,750 | Outflow 1 = 2,503,750
    fill_1 = client.post(
        f"/api/v1/orders/{order_id}/simulate-fill",
        json={"fill_quantity": 100, "fill_price": "25000.0000"},
    )
    assert fill_1.status_code == 200
    ord_1 = fill_1.json()
    assert ord_1["status"] == "PartiallyFilled"
    assert ord_1["filled_quantity"] == 100
    assert Decimal(ord_1["average_fill_price"]) == Decimal("25000.0000")

    # Đợt khớp 2: 100 cổ phiếu @ 25,200 VND
    # Gross = 2,520,000 | Fee (0.15%) = 3,780 | Outflow 2 = 2,523,780
    # Tổng Outflow = 5,027,530 -> Cash còn lại = 30,000,000 - 5,027,530 = 24,972,470 VND
    fill_2 = client.post(
        f"/api/v1/orders/{order_id}/simulate-fill",
        json={"fill_quantity": 100, "fill_price": "25200.0000"},
    )
    assert fill_2.status_code == 200
    ord_2 = fill_2.json()
    assert ord_2["status"] == "Filled"
    assert ord_2["filled_quantity"] == 200
    assert Decimal(ord_2["average_fill_price"]) == Decimal("25100.0000")
    assert len(ord_2["executions"]) == 2

    # Kiểm tra trạng thái Portfolio sau 2 lần partial fill
    port_resp = client.get("/api/v1/portfolio")
    assert port_resp.status_code == 200
    port = port_resp.json()
    expected_cash = Decimal("24972470.00")
    assert Decimal(port["cash_balance"]) == expected_cash
    assert port["open_positions_count"] == 1
    assert port["positions"][0]["symbol"] == "HPG"
    assert port["positions"][0]["quantity"] == 200
    # Giá vốn bình quân có phí = 5,027,530 / 200 = 25,137.6500
    assert Decimal(port["positions"][0]["average_cost"]) == Decimal("25137.6500")

    # Giả lập lỗi sai lệch dữ liệu tổng hợp (corrupt cash_balance & position quantity)
    account = db_session.scalar(select(Account))
    pos = db_session.scalar(select(Position))
    assert account is not None and pos is not None
    account.cash_balance = Decimal("999999.00")
    pos.quantity = 500
    db_session.commit()

    # Gọi API đối soát & tái dựng từ sổ cái gốc
    rec_resp = client.post("/api/v1/portfolio/reconcile")
    assert rec_resp.status_code == 200
    rec = rec_resp.json()
    assert rec["is_consistent_before_rebuild"] is False
    assert Decimal(rec["rebuilt_cash_balance"]) == expected_cash
    assert len(rec["discrepancies"]) >= 2

    # Kiểm tra lại Portfolio sau khi Reconcile: số dư và vị thế đã được khôi phục chuẩn xác
    port_after = client.get("/api/v1/portfolio").json()
    assert Decimal(port_after["cash_balance"]) == expected_cash
    assert port_after["positions"][0]["quantity"] == 200
    assert Decimal(port_after["positions"][0]["average_cost"]) == Decimal("25137.6500")
