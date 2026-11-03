# Ngày tạo: 2026-11-03
# Mục đích: Router tổng hợp toàn bộ các endpoints thuộc phiên bản /api/v1.

from fastapi import APIRouter

from app.api.v1.ai import router as ai_router
from app.api.v1.health import router as health_router
from app.api.v1.indicators import router as indicators_router
from app.api.v1.market import router as market_router
from app.api.v1.strategies import router as strategies_router
from app.api.v1.system import router as system_router
from app.api.v1.trading import router as trading_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(indicators_router)
api_v1_router.include_router(strategies_router)
api_v1_router.include_router(ai_router)
api_v1_router.include_router(trading_router)
api_v1_router.include_router(system_router)
