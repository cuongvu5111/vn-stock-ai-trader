# Ngày tạo: 2026-11-03
# Mục đích: Điều phối chuỗi công việc EOD hàng ngày (Daily Workflow - Mục 13) và quản lý lịch sử `system.job_runs`.
# Lý do:
#   - Đảm bảo tính idempotent khi chạy lại cùng ngày.
#   - Tự động dừng ở bước tạo `TradeProposal(status='PendingApproval')` chờ con người phê duyệt, tuyệt đối không auto-approve.

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.service import AiAnalysisService
from app.indicators.service import IndicatorService
from app.market_data.models import DailyPrice
from app.market_data.service import MarketDataService
from app.portfolio.service import PortfolioService
from app.risk.service import record_audit_log
from app.schemas.ai import AiAnalyzeRequest
from app.schemas.strategy import ScannerRunRequest
from app.schemas.system import (
    DailyWorkflowRunRequest,
    DailyWorkflowRunResponse,
    JobRunItemResponse,
    JobRunListResponse,
)
from app.schemas.trading import ProposalCreateRequest
from app.screening.service import ScannerService
from app.system.models import JobRun
from app.trading.service import TradingWorkflowService

DAILY_EOD_JOB_NAME = "DAILY_EOD_WORKFLOW"
MAX_ERROR_MESSAGE_LENGTH = 500


