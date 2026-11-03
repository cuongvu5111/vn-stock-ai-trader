# Ngày tạo: 2026-11-03
# Mục đích: Kiểm thử tích hợp End-to-End (E2E) toàn bộ chu trình của hệ thống:
#           Import CSV -> Indicators -> Scanner/Signals -> AI Report -> Trade Proposal ->
#           Human Approval -> Paper Order & Fill -> Portfolio Snapshot/Ledger/Reconcile -> Audit Trail & Job Runs.

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
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
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import create_app


@pytest.fixture(autouse=True)
def _force_mock_ai_settings_in_e2e_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đảm bảo E2E test chạy deterministic với MockAiAnalysisProvider kể cả khi .env bật LLM thật."""
    settings = get_settings()
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    monkeypatch.setattr(settings, "AI_MODEL", "mock-v1")
    monkeypatch.setattr(settings, "LLM_MODEL", "")


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


def test_end_to_end_daily_workflow_and_paper_trading_lifecycle(db_session: Session) -> None:
    """
    Kiểm thử trọn vẹn luồng nghiệp vụ Sprint 7:
    1. Chạy Daily EOD Workflow (`/api/v1/system/daily-workflow`) tự động nạp `sample_ohlcv_data.csv`,
       tính chỉ báo, quét tín hiệu, tạo báo cáo AI, tạo Proposal chờ duyệt (`PendingApproval`) và chốt Snapshot.
    2. Kiểm tra `/api/v1/system/jobs` ghi nhận lịch sử `DAILY_EOD_WORKFLOW` thành công.
    3. Kiểm tra `/api/v1/proposals` có đề xuất ở trạng thái `PendingApproval` (chưa hề có lệnh Paper nào được tự động tạo).
    4. Người dùng thực hiện Human Approval (`/api/v1/proposals/{id}/approve`) -> tạo lệnh Paper ở trạng thái `Submitted`.
    5. Mô phỏng khớp lệnh trên Paper Broker (`/api/v1/orders/{id}/simulate-fill`) -> lệnh chuyển sang `Filled`.
    6. Kiểm tra `/api/v1/portfolio`, `/api/v1/portfolio/ledger`, `/api/v1/portfolio/snapshots`, `/api/v1/portfolio/reconcile`
       và `/api/v1/risk` (audit trail đầy đủ).
    """
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    # 1. Kích hoạt Daily EOD Workflow
    wf_resp = client.post(
        "/api/v1/system/daily-workflow",
        json={
            "import_sample_csv_if_empty": True,
            "run_ai_analysis": True,
            "create_proposals": True,
        },
    )
    assert wf_resp.status_code == 200
    wf = wf_resp.json()
    assert wf["status"] == "COMPLETED"
    assert wf["imported_rows"] > 0
    assert wf["indicators_upserted"] > 0
    assert wf["signals_generated"] >= 1
    assert wf["ai_reports_created"] >= 1
    assert wf["proposals_created"] >= 1

    # 2. Kiểm tra JobRun đã lưu
    jobs_resp = client.get("/api/v1/system/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert jobs["total"] >= 1
    assert jobs["items"][0]["job_name"] == "DAILY_EOD_WORKFLOW"
    assert jobs["items"][0]["status"] == "COMPLETED"

    # 3. Kiểm tra danh sách Proposals đang chờ con người phê duyệt (PendingApproval)
    props_resp = client.get("/api/v1/proposals?status=PendingApproval")
    assert props_resp.status_code == 200
    props = props_resp.json()["items"]
    assert len(props) >= 1
    target_prop = props[0]
    proposal_id = target_prop["id"]

    # Đảm bảo chưa có bất kỳ Order nào được tạo trước khi con người nhấn Approve
    orders_before = client.get("/api/v1/orders").json()
    assert orders_before["total"] == 0

    # 4. Người dùng nhấn Approve đề xuất
    approve_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        json={
            "approved_by": "cuong_e2e_reviewer",
            "comment": "Xác nhận duyệt đề xuất sau khi xem AI Report & Risk Check",
            "expected_quantity": target_prop["proposed_quantity"],
            "auto_submit_and_fill_in_paper": False,
        },
    )
    assert approve_resp.status_code == 200
    approved_prop = approve_resp.json()
    assert approved_prop["status"] == "Submitted"
    order_id = approved_prop["order_id"]
    assert order_id is not None

    # 5. Mô phỏng khớp toàn bộ lệnh trên Paper Broker
    fill_resp = client.post(
        f"/api/v1/orders/{order_id}/simulate-fill",
        json={
            "fill_quantity": target_prop["proposed_quantity"],
            "fill_price": str(target_prop["limit_price"]),
        },
    )
    assert fill_resp.status_code == 200
    filled_order = fill_resp.json()
    assert filled_order["status"] == "Filled"
    assert filled_order["filled_quantity"] == target_prop["proposed_quantity"]

    # 6. Kiểm tra Portfolio, Cash Ledger, Reconcile và Audit Trail
    portfolio = client.get("/api/v1/portfolio").json()
    assert Decimal(portfolio["cash_balance"]) < Decimal("30000000.00")
    assert portfolio["open_positions_count"] == 1
    assert portfolio["positions"][0]["symbol"] == target_prop["symbol"]
    assert portfolio["positions"][0]["quantity"] == target_prop["proposed_quantity"]

    ledger = client.get("/api/v1/portfolio/ledger").json()
    assert ledger["total"] >= 2  # INITIAL_DEPOSIT + BUY_EXECUTION

    reconcile = client.post("/api/v1/portfolio/reconcile").json()
    assert reconcile["is_consistent_before_rebuild"] is True

    risk_status = client.get("/api/v1/risk").json()
    audit_actions = [a["action"] for a in risk_status["recent_audit_logs"]]
    assert "PROPOSAL_APPROVED_AND_ORDER_CREATED" in audit_actions
    assert "ORDER_FILLED" in audit_actions
