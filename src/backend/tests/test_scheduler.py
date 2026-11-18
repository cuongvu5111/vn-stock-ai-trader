# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử scheduler Daily EOD (app/system/scheduler.py) mà không chờ đồng hồ thật:
#   - cấu hình job (cron thứ 2-6 16:30 Asia/Ho_Chi_Minh, coalesce, max_instances=1, misfire grace) và mặc định TẮT;
#   - vòng đời start/shutdown qua FastAPI lifespan và việc APScheduler thực sự gọi job (kích hoạt bằng next_run_time giả);
#   - chạy thành công dừng ở PendingApproval (không Approval/Order/Execution, không import dữ liệu SAMPLE);
#   - chạy lỗi: rollback, đúng một JobRun FAILED (kể cả khi bản ghi RUNNING đã bị commit bởi bước con), log có cấu trúc.

import ast
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from structlog.testing import capture_logs

import app.main as main_module
import app.system.scheduler as scheduler_module
from app.core.config import Settings
from app.core.database import Base
from app.core.logging import correlation_id_ctx
from app.indicators.service import IndicatorService
from app.market_data.models import DailyPrice
from app.market_data.service import MarketDataService
from app.screening.service import ScannerService
from app.system.models import AuditLog, JobRun
from app.system.scheduler import (
    DAILY_EOD_SCHEDULER_JOB_ID,
    SCHEDULER_ACTOR,
    SCHEDULER_TIMEZONE_NAME,
    build_safe_daily_payload,
    build_scheduler,
    run_scheduled_daily_eod,
    shutdown_scheduler,
    start_scheduler,
)
from app.system.service import SystemWorkflowService
from app.trading.models import Approval, Execution, Order, TradeProposal

STRONG_SECRET = "Xk9#mP2$vL8@nQ4!wR7&tY1^uI5*oE3-zA6+bC0"
SAMPLE_CSV = Path(__file__).resolve().parents[3] / "database" / "seeds" / "sample_ohlcv_data.csv"
MARKET_TZ = ZoneInfo(SCHEDULER_TIMEZONE_NAME)


def make_settings(**overrides) -> Settings:
    values = {"_env_file": None, "JWT_SECRET_KEY": STRONG_SECRET, "AI_ENABLED": False}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def session_factory():
    """Engine SQLite in-memory dùng chung nhiều Session, giống cách job tự mở Session riêng mỗi lần chạy."""
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
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def seeded_factory(session_factory):
    """Dữ liệu giá đã có sẵn (gắn nhãn SAMPLE) vì job tự động tuyệt đối không tự import dữ liệu mẫu."""
    with session_factory() as session:
        MarketDataService(session=session).import_csv_content(
            csv_text=SAMPLE_CSV.read_text(encoding="utf-8"),
            file_name=SAMPLE_CSV.name,
            source_name="SAMPLE_CSV_SEED",
            is_sample=True,
        )
    return session_factory


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------------------
# Cấu hình
# --------------------------------------------------------------------------------------


def test_scheduler_settings_defaults_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SCHEDULER_ENABLED", "DAILY_EOD_HOUR", "DAILY_EOD_MINUTE", "SCHEDULER_MISFIRE_GRACE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    settings = make_settings()

    assert settings.SCHEDULER_ENABLED is False
    assert (settings.DAILY_EOD_HOUR, settings.DAILY_EOD_MINUTE) == (16, 30)
    assert settings.SCHEDULER_MISFIRE_GRACE_SECONDS == 3600
    assert start_scheduler(settings) is None


