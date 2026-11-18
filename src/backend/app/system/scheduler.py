# Ngày tạo: 2026-11-17
# Mục đích: Lập lịch chạy tự động Daily EOD Workflow (APScheduler) tích hợp vào FastAPI lifespan.
# Lý do an toàn:
#   - Job chỉ gọi `SystemWorkflowService.run_daily_eod_workflow` với payload cố định; workflow dừng ở
#     `TradeProposal(PendingApproval)`. Module này không import/gọi approve, Paper Broker hay bất kỳ đường tạo Order/Execution nào.
#   - Không import dữ liệu mẫu (`SAMPLE`) vào hệ thống đang chạy thật; AI chỉ chạy khi `AI_ENABLED=true` tường minh.
#   - Múi giờ cố định Asia/Ho_Chi_Minh, thứ 2-6, coalesce + max_instances=1 để không chạy chồng/chạy bù hàng loạt.
#   - Mỗi lần chạy dùng một Session riêng; lỗi được rollback, ghi `JobRun FAILED` + log có cấu trúc, không nuốt lỗi im lặng.

import uuid
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import structlog
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobEvent,
)
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from structlog.typing import FilteringBoundLogger

from app.core import clock
from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.logging import correlation_id_ctx
from app.schemas.system import DailyWorkflowRunRequest, DailyWorkflowRunResponse
from app.system.service import DAILY_EOD_JOB_NAME, MAX_ERROR_MESSAGE_LENGTH, SystemWorkflowService

logger = structlog.get_logger(__name__)

# Cố định theo quy tắc dự án (ngày giao dịch theo giờ thị trường Việt Nam); không cấu hình qua biến môi trường.
SCHEDULER_TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
DAILY_EOD_DAYS_OF_WEEK = "mon-fri"
DAILY_EOD_SCHEDULER_JOB_ID = "daily_eod_workflow"
SCHEDULER_ACTOR = "daily_eod_scheduler"

SessionFactory = Callable[[], Session]


def build_safe_daily_payload(settings: Settings) -> DailyWorkflowRunRequest:
    """
    Payload cố định cho lần chạy tự động.
    - `import_sample_csv_if_empty=False`: không bao giờ tự nạp dữ liệu SAMPLE rồi sinh đề xuất từ đó.
    - `run_ai_analysis` chỉ bật khi AI được cấu hình bật tường minh (tránh gọi LLM ngoài ý muốn).
    - `create_proposals=True`: chỉ tạo `PendingApproval`; việc duyệt luôn do con người thực hiện.
    """
    return DailyWorkflowRunRequest(
        import_sample_csv_if_empty=False,
        as_of_date=None,
        run_ai_analysis=settings.AI_ENABLED,
        create_proposals=True,
    )


def _persist_failure(
    session: Session,
    job_run_id: uuid.UUID,
    started_at: datetime,
    error: Exception,
    log: FilteringBoundLogger,
) -> None:
    """Rollback giao dịch dang dở rồi ghi JobRun FAILED; nếu chính việc ghi này lỗi thì log mức critical."""
    try:
        session.rollback()
        SystemWorkflowService(session).record_daily_eod_failure(
            job_run_id=job_run_id,
            started_at=started_at,
            error=error,
            actor=SCHEDULER_ACTOR,
        )
    except Exception as record_error:
        session.rollback()
        log.critical(
            "scheduler_daily_eod_failure_not_recorded",
            error_type=type(record_error).__name__,
            error_message=str(record_error)[:MAX_ERROR_MESSAGE_LENGTH],
            exc_info=True,
        )


def run_scheduled_daily_eod(
    session_factory: SessionFactory, payload: DailyWorkflowRunRequest
) -> Optional[DailyWorkflowRunResponse]:
    """
    Thân job: mỗi lần chạy mở Session riêng (không dùng chung với request HTTP hay lần chạy trước).
    Trả về kết quả khi thành công, `None` khi thất bại (lỗi đã được rollback + ghi JobRun FAILED + log).
    """
    job_run_id = uuid.uuid4()
    started_at = clock.utc_now()
    # Thread pool tái sử dụng thread nên phải reset correlation_id để không rò sang lần chạy sau.
    token = correlation_id_ctx.set(f"scheduler-{job_run_id}")
    log = logger.bind(job_name=DAILY_EOD_JOB_NAME, job_run_id=str(job_run_id))
    session = session_factory()
    try:
        log.info("scheduler_daily_eod_started", payload=payload.model_dump(mode="json"))
        result = SystemWorkflowService(session).run_daily_eod_workflow(
            payload=payload, actor=SCHEDULER_ACTOR, job_run_id=job_run_id
        )
        log.info(
            "scheduler_daily_eod_completed",
            as_of_date=result.as_of_date.isoformat() if result.as_of_date else None,
            signals_generated=result.signals_generated,
            proposals_created=result.proposals_created,
            proposals_blocked_or_skipped=result.proposals_blocked_or_skipped,
        )
        return result
    except Exception as exc:
        log.error(
            "scheduler_daily_eod_failed",
            error_type=type(exc).__name__,
            error_message=str(exc)[:MAX_ERROR_MESSAGE_LENGTH],
            exc_info=True,
        )
        _persist_failure(session, job_run_id, started_at, exc, log)
        return None
    finally:
        session.close()
        correlation_id_ctx.reset(token)


