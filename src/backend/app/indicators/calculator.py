# Ngày tạo: 2026-11-03
# Mục đích: Tính toán bộ chỉ báo kỹ thuật (SMA, EMA, RSI14, MACD, ATR14, Volume Avg 20) một cách deterministic bằng Decimal.
# Lý do:
#   - Đảm bảo không dùng float gây sai số làm tròn tài chính.
#   - Tuân thủ nghiêm ngặt giai đoạn làm nóng dữ liệu (warm-up period): trả về None khi chưa đủ số phiên.
#   - Chống look-ahead bias: chỉ báo tại phiên thứ i chỉ phụ thuộc vào dữ liệu từ phiên 0 đến phiên i.

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Sequence

Q_PRICE_4 = Decimal("0.0001")
Q_MACD_6 = Decimal("0.000001")
Q_VOL_2 = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0")


@dataclass(frozen=True)
class OhlcvBar:
    """Một thanh nến OHLCV đầu vào đã được sắp xếp theo ngày giao dịch tăng dần."""

    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class IndicatorPoint:
    """Kết quả toàn bộ các chỉ báo kỹ thuật tại một ngày giao dịch cụ thể."""

    trading_date: date
    ma20: Optional[Decimal]
    ma50: Optional[Decimal]
    ma200: Optional[Decimal]
    ema20: Optional[Decimal]
    ema50: Optional[Decimal]
    rsi14: Optional[Decimal]
    macd: Optional[Decimal]
    macd_signal: Optional[Decimal]
    macd_histogram: Optional[Decimal]
    atr14: Optional[Decimal]
    volume_avg20: Optional[Decimal]
    calculation_version: str


def _q(val: Optional[Decimal], quantum: Decimal) -> Optional[Decimal]:
    """Làm tròn Decimal theo chuẩn ROUND_HALF_UP nếu giá trị khác None."""
    if val is None:
        return None
    return val.quantize(quantum, rounding=ROUND_HALF_UP)


def compute_sma_series(values: Sequence[Decimal], period: int) -> List[Optional[Decimal]]:
    """
    Tính Simple Moving Average (SMA) cho chuỗi Decimal.
    Trả về None cho các vị trí index < period - 1 (chưa đủ dữ liệu warm-up).
    """
    if period <= 0:
        raise ValueError("Chu kỳ SMA phải lớn hơn 0.")
    n = len(values)
    result: List[Optional[Decimal]] = [None] * n
    if n < period:
        return result

    period_dec = Decimal(period)
    window_sum = sum(values[:period], ZERO)
    result[period - 1] = window_sum / period_dec

    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period_dec

    return result


def compute_ema_series(values: Sequence[Decimal], period: int) -> List[Optional[Decimal]]:
    """
    Tính Exponential Moving Average (EMA) với hạt giống khởi tạo là SMA(period) tại index = period - 1.
    Trả về None cho các vị trí index < period - 1.
    """
    if period <= 0:
        raise ValueError("Chu kỳ EMA phải lớn hơn 0.")
    n = len(values)
    result: List[Optional[Decimal]] = [None] * n
    if n < period:
        return result

    multiplier = Decimal(2) / Decimal(period + 1)
    seed_sma = sum(values[:period], ZERO) / Decimal(period)
    prev_ema = seed_sma
    result[period - 1] = prev_ema

    for i in range(period, n):
        current_ema = (values[i] - prev_ema) * multiplier + prev_ema
        result[i] = current_ema
        prev_ema = current_ema

    return result


def compute_rsi_wilder_series(closes: Sequence[Decimal], period: int = 14) -> List[Optional[Decimal]]:
    """
    Tính Relative Strength Index (RSI) theo phương pháp làm mượt của Wilder.
    Cần ít nhất `period` bước thay đổi giá (tức `period + 1` phiên, bắt đầu có giá trị tại index = period).
    Xử lý an toàn trường hợp giá đi ngang (flat prices -> RSI = 50) hoặc chỉ tăng (RSI = 100).
    """
    n = len(closes)
    result: List[Optional[Decimal]] = [None] * n
    if n <= period:
        return result

    period_dec = Decimal(period)
    period_minus_one = Decimal(period - 1)

    gains: List[Decimal] = [ZERO] * n
    losses: List[Decimal] = [ZERO] * n

    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        if delta > ZERO:
            gains[i] = delta
        elif delta < ZERO:
            losses[i] = -delta

    avg_gain = sum(gains[1 : period + 1], ZERO) / period_dec
    avg_loss = sum(losses[1 : period + 1], ZERO) / period_dec

    def _calc_rsi_from_averages(ag: Decimal, al: Decimal) -> Decimal:
        if ag == ZERO and al == ZERO:
            return Decimal("50")
        if al == ZERO:
            return HUNDRED
        if ag == ZERO:
            return ZERO
        rs = ag / al
        return HUNDRED - (HUNDRED / (Decimal("1") + rs))

    result[period] = _calc_rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * period_minus_one + gains[i]) / period_dec
        avg_loss = (avg_loss * period_minus_one + losses[i]) / period_dec
        result[i] = _calc_rsi_from_averages(avg_gain, avg_loss)

    return result


