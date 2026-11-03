# Ngày tạo: 2026-11-03
# Mục đích: Điều phối phân tích AI có kiểm tra schema JSON, xác thực nguồn trích dẫn, giới hạn retry và lưu vào `analysis.ai_reports`.
# Lý do:
#   - Đảm bảo không có bất kỳ output sai schema hoặc bịa nguồn nào được lưu như một report thành công (`COMPLETED`).
#   - Hoàn toàn cô lập với `trading`, `risk`, `portfolio` (chỉ đọc từ `market` và `analysis`).

import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Set

import structlog
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompting import PROMPT_VERSION, sanitize_untrusted_text
from app.ai.providers import ConfigurableHttpLlmProvider, MockAiAnalysisProvider
from app.core.config import get_settings
from app.core.protocols import AiAnalysisProvider
from app.indicators.models import AiReport, StockSignal
from app.market_data.models import Stock
from app.schemas.ai import (
    AiAnalyzeRequest,
    AiReportListResponse,
    AiReportResponse,
    AiStructuredReportPayload,
)

logger = structlog.get_logger(__name__)


class AiAnalysisService:
    """Service điều phối lớp giải thích AI (Explainable AI Layer)."""

    def __init__(
        self,
        session: Session,
        provider_override: Optional[AiAnalysisProvider] = None,
        max_retries: int = 2,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.max_retries = max(1, max_retries)
        self._provider_override = provider_override

    def _resolve_provider(self) -> AiAnalysisProvider:
        if self._provider_override is not None:
            return self._provider_override

        provider_type = self.settings.AI_PROVIDER.strip().lower()
        if provider_type in ("", "mock"):
            return MockAiAnalysisProvider(model_name=self.settings.resolved_llm_model)

        return ConfigurableHttpLlmProvider(
            provider_name=provider_type,
            model_name=self.settings.resolved_llm_model,
            api_key=self.settings.resolved_llm_api_key,
            endpoint_url=self.settings.resolved_llm_url,
        )

    def _resolve_signal_and_stock(self, payload: AiAnalyzeRequest) -> tuple[StockSignal, Stock]:
        if payload.signal_id is not None:
            signal = self.session.get(StockSignal, payload.signal_id)
            if not signal:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Không tìm thấy tín hiệu với ID '{payload.signal_id}'.",
                )
            stock = self.session.get(Stock, signal.stock_id)
            if not stock:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Không tìm thấy mã cổ phiếu tương ứng với tín hiệu.",
                )
            return signal, stock

        if payload.symbol:
            norm_sym = payload.symbol.strip().upper()
            stock = self.session.scalar(select(Stock).where(Stock.symbol == norm_sym))
            if not stock:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Không tìm thấy mã cổ phiếu '{norm_sym}'.",
                )
            signal = self.session.scalar(
                select(StockSignal)
                .where(StockSignal.stock_id == stock.id)
                .order_by(StockSignal.trading_date.desc(), StockSignal.created_at.desc())
            )
            if not signal:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Mã cổ phiếu '{norm_sym}' chưa có tín hiệu nào trong analysis.stock_signals.",
                )
            return signal, stock

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phải cung cấp `signal_id` hoặc `symbol` để chạy phân tích AI.",
        )

    def analyze_and_persist(self, payload: AiAnalyzeRequest) -> AiReportResponse:
        """
        Thực hiện phân tích AI cho một tín hiệu:
        1. Nếu AI bị tắt (`AI_ENABLED=False` và `allow_mock_when_disabled=False`) -> lưu bản ghi `SKIPPED_AI_DISABLED`.
        2. Làm sạch dữ liệu tin tức bên ngoài (chống Prompt Injection) và đóng gói `input_snapshot`.
        3. Gọi AI Provider với cơ chế retry giới hạn (`max_retries`).
        4. Kiểm tra nghiêm ngặt schema JSON (`extra="forbid"`) và xác thực mọi `source_id` trích dẫn.
        5. Lưu kết quả vào `analysis.ai_reports`.
        """
        signal, stock = self._resolve_signal_and_stock(payload)
        signal_reason = signal.reason or {}
        as_of_date = date.fromisoformat(
            signal_reason.get("data_as_of", signal.trading_date.isoformat())
        )

        # Kiểm tra nếu AI bị tắt trong cấu hình
        if not self.settings.AI_ENABLED and not payload.allow_mock_when_disabled and self._provider_override is None:
            skipped_report = AiReport(
                stock_id=stock.id,
                signal_id=signal.id,
                provider="disabled",
                model="none",
                prompt_version=PROMPT_VERSION,
                input_snapshot={"symbol": stock.symbol, "signal_id": str(signal.id), "ai_enabled": False},
                report=None,
                source_references={"note": "AI_DISABLED_BY_CONFIGURATION"},
                status="SKIPPED_AI_DISABLED",
            )
            self.session.add(skipped_report)
            self.session.commit()
            self.session.refresh(skipped_report)
            return AiReportResponse(
                id=skipped_report.id,
                stock_id=stock.id,
                symbol=stock.symbol,
                signal_id=signal.id,
                provider=skipped_report.provider,
                model=skipped_report.model,
                prompt_version=skipped_report.prompt_version,
                status=skipped_report.status or "SKIPPED_AI_DISABLED",
                input_snapshot=skipped_report.input_snapshot,
                report=None,
                source_references=skipped_report.source_references,
                created_at=skipped_report.created_at,
            )

        provider = self._resolve_provider()
        primary_signal_source_id = f"SIGNAL_{signal.id}"
        allowed_source_ids: Set[str] = {primary_signal_source_id}

        sanitized_news: List[Dict[str, Any]] = []
        security_warnings: List[str] = []

        for article in payload.news_articles:
            clean_title, w_title = sanitize_untrusted_text(article.title)
            clean_summary, w_sum = sanitize_untrusted_text(article.content_summary)
            security_warnings.extend(w_title)
            security_warnings.extend(w_sum)
            allowed_source_ids.add(article.source_id)
            sanitized_news.append(
                {
                    "source_id": article.source_id,
                    "title": clean_title,
                    "published_date": article.published_date.isoformat(),
                    "publisher": article.publisher,
                    "content_summary": clean_summary,
                }
            )

        fin_snapshot: Optional[Dict[str, Any]] = None
        if payload.financial_metrics is not None:
            allowed_source_ids.add(payload.financial_metrics.source_id)
            fin_snapshot = payload.financial_metrics.model_dump(mode="json")

        input_snapshot: Dict[str, Any] = {
            "symbol": stock.symbol,
            "data_as_of": as_of_date.isoformat(),
            "allowed_source_ids": sorted(allowed_source_ids),
            "signal": {
                "source_id": primary_signal_source_id,
                "signal_id": str(signal.id),
                "trading_date": signal.trading_date.isoformat(),
                "action": signal.action,
                "score": str(signal.score) if signal.score is not None else None,
                "reference_price": str(signal.reference_price) if signal.reference_price is not None else None,
                "stop_loss": str(signal.stop_loss) if signal.stop_loss is not None else None,
                "reasons": signal_reason.get("reasons", []),
                "warnings": signal_reason.get("warnings", []),
                "indicators_snapshot": signal_reason.get("indicators_snapshot", {}),
            },
            "financial_metrics": fin_snapshot,
            "news_articles": sanitized_news,
            "security_warnings": security_warnings,
        }

        validated_payload: Optional[AiStructuredReportPayload] = None
        last_error_msg: str = ""
        final_status: str = "FAILED_VALIDATION"

        for attempt in range(1, self.max_retries + 1):
            try:
                raw_output = provider.analyze_signal(
                    symbol=stock.symbol,
                    as_of_date=as_of_date,
                    input_snapshot=input_snapshot,
                )
                candidate = AiStructuredReportPayload.model_validate(raw_output)
                candidate.verify_source_references(allowed_source_ids)
                validated_payload = candidate
                final_status = "COMPLETED"
                break
            except (ValidationError, ValueError) as val_err:
                last_error_msg = f"Attempt {attempt}/{self.max_retries} schema/source validation failed: {val_err}"
                final_status = "FAILED_VALIDATION"
                logger.warning(
                    "ai_report_validation_retry",
                    symbol=stock.symbol,
                    attempt=attempt,
                    error=str(val_err),
                )
            except Exception as prov_err:
                last_error_msg = f"Attempt {attempt}/{self.max_retries} provider error: {type(prov_err).__name__}: {prov_err}"
                final_status = "FAILED_PROVIDER_ERROR"
                logger.warning(
                    "ai_report_provider_retry",
                    symbol=stock.symbol,
                    attempt=attempt,
                    error_type=type(prov_err).__name__,
                )

        if validated_payload is not None:
            report_json = validated_payload.model_dump(mode="json")
            refs_json = {
                "items": [r.model_dump(mode="json") for r in validated_payload.source_references],
                "security_warnings": security_warnings,
            }
        else:
            # Tuyệt đối không lưu output không hợp lệ như một report thành công
            report_json = None
            refs_json = {
                "error": last_error_msg,
                "security_warnings": security_warnings,
            }

        db_report = AiReport(
            stock_id=stock.id,
            signal_id=signal.id,
            provider=provider.provider_name,
            model=provider.model_name,
            prompt_version=PROMPT_VERSION,
            input_snapshot=input_snapshot,
            report=report_json,
            source_references=refs_json,
            status=final_status,
        )
        self.session.add(db_report)
        self.session.commit()
        self.session.refresh(db_report)

        return AiReportResponse(
            id=db_report.id,
            stock_id=stock.id,
            symbol=stock.symbol,
            signal_id=signal.id,
            provider=db_report.provider,
            model=db_report.model,
            prompt_version=db_report.prompt_version,
            status=db_report.status or final_status,
            input_snapshot=db_report.input_snapshot,
            report=validated_payload,
            source_references=db_report.source_references,
            created_at=db_report.created_at,
        )

    def get_report(self, report_id: uuid.UUID) -> AiReportResponse:
        """Lấy chi tiết một bản ghi báo cáo AI theo ID."""
        row = self.session.get(AiReport, report_id)
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy báo cáo AI với ID '{report_id}'.",
            )
        stock = self.session.get(Stock, row.stock_id) if row.stock_id else None
        parsed_report = (
            AiStructuredReportPayload.model_validate(row.report)
            if row.report and row.status == "COMPLETED"
            else None
        )
        return AiReportResponse(
            id=row.id,
            stock_id=row.stock_id,
            symbol=stock.symbol if stock else None,
            signal_id=row.signal_id,
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            status=row.status or "UNKNOWN",
            input_snapshot=row.input_snapshot,
            report=parsed_report,
            source_references=row.source_references,
            created_at=row.created_at,
        )

    def list_reports(
        self,
        symbol: Optional[str] = None,
        signal_id: Optional[uuid.UUID] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> AiReportListResponse:
        """Liệt kê danh sách các báo cáo AI đã tạo."""
        stmt = select(AiReport, Stock.symbol).outerjoin(Stock, AiReport.stock_id == Stock.id)
        if symbol:
            stmt = stmt.where(Stock.symbol == symbol.strip().upper())
        if signal_id:
            stmt = stmt.where(AiReport.signal_id == signal_id)
        if status_filter:
            stmt = stmt.where(AiReport.status == status_filter.strip().upper())

        rows = self.session.execute(
            stmt.order_by(AiReport.created_at.desc()).limit(limit)
        ).all()

        items: List[AiReportResponse] = []
        for rep, sym in rows:
            parsed = (
                AiStructuredReportPayload.model_validate(rep.report)
                if rep.report and rep.status == "COMPLETED"
                else None
            )
            items.append(
                AiReportResponse(
                    id=rep.id,
                    stock_id=rep.stock_id,
                    symbol=sym,
                    signal_id=rep.signal_id,
                    provider=rep.provider,
                    model=rep.model,
                    prompt_version=rep.prompt_version,
                    status=rep.status or "UNKNOWN",
                    input_snapshot=rep.input_snapshot,
                    report=parsed,
                    source_references=rep.source_references,
                    created_at=rep.created_at,
                )
            )

        return AiReportListResponse(total=len(items), items=items)
