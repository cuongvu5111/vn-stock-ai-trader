# Ngày tạo: 2026-11-17
# Mục đích: Nguồn thời gian duy nhất cho nghiệp vụ — timestamp sự kiện luôn UTC, ngày giao dịch luôn theo múi giờ thị trường.
# Lý do: `datetime.now(timezone.utc).date()` lệch 1 ngày so với lịch Việt Nam (UTC+7) từ 17:00 UTC trở đi,
#        làm sai ngày chốt NAV, ngày khớp lệnh và ngày thanh toán T+N.

from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@lru_cache
def _load_zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def utc_now() -> datetime:
    """Thời điểm hiện tại (timezone-aware, UTC) dùng cho mọi timestamp sự kiện."""
    return datetime.now(timezone.utc)


def market_timezone() -> ZoneInfo:
    """Múi giờ thị trường lấy từ `MARKET_TIMEZONE` (Settings chỉ chấp nhận Asia/Ho_Chi_Minh)."""
    return _load_zone(get_settings().MARKET_TIMEZONE)


def market_now(now: Optional[datetime] = None) -> datetime:
    """
    Quy đổi một thời điểm sang giờ thị trường. `now` cho phép inject thời gian khi test;
    bắt buộc timezone-aware để không ngầm hiểu nhầm một giá trị naive là UTC hay giờ địa phương.
    """
    current = utc_now() if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("`now` phải là datetime timezone-aware.")
    return current.astimezone(market_timezone())


def market_today(now: Optional[datetime] = None) -> date:
    """Ngày giao dịch hiện tại theo múi giờ thị trường (không phải ngày UTC)."""
    return market_now(now).date()