def compute_macd_series(
    closes: Sequence[Decimal],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[List[Optional[Decimal]], List[Optional[Decimal]], List[Optional[Decimal]]]:
    """
    Tính bộ 3 chỉ báo MACD (12, 26, 9):
    - MACD line = EMA(12) - EMA(26), bắt đầu có từ index = slow_period - 1 (25).
    - Signal line = EMA(9) tính trên chuỗi MACD hợp lệ, bắt đầu có từ index = slow_period + signal_period - 2 (33).
    - Histogram = MACD line - Signal line.
    """
    n = len(closes)
    macd_line: List[Optional[Decimal]] = [None] * n
    signal_line: List[Optional[Decimal]] = [None] * n
    histogram: List[Optional[Decimal]] = [None] * n

    if n < slow_period:
        return macd_line, signal_line, histogram

    ema_fast = compute_ema_series(closes, fast_period)
    ema_slow = compute_ema_series(closes, slow_period)

    valid_macd_values: List[Decimal] = []
    valid_macd_indices: List[int] = []

    for i in range(slow_period - 1, n):
        ef = ema_fast[i]
        es = ema_slow[i]
        if ef is not None and es is not None:
            m_val = ef - es
            macd_line[i] = m_val
            valid_macd_values.append(m_val)
            valid_macd_indices.append(i)

    if len(valid_macd_values) >= signal_period:
        ema_signal_on_valid = compute_ema_series(valid_macd_values, signal_period)
        for pos, sig_val in enumerate(ema_signal_on_valid):
            if sig_val is not None:
                bar_idx = valid_macd_indices[pos]
                signal_line[bar_idx] = sig_val
                m_val = macd_line[bar_idx]
                if m_val is not None:
                    histogram[bar_idx] = m_val - sig_val

    return macd_line, signal_line, histogram


def compute_atr_wilder_series(bars: Sequence[OhlcvBar], period: int = 14) -> List[Optional[Decimal]]:
    """
    Tính Average True Range (ATR) 14 phiên theo công thức làm mượt của Wilder.
    True Range từ phiên i >= 1 sử dụng previous close (bars[i-1].close).
    Cần đủ `period` giá trị True Range (tức `period + 1` phiên, bắt đầu có ATR tại index = period).
    """
    n = len(bars)
    result: List[Optional[Decimal]] = [None] * n
    if n <= period:
        return result

    period_dec = Decimal(period)
    period_minus_one = Decimal(period - 1)
    tr_values: List[Decimal] = [ZERO] * n

    for i in range(1, n):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        tr_values[i] = tr

    current_atr = sum(tr_values[1 : period + 1], ZERO) / period_dec
    result[period] = current_atr

    for i in range(period + 1, n):
        current_atr = (current_atr * period_minus_one + tr_values[i]) / period_dec
        result[i] = current_atr

    return result


def calculate_indicator_series(
    bars: Sequence[OhlcvBar],
    calculation_version: str = "v1.0",
) -> List[IndicatorPoint]:
    """
    Tính toàn bộ các chỉ báo kỹ thuật cho một chuỗi nến OHLCV.
    Tự động sắp xếp lại theo ngày tăng dần để đảm bảo tính tất định (deterministic) và không dùng dữ liệu tương lai.
    """
    if not bars:
        return []

    sorted_bars = sorted(bars, key=lambda b: b.trading_date)
    closes = [b.close for b in sorted_bars]
    volumes = [Decimal(b.volume) for b in sorted_bars]

    ma20_raw = compute_sma_series(closes, 20)
    ma50_raw = compute_sma_series(closes, 50)
    ma200_raw = compute_sma_series(closes, 200)

    ema20_raw = compute_ema_series(closes, 20)
    ema50_raw = compute_ema_series(closes, 50)

    rsi14_raw = compute_rsi_wilder_series(closes, 14)
    macd_raw, macd_sig_raw, macd_hist_raw = compute_macd_series(closes, 12, 26, 9)
    atr14_raw = compute_atr_wilder_series(sorted_bars, 14)
    vol_avg20_raw = compute_sma_series(volumes, 20)

    points: List[IndicatorPoint] = []
    for i, bar in enumerate(sorted_bars):
        points.append(
            IndicatorPoint(
                trading_date=bar.trading_date,
                ma20=_q(ma20_raw[i], Q_PRICE_4),
                ma50=_q(ma50_raw[i], Q_PRICE_4),
                ma200=_q(ma200_raw[i], Q_PRICE_4),
                ema20=_q(ema20_raw[i], Q_PRICE_4),
                ema50=_q(ema50_raw[i], Q_PRICE_4),
                rsi14=_q(rsi14_raw[i], Q_PRICE_4),
                macd=_q(macd_raw[i], Q_MACD_6),
                macd_signal=_q(macd_sig_raw[i], Q_MACD_6),
                macd_histogram=_q(macd_hist_raw[i], Q_MACD_6),
                atr14=_q(atr14_raw[i], Q_PRICE_4),
                volume_avg20=_q(vol_avg20_raw[i], Q_VOL_2),
                calculation_version=calculation_version,
            )
        )

    return points
