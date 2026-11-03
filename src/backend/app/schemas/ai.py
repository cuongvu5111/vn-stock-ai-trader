# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Pydantic v2 DTOs cho phân hệ AI Analysis (Mục 11 trong Implementation Plan).
# Lý do:
#   - Đảm bảo output JSON từ AI tuân thủ nghiêm ngặt schema (`extra="forbid"`).
#   - Cấm tuyệt đối mọi trường liên quan đến đặt lệnh, khối lượng giao dịch hoặc tự duyệt proposal.

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsArticleInput(BaseModel):
    """Dữ liệu một bài báo/tin tức bên ngoài (được coi là untrusted content)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=100, description="Mã định danh nguồn tin")
    title: str = Field(..., min_length=1, max_length=500)
    published_date: date
    publisher: str = Field(default="UNKNOWN_PUBLISHER", max_length=200)
    content_summary: str = Field(..., min_length=1, max_length=4000)


class FinancialMetricsInput(BaseModel):
    """Các chỉ số tài chính cơ bản có nguồn rõ ràng (tùy chọn)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=100)
    period: str = Field(..., description="Kỳ báo cáo (VD: Q3/2026)")
    pe_ratio: Optional[str] = None
    pb_ratio: Optional[str] = None
    roe_pct: Optional[str] = None
    debt_to_equity: Optional[str] = None


class SourceReferenceItem(BaseModel):
    """Một trích dẫn nguồn cụ thể trong báo cáo AI."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(..., description="SIGNAL | INDICATORS | NEWS | FINANCIAL_METRICS")
    description: str = Field(..., min_length=1, max_length=500)
    as_of_date: date


class AiStructuredReportPayload(BaseModel):
    """
    Schema JSON bắt buộc cho output của AI Analysis (Mục 11).
    Sử dụng `extra="forbid"` để lập tức từ chối nếu LLM sinh thêm các trường trái phép
    như `quantity`, `proposed_quantity`, `place_order`, `approve_proposal`.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=5)
    positive_factors: List[str] = Field(default_factory=list)
    negative_factors: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    conflicting_evidence: List[str] = Field(default_factory=list)
    source_references: List[SourceReferenceItem] = Field(..., min_length=1)
    data_as_of: date
    limitations: List[str] = Field(..., min_length=1)

    @field_validator("summary")
    @classmethod
    def check_forbidden_action_phrases(cls, v: str) -> str:
        lowered = v.lower()
        forbidden = ("auto_approve", "execute_live_order", "bypass_risk_engine")
        for token in forbidden:
            if token in lowered:
                raise ValueError(f"Summary chứa lệnh điều khiển trái phép: {token}")
        return v

    def verify_source_references(self, allowed_source_ids: Set[str]) -> None:
        """Đảm bảo AI không bịa ra nguồn trích dẫn không tồn tại trong input_snapshot."""
        for ref in self.source_references:
            if ref.source_id not in allowed_source_ids:
                raise ValueError(
                    f"AI trích dẫn nguồn không tồn tại trong input_snapshot: '{ref.source_id}'. "
                    f"Các nguồn hợp lệ: {sorted(allowed_source_ids)}"
                )


class AiAnalyzeRequest(BaseModel):
    """Yêu cầu chạy phân tích AI cho một tín hiệu giao dịch."""

    signal_id: Optional[uuid.UUID] = Field(
        default=None,
        description="ID của bản ghi trong analysis.stock_signals (ưu tiên nếu có)",
    )
    symbol: Optional[str] = Field(
        default=None,
        description="Mã cổ phiếu (nếu không truyền signal_id sẽ lấy tín hiệu mới nhất của mã này)",
    )
    news_articles: List[NewsArticleInput] = Field(
        default_factory=list,
        description="Danh sách tin tức có nguồn đính kèm (untrusted input)",
    )
    financial_metrics: Optional[FinancialMetricsInput] = Field(
        default=None,
        description="Chỉ số tài chính có nguồn đáng tin cậy (tùy chọn)",
    )
    allow_mock_when_disabled: bool = Field(
        default=False,
        description="Nếu AI_ENABLED=false, cho phép bỏ qua (SKIPPED) trừ khi bật cờ này để chạy Mock test",
    )


class AiReportResponse(BaseModel):
    """Kết quả bản ghi báo cáo AI từ bảng `analysis.ai_reports`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stock_id: Optional[uuid.UUID] = None
    symbol: Optional[str] = None
    signal_id: Optional[uuid.UUID] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    status: str
    input_snapshot: Optional[Dict[str, Any]] = None
    report: Optional[AiStructuredReportPayload] = None
    source_references: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class AiReportListResponse(BaseModel):
    """Danh sách các báo cáo AI đã tạo."""

    total: int
    items: List[AiReportResponse]