@pytest.mark.parametrize(
    "field,value", [("DAILY_EOD_HOUR", 24), ("DAILY_EOD_HOUR", -1), ("DAILY_EOD_MINUTE", 60), ("SCHEDULER_MISFIRE_GRACE_SECONDS", 0)]
)
def test_scheduler_settings_reject_out_of_range(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_job_config_is_weekday_vn_time_coalesced_single_instance(session_factory) -> None:
    settings = make_settings(SCHEDULER_ENABLED=True)
    scheduler = build_scheduler(settings, session_factory)

    job = scheduler.get_job(DAILY_EOD_SCHEDULER_JOB_ID)
    assert job is not None
    assert job.coalesce is True
    assert job.max_instances == 1
    assert job.misfire_grace_time == 3600
    assert str(scheduler.timezone) == SCHEDULER_TIMEZONE_NAME == "Asia/Ho_Chi_Minh"
    assert str(job.trigger.timezone) == "Asia/Ho_Chi_Minh"

    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["day_of_week"] == "mon-fri"
    assert fields["hour"] == "16"
    assert fields["minute"] == "30"

    assert job.func is run_scheduled_daily_eod
    factory_arg, payload_arg = job.args
    assert factory_arg is session_factory
    assert payload_arg == build_safe_daily_payload(settings)


def test_trigger_fire_times_skip_weekend_without_real_clock(session_factory) -> None:
    trigger = build_scheduler(make_settings(), session_factory).get_job(DAILY_EOD_SCHEDULER_JOB_ID).trigger

    monday_morning = datetime(2026, 11, 16, 10, 0, tzinfo=MARKET_TZ)
    assert trigger.get_next_fire_time(None, monday_morning) == datetime(2026, 11, 16, 16, 30, tzinfo=MARKET_TZ)

    friday_evening = datetime(2026, 11, 20, 17, 0, tzinfo=MARKET_TZ)
    assert trigger.get_next_fire_time(None, friday_evening) == datetime(2026, 11, 23, 16, 30, tzinfo=MARKET_TZ)

    saturday = datetime(2026, 11, 21, 9, 0, tzinfo=MARKET_TZ)
    assert trigger.get_next_fire_time(None, saturday).date() == datetime(2026, 11, 23).date()


def test_job_config_honours_custom_hour_minute_and_grace(session_factory) -> None:
    settings = make_settings(DAILY_EOD_HOUR=18, DAILY_EOD_MINUTE=5, SCHEDULER_MISFIRE_GRACE_SECONDS=120)
    job = build_scheduler(settings, session_factory).get_job(DAILY_EOD_SCHEDULER_JOB_ID)

    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("18", "5")
    assert job.misfire_grace_time == 120


@pytest.mark.parametrize("ai_enabled", [False, True])
def test_safe_payload_never_imports_sample_data(ai_enabled: bool) -> None:
    payload = build_safe_daily_payload(make_settings(AI_ENABLED=ai_enabled))

    assert payload.import_sample_csv_if_empty is False
    assert payload.as_of_date is None
    assert payload.create_proposals is True
    assert payload.run_ai_analysis is ai_enabled


def test_scheduler_module_has_no_approval_or_order_path() -> None:
    """Scheduler không được import module đặt/duyệt lệnh, rủi ro hay danh mục; chỉ đi qua SystemWorkflowService."""
    tree = ast.parse(Path(scheduler_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    forbidden = ("app.trading", "app.risk", "app.portfolio", "app.ai")
    assert not [name for name in imported if name.startswith(forbidden)]
    source = Path(scheduler_module.__file__).read_text(encoding="utf-8").lower()
    for token in ("approve_proposal", "paperbroker", "simulate_fill", "execute_fill"):
        assert token not in source


# --------------------------------------------------------------------------------------
# Vòng đời
# --------------------------------------------------------------------------------------


def test_shutdown_scheduler_is_noop_for_none_or_stopped(session_factory) -> None:
    shutdown_scheduler(None)
    never_started = build_scheduler(make_settings(), session_factory)
    shutdown_scheduler(never_started)
    assert never_started.running is False


def test_lifespan_leaves_scheduler_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module.settings, "SCHEDULER_ENABLED", False)
    application = main_module.create_app()

    with TestClient(application):
        assert application.state.scheduler is None


def test_lifespan_starts_and_stops_scheduler_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module.settings, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "run_scheduled_daily_eod", lambda *_args: None)
    application = main_module.create_app()

    with TestClient(application):
        scheduler = application.state.scheduler
        assert scheduler is not None and scheduler.running
        job = scheduler.get_job(DAILY_EOD_SCHEDULER_JOB_ID)
        assert job is not None and job.next_run_time is not None
        assert job.next_run_time.tzinfo is not None

    assert scheduler.running is False
    assert application.state.scheduler is None


def test_started_scheduler_invokes_job_with_session_factory_and_safe_payload(
    monkeypatch: pytest.MonkeyPatch, session_factory
) -> None:
    """Kích hoạt job bằng next_run_time giả (không chờ 16:30 thật) để kiểm tra APScheduler gọi đúng hàm/đối số."""
    called = threading.Event()
    received: list = []

    def fake_job(factory, payload) -> None:
        received.extend([factory, payload])
        called.set()

    monkeypatch.setattr(scheduler_module, "run_scheduled_daily_eod", fake_job)
    settings = make_settings(SCHEDULER_ENABLED=True)
    scheduler = start_scheduler(settings, session_factory)
    assert scheduler is not None
    try:
        job = scheduler.get_job(DAILY_EOD_SCHEDULER_JOB_ID)
        job.modify(next_run_time=datetime.now(MARKET_TZ))
        scheduler.wakeup()
        assert called.wait(timeout=10), "APScheduler không gọi job trong thời gian chờ"
    finally:
        shutdown_scheduler(scheduler)

    assert received[0] is session_factory
    assert received[1].import_sample_csv_if_empty is False
    assert scheduler.running is False


# --------------------------------------------------------------------------------------
# Thực thi job
# --------------------------------------------------------------------------------------


def test_successful_run_stops_at_pending_approval(seeded_factory) -> None:
    correlation_before = correlation_id_ctx.get()
    with seeded_factory() as session:
        prices_before = _count(session, DailyPrice)

    result = run_scheduled_daily_eod(seeded_factory, build_safe_daily_payload(make_settings()))

    assert result is not None and result.status == "COMPLETED"
    assert result.imported_rows == 0
    assert result.ai_reports_created == 0
    assert result.proposals_created >= 1

    with seeded_factory() as session:
        assert _count(session, DailyPrice) == prices_before
        jobs = session.scalars(select(JobRun)).all()
        assert len(jobs) == 1
        assert jobs[0].id == result.job_run_id and jobs[0].status == "COMPLETED"

        proposals = session.scalars(select(TradeProposal)).all()
        assert proposals and {p.status for p in proposals} == {"PendingApproval"}
        assert _count(session, Approval) == 0
        assert _count(session, Order) == 0
        assert _count(session, Execution) == 0

        actors = {a.actor for a in session.scalars(select(AuditLog)).all() if a.action == "PROPOSAL_CREATED"}
        assert actors == {SCHEDULER_ACTOR}
    assert correlation_id_ctx.get() == correlation_before


def test_failure_before_any_commit_records_single_failed_job_and_rolls_back(
    seeded_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self, *args, **kwargs):
        raise RuntimeError("lỗi giả lập khi tính chỉ báo")

    monkeypatch.setattr(IndicatorService, "calculate_and_persist", boom)
    correlation_before = correlation_id_ctx.get()

    with capture_logs() as logs:
        result = run_scheduled_daily_eod(seeded_factory, build_safe_daily_payload(make_settings()))

    assert result is None
    with seeded_factory() as session:
        jobs = session.scalars(select(JobRun)).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.job_name == "DAILY_EOD_WORKFLOW"
        assert job.status == "FAILED"
        assert job.completed_at is not None
        assert job.error_detail["error_type"] == "RuntimeError"
        assert "lỗi giả lập" in job.error_detail["error_message"]
        assert _count(session, TradeProposal) == 0
        failed_audit = [a for a in session.scalars(select(AuditLog)).all() if a.action == "DAILY_EOD_WORKFLOW_FAILED"]
        assert len(failed_audit) == 1 and failed_audit[0].entity_id == str(job.id)

    failed_events = [entry for entry in logs if entry["event"] == "scheduler_daily_eod_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["log_level"] == "error"
    assert failed_events[0]["error_type"] == "RuntimeError"
    assert failed_events[0]["job_run_id"] == str(job.id)
    assert correlation_id_ctx.get() == correlation_before


def test_failure_after_running_row_committed_updates_it_instead_of_duplicating(
    seeded_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bước chỉ báo tự commit (kéo theo bản ghi RUNNING); lỗi ở bước scanner phải chuyển chính bản ghi đó sang FAILED."""

    def boom(self, *args, **kwargs):
        raise RuntimeError("scanner hỏng")

    monkeypatch.setattr(ScannerService, "run_scanner", boom)

    result = run_scheduled_daily_eod(seeded_factory, build_safe_daily_payload(make_settings()))

    assert result is None
    with seeded_factory() as session:
        jobs = session.scalars(select(JobRun)).all()
        assert len(jobs) == 1
        assert jobs[0].status == "FAILED"
        assert jobs[0].error_detail["error_type"] == "RuntimeError"
        assert jobs[0].started_at is not None
        assert _count(session, Order) == 0 and _count(session, Execution) == 0


def test_failure_recording_error_is_logged_not_raised(
    seeded_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self, *args, **kwargs):
        raise RuntimeError("workflow hỏng")

    def record_boom(self, *args, **kwargs):
        raise ConnectionError("mất kết nối khi ghi JobRun")

    monkeypatch.setattr(IndicatorService, "calculate_and_persist", boom)
    monkeypatch.setattr(SystemWorkflowService, "record_daily_eod_failure", record_boom)

    with capture_logs() as logs:
        result = run_scheduled_daily_eod(seeded_factory, build_safe_daily_payload(make_settings()))

    assert result is None
    events = {entry["event"]: entry for entry in logs}
    assert events["scheduler_daily_eod_failed"]["log_level"] == "error"
    assert events["scheduler_daily_eod_failure_not_recorded"]["log_level"] == "critical"
    assert events["scheduler_daily_eod_failure_not_recorded"]["error_type"] == "ConnectionError"


def test_record_failure_never_overwrites_completed_job(session_factory) -> None:
    with session_factory() as session:
        service = SystemWorkflowService(session)
        session.add(JobRun(job_name="DAILY_EOD_WORKFLOW", status="COMPLETED", records_processed=3))
        session.commit()
        job_id = session.scalar(select(JobRun.id))

        job = service.record_daily_eod_failure(
            job_run_id=job_id, started_at=datetime.now(MARKET_TZ), error=RuntimeError("muộn")
        )

        assert job.status == "COMPLETED"
        assert _count(session, JobRun) == 1
        assert _count(session, AuditLog) == 0