def _find_sample_csv_path() -> Path | None:
    """Tìm đường dẫn tới file `database/seeds/sample_ohlcv_data.csv`."""
    candidates = [
        Path("database/seeds/sample_ohlcv_data.csv"),
        Path(__file__).resolve().parents[4] / "database" / "seeds" / "sample_ohlcv_data.csv",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


class SystemWorkflowService:
    """Service quản lý lịch sử JobRun và thực thi chuỗi công việc EOD hàng ngày."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_job_runs(self, limit: int = 30) -> JobRunListResponse:
        rows = self.session.scalars(
            select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        ).all()
        return JobRunListResponse(
            total=len(rows),
            items=[JobRunItemResponse.model_validate(r) for r in rows],
        )

    def run_daily_eod_workflow(
        self,
        payload: DailyWorkflowRunRequest,
        actor: str = "daily_eod_scheduler",
        job_run_id: Optional[uuid.UUID] = None,
    ) -> DailyWorkflowRunResponse:
        """
        Thực thi quy trình EOD hàng ngày theo đúng thứ tự Mục 13:
        1. Import dữ liệu mẫu CSV nếu DB đang trống và `import_sample_csv_if_empty=True`.
        2. Tính toán bộ chỉ báo kỹ thuật (`IndicatorService.calculate_and_persist`).
        3. Quét cổ phiếu và sinh tín hiệu cho cả 2 chiến lược (`TREND_FOLLOWING` & `PULLBACK`).
        4. Phân tích AI giải thích cho các tín hiệu `BUY`/`SELL` (`AiAnalysisService`).
        5. Đánh giá rủi ro và tạo `TradeProposal` ở trạng thái `PendingApproval` (`TradingWorkflowService`).
        6. Chốt bản chụp NAV cuối ngày (`PortfolioService.create_or_update_daily_snapshot`).

        `job_run_id` cho phép bên gọi (scheduler) biết trước khóa của JobRun để khi workflow lỗi giữa chừng
        vẫn cập nhật đúng bản ghi `RUNNING` (nếu đã bị commit bởi các bước con) thay vì tạo thêm bản ghi lỗi trùng.
        """
        started_at = datetime.now(timezone.utc)
        job = JobRun(
            job_name=DAILY_EOD_JOB_NAME,
            started_at=started_at,
            status="RUNNING",
            records_processed=0,
        )
        if job_run_id is not None:
            job.id = job_run_id
        self.session.add(job)
        self.session.flush()

        steps_summary: List[str] = []
        imported_rows = 0

        market_svc = MarketDataService(session=self.session)
        total_prices = int(self.session.scalar(select(func.count()).select_from(DailyPrice)) or 0)

        if total_prices == 0 and payload.import_sample_csv_if_empty:
            sample_path = _find_sample_csv_path()
            if sample_path is not None:
                csv_text = sample_path.read_text(encoding="utf-8")
                batch_res = market_svc.import_csv_content(
                    csv_text=csv_text,
                    file_name=sample_path.name,
                    source_name="SAMPLE_CSV_SEED",
                    is_sample=True,
                )
                imported_rows = int(batch_res.rows_inserted or 0)
                steps_summary.append(
                    f"1. Đã tự động import dữ liệu mẫu ({sample_path.name}): {imported_rows} dòng OHLCV."
                )

        # Bước 2: Tính toán chỉ báo kỹ thuật
        ind_svc = IndicatorService(session=self.session)
        ind_res = ind_svc.calculate_and_persist(as_of_date=payload.as_of_date)
        resolved_date = ind_res.data_as_of or payload.as_of_date
        steps_summary.append(
            f"2. Tính toán chỉ báo kỹ thuật hoàn tất cho {ind_res.symbols_processed} mã ({ind_res.rows_upserted} bản ghi)."
        )

        # Bước 3: Quét cổ phiếu theo cả 2 chiến lược
        scanner_svc = ScannerService(session=self.session)
        tf_res = scanner_svc.run_scanner(
            ScannerRunRequest(
                strategy_type="TREND_FOLLOWING",
                as_of_date=resolved_date,
                only_actionable=True,
            )
        )
        pb_res = scanner_svc.run_scanner(
            ScannerRunRequest(
                strategy_type="PULLBACK",
                as_of_date=resolved_date,
                only_actionable=True,
            )
        )
        actionable_signals = [*tf_res.signals, *pb_res.signals]
        steps_summary.append(
            f"3. Quét chiến lược hoàn tất: phát hiện {len(actionable_signals)} tín hiệu hành động (BUY/SELL)."
        )

        # Bước 4: Phân tích AI cho các tín hiệu hành động (tối đa 4 mã điểm cao nhất trong batch để phản hồi nhanh)
        ai_reports_created = 0
        if payload.run_ai_analysis and actionable_signals:
            ai_svc = AiAnalysisService(session=self.session, max_retries=1)
            seen_symbols: set[str] = set()
            prioritized_signals = []
            for sig in actionable_signals:
                if sig.symbol not in seen_symbols:
                    seen_symbols.add(sig.symbol)
                    prioritized_signals.append(sig)
            for sig in prioritized_signals[:2]:
                try:
                    ai_svc.analyze_and_persist(
                        AiAnalyzeRequest(signal_id=sig.id, allow_mock_when_disabled=True)
                    )
                    ai_reports_created += 1
                except Exception:
                    continue
            steps_summary.append(f"4. Đã sinh {ai_reports_created} báo cáo giải thích AI có trích dẫn nguồn.")
        else:
            steps_summary.append("4. Bỏ qua bước phân tích AI hoặc không có tín hiệu mới.")

        # Bước 5: Tạo TradeProposal (dừng ở PendingApproval chờ người dùng duyệt)
        proposals_created = 0
        proposals_blocked = 0
        if payload.create_proposals and actionable_signals:
            trading_svc = TradingWorkflowService(session=self.session)
            for sig in actionable_signals:
                try:
                    trading_svc.create_proposal_from_signal(
                        ProposalCreateRequest(signal_id=sig.id, expiry_minutes=240),
                        actor=actor,
                    )
                    proposals_created += 1
                except HTTPException:
                    proposals_blocked += 1
            steps_summary.append(
                f"5. Đánh giá Risk & tạo Proposal: {proposals_created} đề xuất chờ duyệt (PendingApproval), "
                f"{proposals_blocked} đề xuất bị chặn bởi Risk Engine."
            )
        else:
            steps_summary.append("5. Không tạo đề xuất giao dịch mới.")

        # Bước 6: Chốt Daily Snapshot cho danh mục Paper
        portfolio_svc = PortfolioService(session=self.session)
        snap = portfolio_svc.create_or_update_daily_snapshot(snapshot_date=resolved_date)
        steps_summary.append(f"6. Đã chốt Daily Snapshot (NAV = {snap.nav} VND).")

        completed_at = datetime.now(timezone.utc)
        job.completed_at = completed_at
        job.status = "COMPLETED"
        job.records_processed = ind_res.rows_upserted + len(actionable_signals) + proposals_created
        job.error_detail = {"steps_summary": steps_summary}

        record_audit_log(
            session=self.session,
            actor=actor,
            action="DAILY_EOD_WORKFLOW_COMPLETED",
            entity_type="JobRun",
            entity_id=str(job.id),
            before_state=None,
            after_state={
                "as_of_date": resolved_date.isoformat() if resolved_date else None,
                "signals_generated": len(actionable_signals),
                "proposals_created": proposals_created,
                "snapshot_nav": str(snap.nav),
            },
        )
        self.session.commit()
        self.session.refresh(job)

        return DailyWorkflowRunResponse(
            job_run_id=job.id,
            status="COMPLETED",
            as_of_date=resolved_date,
            imported_rows=imported_rows,
            indicators_upserted=ind_res.rows_upserted,
            signals_generated=len(actionable_signals),
            ai_reports_created=ai_reports_created,
            proposals_created=proposals_created,
            proposals_blocked_or_skipped=proposals_blocked,
            snapshot_nav=str(snap.nav),
            steps_summary=steps_summary,
            started_at=started_at,
            completed_at=completed_at,
        )

    def record_daily_eod_failure(
        self,
        job_run_id: uuid.UUID,
        started_at: datetime,
        error: BaseException,
        actor: str = "daily_eod_scheduler",
    ) -> JobRun:
        """
        Ghi nhận workflow EOD thất bại; chỉ gọi sau khi session đã `rollback()`.
        - Các bước con (import/chỉ báo/scanner/proposal) tự commit nên bản ghi `RUNNING` có thể đã nằm trong DB:
          khi đó cập nhật chính bản ghi đó sang `FAILED` để không sinh JobRun lỗi trùng.
        - Nếu bản ghi chưa từng được commit (đã bị rollback) thì tạo mới `FAILED` với đúng `job_run_id`.
        - Nếu bản ghi đã `COMPLETED` (lỗi chỉ xảy ra sau commit cuối) thì giữ nguyên, không ghi đè kết quả thành công.
        """
        job = self.session.scalar(select(JobRun).where(JobRun.id == job_run_id).with_for_update())
        if job is not None and job.status == "COMPLETED":
            return job

        failed_at = datetime.now(timezone.utc)
        error_detail = {
            "error_type": type(error).__name__,
            "error_message": str(error)[:MAX_ERROR_MESSAGE_LENGTH],
            "failed_at_utc": failed_at.isoformat(),
            "note": (
                "Các bước đã commit trước khi lỗi được giữ nguyên; workflow không bao giờ duyệt "
                "hay khớp lệnh nên không có Order/Execution nào được tạo."
            ),
        }
        if job is None:
            job = JobRun(
                id=job_run_id,
                job_name=DAILY_EOD_JOB_NAME,
                started_at=started_at,
                records_processed=0,
            )
            self.session.add(job)
        job.status = "FAILED"
        job.completed_at = failed_at
        job.error_detail = error_detail

        record_audit_log(
            session=self.session,
            actor=actor,
            action="DAILY_EOD_WORKFLOW_FAILED",
            entity_type="JobRun",
            entity_id=str(job_run_id),
            before_state=None,
            after_state={"error_type": error_detail["error_type"]},
        )
        self.session.commit()
        return job
