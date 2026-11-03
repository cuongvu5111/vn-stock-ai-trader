# Ngày tạo: 2026-11-03
# Mục đích: Cấu hình structured logging (JSON) và middleware gắn Correlation ID cho mỗi request/job.
# Lý do: Đảm bảo khả năng truy vết (traceability) cho mọi quyết định phân tích, kiểm tra rủi ro và đặt lệnh Paper.

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Lấy correlation_id hiện tại của ngữ cảnh request hoặc sinh mới nếu chưa có."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_ctx.set(cid)
    return cid


def inject_correlation_id(_, __, event_dict: dict) -> dict:
    """Processor tự động gắn correlation_id vào mỗi dòng log."""
    cid = correlation_id_ctx.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Thiết lập structlog xuất JSON chuẩn cho môi trường vận hành."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            inject_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware đọc hoặc tạo mới X-Correlation-ID cho mỗi HTTP request."""

    HEADER_NAME = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cid = request.headers.get(self.HEADER_NAME) or str(uuid.uuid4())
        token = correlation_id_ctx.set(cid)
        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)
