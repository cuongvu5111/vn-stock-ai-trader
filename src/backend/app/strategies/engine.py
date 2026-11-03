# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa BaseTradingStrategy và hai chiến lược giải thích được (TrendFollowingStrategy, PullbackStrategy).
# Lý do:
#   - Tuân thủ Mục 7 trong Implementation Plan: tham số cấu hình được, version hóa, có cả quy tắc BUY và quy tắc SELL/exit rõ ràng.
#   - Tuân thủ Signal Contract (Mục 7.3): symbol, strategy_id, strategy_version, signal_date, data_as_of, action, score,
#     reference_price, stop_loss, reason[], warnings[], source_data_version.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from app.indicators.calculator import IndicatorPoint, OhlcvBar

Q_PRICE_4 = Decimal("0.0001")
Q_SCORE_2 = Decimal("0.01")


def _q_price(val: Decimal) -> Decimal:
    return val.quantize(Q_PRICE_4, rounding=ROUND_HALF_UP)


def _q_score(val: Decimal) -> Decimal:
    return val.quantize(Q_SCORE_2, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class EvaluatedSignal:
    """Cấu trúc chuẩn theo Signal Contract (Mục 7.3)."""

    symbol: str
    strategy_id: str
    strategy_version: int
    signal_date: date
    data_as_of: date
    action: str  # BUY / SELL / HOLD
    score: Decimal
    reference_price: Decimal
    stop_loss: Optional[Decimal]
    reasons: List[str]
    warnings: List[str]
    source_data_version: str
    indicators_snapshot: Dict[str, Any]


class BaseTradingStrategy(ABC):
    """Lớp cơ sở cho mọi chiến lược giao dịch Daily / Swing EOD."""

    strategy_type: str

    def __init__(
        self,
        strategy_id: str,
        strategy_version: int,
        configuration: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.config = configuration or {}

    @abstractmethod
    def evaluate_bar(
        self,
        symbol: str,
        bar: OhlcvBar,
        indicator: IndicatorPoint,
        source_data_version: str = "CSV_EOD_V1",
    ) -> EvaluatedSignal:
        """Đánh giá một thanh nến và snapshot chỉ báo tại ngày T (chỉ dùng dữ liệu <= T)."""
        ...


class TrendFollowingStrategy(BaseTradingStrategy):
    """
    Chiến lược Trend Following (Mục 7.1):
    - Điều kiện BUY:
      1. Close > MA20 và MA20 > MA50 (xu hướng tăng đồng thuận ngắn & trung hạn).
      2. RSI14 nằm trong khoảng [rsi_min, rsi_max] (mặc định 50 - 70).
      3. Volume >= volume_multiplier * Volume_Avg20 (mặc định 1.2x).
      4. Đủ dữ liệu warm-up cho toàn bộ chỉ báo.
    - Điều kiện SELL / Exit:
      1. Close < MA20 (gãy xu hướng ngắn hạn) HOẶC
      2. MA20 < MA50 (đảo chiều cấu trúc xu hướng) HOẶC
      3. RSI14 >= rsi_overbought_exit (mặc định 78).
    """

    strategy_type = "TREND_FOLLOWING"

    def evaluate_bar(
        self,
        symbol: str,
        bar: OhlcvBar,
        indicator: IndicatorPoint,
        source_data_version: str = "CSV_EOD_V1",
    ) -> EvaluatedSignal:
        rsi_min = Decimal(str(self.config.get("rsi_min", "50")))
        rsi_max = Decimal(str(self.config.get("rsi_max", "70")))
        rsi_exit = Decimal(str(self.config.get("rsi_overbought_exit", "78")))
        vol_mult = Decimal(str(self.config.get("volume_multiplier", "1.2")))
        atr_mult = Decimal(str(self.config.get("atr_stop_multiplier", "2.0")))

        warnings: List[str] = [
            "INTERNAL_SCORE_NOT_PROBABILITY: Điểm số là thước đo khớp điều kiện nội bộ, không phải xác suất sinh lời."
        ]
        reasons: List[str] = []

        snapshot = {
            "close": str(bar.close),
            "volume": bar.volume,
            "ma20": str(indicator.ma20) if indicator.ma20 is not None else None,
            "ma50": str(indicator.ma50) if indicator.ma50 is not None else None,
            "rsi14": str(indicator.rsi14) if indicator.rsi14 is not None else None,
            "atr14": str(indicator.atr14) if indicator.atr14 is not None else None,
            "volume_avg20": str(indicator.volume_avg20) if indicator.volume_avg20 is not None else None,
            "calculation_version": indicator.calculation_version,
        }

        if any(
            v is None
            for v in (
                indicator.ma20,
                indicator.ma50,
                indicator.rsi14,
                indicator.atr14,
                indicator.volume_avg20,
            )
        ):
            warnings.append("INSUFFICIENT_WARMUP: Chưa đủ tối thiểu 50 phiên dữ liệu để tính đủ MA20/MA50/RSI14/ATR14.")
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="HOLD",
                score=Decimal("0.00"),
                reference_price=bar.close,
                stop_loss=None,
                reasons=["Chưa đủ dữ liệu warm-up cho các chỉ báo kỹ thuật bắt buộc."],
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        ma20 = indicator.ma20
        ma50 = indicator.ma50
        rsi14 = indicator.rsi14
        atr14 = indicator.atr14
        vol_avg20 = indicator.volume_avg20
        assert ma20 is not None and ma50 is not None and rsi14 is not None and atr14 is not None and vol_avg20 is not None

        # Kiểm tra điều kiện SELL / Exit trước
        if bar.close < ma20:
            reasons.append(f"Giá đóng cửa ({bar.close}) cắt xuống dưới MA20 ({ma20}) — gãy xu hướng ngắn hạn.")
        if ma20 < ma50:
            reasons.append(f"MA20 ({ma20}) nằm dưới MA50 ({ma50}) — xu hướng trung hạn suy yếu.")
        if rsi14 >= rsi_exit:
            reasons.append(f"RSI14 ({rsi14}) vượt ngưỡng quá mua thoát lệnh ({rsi_exit}).")

        if reasons:
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="SELL",
                score=Decimal("75.00"),
                reference_price=bar.close,
                stop_loss=None,
                reasons=reasons,
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        # Kiểm tra điều kiện BUY
        cond_price_above_ma20 = bar.close > ma20
        cond_ma20_above_ma50 = ma20 > ma50
        cond_rsi_in_range = rsi_min <= rsi14 <= rsi_max
        required_vol = vol_avg20 * vol_mult
        cond_volume = Decimal(bar.volume) >= required_vol and bar.volume > 0

        if cond_price_above_ma20 and cond_ma20_above_ma50 and cond_rsi_in_range and cond_volume:
            atr_buffer = atr14 * atr_mult if atr14 > Decimal("0") else bar.close * Decimal("0.03")
            stop_loss = _q_price(max(bar.close - atr_buffer, bar.close * Decimal("0.85")))

            vol_ratio = (Decimal(bar.volume) / vol_avg20) if vol_avg20 > 0 else Decimal("1")
            raw_score = Decimal("70") + min(vol_ratio * Decimal("5"), Decimal("20"))
            score = _q_score(min(raw_score, Decimal("95.00")))

            buy_reasons = [
                f"Giá đóng cửa ({bar.close}) > MA20 ({ma20}) và MA20 > MA50 ({ma50}).",
                f"RSI14 ({rsi14}) nằm trong vùng động lượng tích cực [{rsi_min}, {rsi_max}].",
                f"Khối lượng ({bar.volume}) >= {vol_mult}x bình quân 20 phiên ({vol_avg20}).",
            ]
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="BUY",
                score=score,
                reference_price=bar.close,
                stop_loss=stop_loss,
                reasons=buy_reasons,
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        hold_reasons = ["Chưa hội tụ đủ toàn bộ điều kiện BUY hoặc SELL của chiến lược Trend Following."]
        if not cond_volume:
            hold_reasons.append(f"Khối lượng ({bar.volume}) chưa đạt ngưỡng {vol_mult}x bình quân 20 phiên ({vol_avg20}).")
        if not cond_rsi_in_range:
            hold_reasons.append(f"RSI14 ({rsi14}) nằm ngoài vùng mục tiêu [{rsi_min}, {rsi_max}].")

        return EvaluatedSignal(
            symbol=symbol,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            signal_date=bar.trading_date,
            data_as_of=bar.trading_date,
            action="HOLD",
            score=Decimal("50.00"),
            reference_price=bar.close,
            stop_loss=None,
            reasons=hold_reasons,
            warnings=warnings,
            source_data_version=source_data_version,
            indicators_snapshot=snapshot,
        )


class PullbackStrategy(BaseTradingStrategy):
    """
    Chiến lược Pullback về vùng hỗ trợ động trong xu hướng tăng (Mục 7.2):
    - Điều kiện BUY:
      1. Xu hướng trung hạn tăng: Close > MA50 và MA20 >= MA50.
      2. Giá điều chỉnh về vùng hỗ trợ MA20: khoảng cách |Close - MA20| / MA20 <= pullback_tolerance_pct (mặc định 2.5%)
         hoặc giá Low chạm vùng MA20 (Low <= MA20 * 1.01) rồi rút chân đóng cửa xanh (Close >= Open).
      3. RSI14 hồi phục trong vùng hợp lý [rsi_recovery_min, rsi_recovery_max] (mặc định 40 - 62).
    - Điều kiện SELL / Exit (Invalidation):
      1. Close < MA50 (gãy cấu trúc xu hướng trung hạn) HOẶC
      2. RSI14 >= rsi_take_profit (mặc định 72).
    """

    strategy_type = "PULLBACK"

    def evaluate_bar(
        self,
        symbol: str,
        bar: OhlcvBar,
        indicator: IndicatorPoint,
        source_data_version: str = "CSV_EOD_V1",
    ) -> EvaluatedSignal:
        tolerance_pct = Decimal(str(self.config.get("pullback_tolerance_pct", "0.025")))
        rsi_min = Decimal(str(self.config.get("rsi_recovery_min", "40")))
        rsi_max = Decimal(str(self.config.get("rsi_recovery_max", "62")))
        rsi_tp = Decimal(str(self.config.get("rsi_take_profit", "72")))
        atr_mult = Decimal(str(self.config.get("atr_stop_multiplier", "1.5")))

        warnings: List[str] = [
            "INTERNAL_SCORE_NOT_PROBABILITY: Điểm số là thước đo khớp điều kiện nội bộ, không phải xác suất sinh lời."
        ]

        snapshot = {
            "open": str(bar.open),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": bar.volume,
            "ma20": str(indicator.ma20) if indicator.ma20 is not None else None,
            "ma50": str(indicator.ma50) if indicator.ma50 is not None else None,
            "rsi14": str(indicator.rsi14) if indicator.rsi14 is not None else None,
            "atr14": str(indicator.atr14) if indicator.atr14 is not None else None,
            "calculation_version": indicator.calculation_version,
        }

        if any(
            v is None
            for v in (indicator.ma20, indicator.ma50, indicator.rsi14, indicator.atr14)
        ):
            warnings.append("INSUFFICIENT_WARMUP: Chưa đủ tối thiểu 50 phiên dữ liệu cho chiến lược Pullback.")
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="HOLD",
                score=Decimal("0.00"),
                reference_price=bar.close,
                stop_loss=None,
                reasons=["Chưa đủ dữ liệu warm-up cho chiến lược Pullback."],
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        ma20 = indicator.ma20
        ma50 = indicator.ma50
        rsi14 = indicator.rsi14
        atr14 = indicator.atr14
        assert ma20 is not None and ma50 is not None and rsi14 is not None and atr14 is not None

        # Kiểm tra điều kiện SELL / Invalidation
        sell_reasons: List[str] = []
        if bar.close < ma50:
            sell_reasons.append(f"Giá đóng cửa ({bar.close}) thủng MA50 ({ma50}) — vi phạm xu hướng trung hạn (invalidation).")
        if rsi14 >= rsi_tp:
            sell_reasons.append(f"RSI14 ({rsi14}) chạm vùng chốt lời ({rsi_tp}).")

        if sell_reasons:
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="SELL",
                score=Decimal("75.00"),
                reference_price=bar.close,
                stop_loss=None,
                reasons=sell_reasons,
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        # Kiểm tra điều kiện BUY
        cond_uptrend = bar.close > ma50 and ma20 >= ma50
        distance_to_ma20 = abs(bar.close - ma20) / ma20 if ma20 > 0 else Decimal("1")
        cond_near_ma20 = distance_to_ma20 <= tolerance_pct or (bar.low <= ma20 * Decimal("1.01") and bar.close >= ma20)
        cond_bullish_candle = bar.close >= bar.open
        cond_rsi = rsi_min <= rsi14 <= rsi_max

        if cond_uptrend and cond_near_ma20 and cond_bullish_candle and cond_rsi:
            atr_buffer = atr14 * atr_mult if atr14 > Decimal("0") else bar.close * Decimal("0.03")
            anchor_support = min(bar.low, ma50)
            stop_loss = _q_price(max(anchor_support - atr_buffer, bar.close * Decimal("0.85")))

            buy_reasons = [
                f"Xu hướng trung hạn tăng: Close ({bar.close}) > MA50 ({ma50}) và MA20 ({ma20}) >= MA50.",
                f"Giá kiểm định thành công vùng hỗ trợ MA20 ({ma20}) với nến hồi phục xanh (Close {bar.close} >= Open {bar.open}).",
                f"RSI14 ({rsi14}) nằm trong vùng tích lũy hồi phục [{rsi_min}, {rsi_max}].",
            ]
            return EvaluatedSignal(
                symbol=symbol,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                signal_date=bar.trading_date,
                data_as_of=bar.trading_date,
                action="BUY",
                score=Decimal("78.00"),
                reference_price=bar.close,
                stop_loss=stop_loss,
                reasons=buy_reasons,
                warnings=warnings,
                source_data_version=source_data_version,
                indicators_snapshot=snapshot,
            )

        return EvaluatedSignal(
            symbol=symbol,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            signal_date=bar.trading_date,
            data_as_of=bar.trading_date,
            action="HOLD",
            score=Decimal("50.00"),
            reference_price=bar.close,
            stop_loss=None,
            reasons=["Chưa xuất hiện nhịp điều chỉnh Pullback đạt chuẩn về vùng hỗ trợ MA20."],
            warnings=warnings,
            source_data_version=source_data_version,
            indicators_snapshot=snapshot,
        )


def build_strategy_instance(
    strategy_type: str,
    strategy_id: str,
    strategy_version: int = 1,
    configuration: Optional[Dict[str, Any]] = None,
) -> BaseTradingStrategy:
    """Factory khởi tạo đối tượng chiến lược theo strategy_type."""
    normalized = strategy_type.strip().upper()
    if normalized == "TREND_FOLLOWING":
        return TrendFollowingStrategy(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            configuration=configuration,
        )
    if normalized == "PULLBACK":
        return PullbackStrategy(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            configuration=configuration,
        )
    raise ValueError(f"Loại chiến lược không được hỗ trợ: '{strategy_type}'.")
