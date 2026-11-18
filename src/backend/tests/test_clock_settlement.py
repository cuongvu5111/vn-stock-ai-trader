# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử hàm thuần của đồng hồ thị trường (`app.core.clock`), lịch thanh toán T+N
#           (`app.trading.settlement`) và cấu hình `SETTLEMENT_LAG_TRADING_DAYS`.
# Lý do: Ngày giao dịch phải theo múi giờ thị trường (UTC+7), không theo ngày UTC; T+2 bỏ thứ 7/Chủ nhật.

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core import clock
from app.core.config import Settings, get_settings
from app.trading.settlement import (
    LedgerFill,
    add_trading_days,
    is_trading_day,
    settled_available_quantity,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MARKET_TIMEZONE = "Asia/Ho_Chi_Minh"
MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 11, d) for d in range(16, 23))
NEXT_MON, NEXT_TUE = date(2026, 11, 23), date(2026, 11, 24)


def test_market_today_uses_market_timezone_not_utc_date() -> None:
    late_utc = datetime(2026, 11, 17, 23, 30, tzinfo=timezone.utc)

    assert late_utc.date() == date(2026, 11, 17)
    assert clock.market_today(late_utc) == date(2026, 11, 18)
    assert clock.market_now(late_utc).utcoffset() == timedelta(hours=7)


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "expected_day"),
    [(16, 59, 17), (17, 0, 18), (0, 0, 17), (23, 59, 18)],
)
def test_market_day_rolls_over_at_17_00_utc(utc_hour: int, utc_minute: int, expected_day: int) -> None:
    now = datetime(2026, 11, 17, utc_hour, utc_minute, tzinfo=timezone.utc)

    assert clock.market_today(now) == date(2026, 11, expected_day)


def test_market_today_accepts_any_aware_timezone_and_rejects_naive() -> None:
    vn_just_after_midnight = datetime(2026, 11, 18, 0, 5, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    assert clock.market_today(vn_just_after_midnight) == date(2026, 11, 18)

    with pytest.raises(ValueError):
        clock.market_today(datetime(2026, 11, 17, 23, 30))


def test_clock_defaults_use_injected_utc_now_and_utc_is_timezone_aware(fake_clock) -> None:
    fake_clock.set_utc(2026, 11, 17, 23, 30)

    assert clock.utc_now().utcoffset() == timedelta(0)
    assert clock.market_today() == date(2026, 11, 18)
    assert clock.market_now().tzinfo is not None


def test_real_utc_now_is_timezone_aware() -> None:
    assert clock.utc_now().tzinfo is timezone.utc


def test_market_timezone_is_pinned_to_ho_chi_minh_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_TIMEZONE", raising=False)
    now = datetime(2026, 11, 17, 23, 30, tzinfo=timezone.utc)

    assert Settings(_env_file=None).MARKET_TIMEZONE == MARKET_TIMEZONE
    assert Settings(MARKET_TIMEZONE=MARKET_TIMEZONE).MARKET_TIMEZONE == MARKET_TIMEZONE
    assert get_settings().MARKET_TIMEZONE == MARKET_TIMEZONE
    assert clock.market_timezone().key == MARKET_TIMEZONE
    assert clock.market_today(now) == date(2026, 11, 18)


@pytest.mark.parametrize(
    "value", ["UTC", "Asia/Bangkok", "Asia/Saigon", "asia/ho_chi_minh", " Asia/Ho_Chi_Minh", ""]
)
def test_market_timezone_rejects_any_value_other_than_ho_chi_minh(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError):
        Settings(MARKET_TIMEZONE=value)

    monkeypatch.setenv("MARKET_TIMEZONE", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("start", "lag", "expected"),
    [
        (MON, 2, WED),
        (TUE, 2, THU),
        (WED, 2, FRI),
        (THU, 2, NEXT_MON),
        (FRI, 2, NEXT_TUE),
        (SAT, 2, NEXT_TUE),
        (SUN, 2, NEXT_TUE),
        (MON, 0, MON),
        (FRI, 1, NEXT_MON),
        (MON, 5, NEXT_MON),
        (SAT, 1, date(2026, 11, 23)),
    ],
)
def test_add_trading_days_skips_weekends(start: date, lag: int, expected: date) -> None:
    assert add_trading_days(start, lag) == expected


def test_add_trading_days_counts_exactly_lag_business_days() -> None:
    for offset in range(60):
        start = MON + timedelta(days=offset)
        for lag in range(0, 11):
            result = add_trading_days(start, lag)
            business_days = sum(
                is_trading_day(start + timedelta(days=i)) for i in range(1, (result - start).days + 1)
            )
            assert business_days == lag
            if lag > 0:
                assert is_trading_day(result)


def test_add_trading_days_rejects_negative_lag() -> None:
    with pytest.raises(ValueError):
        add_trading_days(MON, -1)


def test_settled_available_quantity_ignores_unsettled_buys_and_never_goes_negative() -> None:
    fills = [LedgerFill("BUY", 100, WED), LedgerFill("BUY", 200, THU)]

    assert settled_available_quantity(fills, TUE) == 0
    assert settled_available_quantity(fills, WED) == 100
    assert settled_available_quantity(fills, THU) == 300
    assert settled_available_quantity([], THU) == 0

    oversold = [*fills, LedgerFill("SELL", 500, THU)]
    assert settled_available_quantity(oversold, NEXT_MON) == 0


def test_settled_available_quantity_handles_partial_fills_and_sells() -> None:
    fills = [
        LedgerFill("BUY", 100, WED),
        LedgerFill("BUY", 100, THU),
        LedgerFill("SELL", 60, WED),
    ]

    assert settled_available_quantity(fills, WED) == 40
    assert settled_available_quantity(fills, THU) == 140


@pytest.mark.parametrize(("value", "valid"), [(0, True), (2, True), (10, True), (-1, False), (11, False)])
def test_settlement_lag_setting_is_validated(value: int, valid: bool) -> None:
    if valid:
        assert Settings(SETTLEMENT_LAG_TRADING_DAYS=value).SETTLEMENT_LAG_TRADING_DAYS == value
    else:
        with pytest.raises(ValidationError):
            Settings(SETTLEMENT_LAG_TRADING_DAYS=value)


def test_settlement_lag_defaults_to_two_trading_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SETTLEMENT_LAG_TRADING_DAYS", raising=False)

    assert Settings(_env_file=None).SETTLEMENT_LAG_TRADING_DAYS == 2


@pytest.mark.parametrize("relative_path", [".env.example", "docker-compose.yml"])
def test_settlement_lag_is_documented_in_env_and_compose(relative_path: str) -> None:
    content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    assert "SETTLEMENT_LAG_TRADING_DAYS" in content


@pytest.mark.parametrize(
    ("relative_path", "expected_line"),
    [
        (".env.example", f"MARKET_TIMEZONE={MARKET_TIMEZONE}"),
        ("docker-compose.yml", f"MARKET_TIMEZONE: ${{MARKET_TIMEZONE:-{MARKET_TIMEZONE}}}"),
    ],
)
def test_market_timezone_env_defaults_match_the_only_allowed_value(
    relative_path: str, expected_line: str
) -> None:
    lines = [line.strip() for line in (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()]

    assert expected_line in lines
