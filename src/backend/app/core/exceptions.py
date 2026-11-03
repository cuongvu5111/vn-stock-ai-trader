# Ngày tạo: 2026-11-03
# Mục đích: Chuẩn hóa định dạng lỗi trả về từ API, không để lộ stack trace kỹ thuật ra giao diện.

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_correlation_id

logger = structlog.get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Đăng ký các bộ xử lý ngoại lệ tập trung cho FastAPI."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": str(exc.detail),
                    "correlation_id": get_correlation_id(),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Dữ liệu đầu vào không hợp lệ.",
                    "details": exc.errors(),
                    "correlation_id": get_correlation_id(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_server_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Đã xảy ra lỗi hệ thống nội bộ. Vui lòng kiểm tra log với correlation_id.",
                    "correlation_id": get_correlation_id(),
                }
            },
        )