def _log_scheduler_event(event: JobEvent) -> None:
    """Ghi log có cấu trúc cho các sự kiện lịch bất thường (bỏ lỡ lần chạy, trùng lịch, lỗi ngoài thân job)."""
    if event.code == EVENT_JOB_MISSED:
        logger.warning(
            "scheduler_job_missed",
            job_id=event.job_id,
            scheduled_run_time=event.scheduled_run_time.isoformat(),
        )
    elif event.code == EVENT_JOB_MAX_INSTANCES:
        logger.warning("scheduler_job_skipped_still_running", job_id=event.job_id)
    elif event.code == EVENT_JOB_ERROR:
        logger.error(
            "scheduler_job_error",
            job_id=event.job_id,
            error_type=type(event.exception).__name__ if event.exception else None,
            error_message=str(event.exception)[:MAX_ERROR_MESSAGE_LENGTH] if event.exception else None,
        )


def build_scheduler(
    settings: Settings, session_factory: Optional[SessionFactory] = None
) -> BackgroundScheduler:
    """
    Dựng (chưa start) scheduler với một job Daily EOD: 16:30 (mặc định) thứ 2-6 giờ Asia/Ho_Chi_Minh.
    - `coalesce=True`: nhiều lần chạy bị lỡ gộp thành một lần.
    - `max_instances=1` + executor 1 thread: không bao giờ có hai workflow EOD chạy chồng nhau trong một process.
    - `misfire_grace_time`: lần chạy trễ hơn ngưỡng này (vd. backend tắt qua giờ chạy) bị bỏ qua thay vì chạy bù muộn.
    """
    timezone = ZoneInfo(SCHEDULER_TIMEZONE_NAME)
    misfire_grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS
    scheduler = BackgroundScheduler(
        timezone=timezone,
        jobstores={"default": MemoryJobStore()},
        executors={"default": ThreadPoolExecutor(max_workers=1)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": misfire_grace},
    )
    scheduler.add_job(
        run_scheduled_daily_eod,
        trigger=CronTrigger(
            day_of_week=DAILY_EOD_DAYS_OF_WEEK,
            hour=settings.DAILY_EOD_HOUR,
            minute=settings.DAILY_EOD_MINUTE,
            timezone=timezone,
        ),
        args=[session_factory or SessionLocal, build_safe_daily_payload(settings)],
        id=DAILY_EOD_SCHEDULER_JOB_ID,
        name="Daily EOD workflow (dừng ở PendingApproval)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=misfire_grace,
    )
    scheduler.add_listener(
        _log_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES
    )
    return scheduler


def start_scheduler(
    settings: Settings, session_factory: Optional[SessionFactory] = None
) -> Optional[BackgroundScheduler]:
    """Khởi động scheduler nếu `SCHEDULER_ENABLED=true`; ngược lại trả về None (mặc định cho dev/test)."""
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler_disabled")
        return None
    scheduler = build_scheduler(settings, session_factory)
    scheduler.start()
    job = scheduler.get_job(DAILY_EOD_SCHEDULER_JOB_ID)
    logger.info(
        "scheduler_started",
        job_id=DAILY_EOD_SCHEDULER_JOB_ID,
        days_of_week=DAILY_EOD_DAYS_OF_WEEK,
        hour=settings.DAILY_EOD_HOUR,
        minute=settings.DAILY_EOD_MINUTE,
        timezone=SCHEDULER_TIMEZONE_NAME,
        misfire_grace_seconds=settings.SCHEDULER_MISFIRE_GRACE_SECONDS,
        next_run_time=job.next_run_time.isoformat() if job and job.next_run_time else None,
    )
    return scheduler


def shutdown_scheduler(scheduler: Optional[BackgroundScheduler]) -> None:
    """Tắt scheduler: không nhận lần chạy mới và chờ job đang chạy (nếu có) kết thúc để không bỏ dở JobRun."""
    if scheduler is None or not scheduler.running:
        return
    scheduler.shutdown(wait=True)
    logger.info("scheduler_stopped")
