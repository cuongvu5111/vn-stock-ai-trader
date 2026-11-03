# Ngày tạo: 2026-11-03
# Mục đích: Kiểm tra tính hợp lệ của từng dòng dữ liệu OHLCV từ CSV và phát hiện bất thường chuỗi thời gian.
# Lý do: Đảm bảo dữ liệu lỗi bị báo cáo rõ ràng, không âm thầm lọt vào database (Sprint 2 Acceptance Criteria).

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

REQUIRED_CSV_COLUMNS = {"symbol", "trading_date", "open", "high", "low", "close", "volume"}
VALID_EXCHANGES = {"HOSE", "HNX", "UPCOM"}


@dataclass(frozen=True)
class ValidatedOhlcvRow:
    """Dữ liệu một dòng OHLCV đã vượt qua toàn bộ bước kiểm tra chất lượng."""

    row_number: int
    symbol: str
    exchange: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Optional[Decimal]
    volume: int
    data_label: str


@dataclass(frozen=True)
class RejectedOhlcvRow:
    """Thông tin chi tiết về một dòng CSV bị từ chối do vi phạm quy tắc dữ liệu."""

    row_number: int
    raw_data: Dict[str, Any]
    error_code: str
    error_message: str


def _parse_positive_decimal(raw_value: Any, field_name: str) -> Decimal:
    """Chuyển chuỗi sang Decimal dương, tuyệt đối không đi qua float."""
    if raw_value is None or str(raw_value).strip() == "":
        raise ValueError(f"Trường '{field_name}' không được để trống.")
    try:
        value = Decimal(str(raw_value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Trường '{field_name}' không phải là số hợp lệ: '{raw_value}'.") from exc

    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"Trường '{field_name}' phải lớn hơn 0 (nhận được: {value}).")
    return value.quantize(Decimal("0.0001"))


def validate_ohlcv_rows(
    raw_rows: List[Dict[str, Any]],
    market_timezone: str = "Asia/Ho_Chi_Minh",
    default_exchange: str = "HOSE",
) -> Tuple[List[ValidatedOhlcvRow], List[RejectedOhlcvRow], Dict[str, List[str]]]:
    """
    Kiểm tra danh sách các dòng đọc từ CSV.
    Trả về: (danh_sách_hợp_lệ, danh_sách_bị_từ_chối, cảnh_báo_thiếu_ngày_theo_mã).
    """
    valid_rows: List[ValidatedOhlcvRow] = []
    rejected_rows: List[RejectedOhlcvRow] = []
    seen_keys: Set[Tuple[str, date]] = set()
    dates_by_symbol: Dict[str, Set[date]] = {}

    today_market = datetime.now(ZoneInfo(market_timezone)).date()

    for idx, row in enumerate(raw_rows, start=2):  # Dòng 1 là header CSV
        try:
            normalized = {
                (k.strip().lower() if isinstance(k, str) else ""): (
                    v.strip() if isinstance(v, str) else v
                )
                for k, v in row.items()
                if k is not None
            }

            missing_cols = REQUIRED_CSV_COLUMNS - set(normalized.keys())
            if missing_cols:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="MISSING_COLUMNS",
                        error_message=f"Thiếu các cột bắt buộc: {sorted(missing_cols)}",
                    )
                )
                continue

            symbol = str(normalized.get("symbol", "")).upper()
            if not symbol or len(symbol) > 20 or not symbol.isalnum():
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_SYMBOL",
                        error_message=f"Mã cổ phiếu không hợp lệ: '{symbol}'.",
                    )
                )
                continue

            exchange = str(normalized.get("exchange") or default_exchange).upper()
            if exchange not in VALID_EXCHANGES:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_EXCHANGE",
                        error_message=f"Sàn giao dịch '{exchange}' không thuộc {sorted(VALID_EXCHANGES)}.",
                    )
                )
                continue

            raw_date = str(normalized.get("trading_date", ""))
            try:
                trading_date = date.fromisoformat(raw_date)
            except ValueError:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_DATE",
                        error_message=f"Ngày giao dịch không đúng định dạng YYYY-MM-DD: '{raw_date}'.",
                    )
                )
                continue

            if trading_date > today_market:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="FUTURE_DATE",
                        error_message=f"Ngày giao dịch {trading_date} nằm trong tương lai so với {today_market}.",
                    )
                )
                continue

            key = (symbol, trading_date)
            if key in seen_keys:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="DUPLICATE_IN_BATCH",
                        error_message=f"Trùng lặp dữ liệu của mã {symbol} vào ngày {trading_date} ngay trong cùng file.",
                    )
                )
                continue

            try:
                open_p = _parse_positive_decimal(normalized.get("open"), "open")
                high_p = _parse_positive_decimal(normalized.get("high"), "high")
                low_p = _parse_positive_decimal(normalized.get("low"), "low")
                close_p = _parse_positive_decimal(normalized.get("close"), "close")

                raw_adj = normalized.get("adjusted_close")
                adj_close_p = (
                    _parse_positive_decimal(raw_adj, "adjusted_close")
                    if raw_adj not in (None, "")
                    else None
                )
            except ValueError as dec_err:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_PRICE",
                        error_message=str(dec_err),
                    )
                )
                continue

            # Kiểm tra quan hệ biên độ giá OHLC
            if high_p < low_p:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_OHLC_HIGH_LOW",
                        error_message=f"Giá high ({high_p}) nhỏ hơn giá low ({low_p}).",
                    )
                )
                continue

            if high_p < open_p or high_p < close_p:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_OHLC_HIGH_BOUND",
                        error_message=f"Giá high ({high_p}) phải >= open ({open_p}) và close ({close_p}).",
                    )
                )
                continue

            if low_p > open_p or low_p > close_p:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_OHLC_LOW_BOUND",
                        error_message=f"Giá low ({low_p}) phải <= open ({open_p}) và close ({close_p}).",
                    )
                )
                continue

            raw_vol = str(normalized.get("volume", ""))
            try:
                if "." in raw_vol:
                    raise ValueError("Khối lượng phải là số nguyên.")
                volume = int(raw_vol)
            except ValueError:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="INVALID_VOLUME",
                        error_message=f"Khối lượng giao dịch không hợp lệ: '{raw_vol}'.",
                    )
                )
                continue

            if volume < 0:
                rejected_rows.append(
                    RejectedOhlcvRow(
                        row_number=idx,
                        raw_data=row,
                        error_code="NEGATIVE_VOLUME",
                        error_message=f"Khối lượng giao dịch không được âm: {volume}.",
                    )
                )
                continue

            data_label = str(normalized.get("data_label") or "HISTORICAL").upper()

            seen_keys.add(key)
            dates_by_symbol.setdefault(symbol, set()).add(trading_date)
            valid_rows.append(
                ValidatedOhlcvRow(
                    row_number=idx,
                    symbol=symbol,
                    exchange=exchange,
                    trading_date=trading_date,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    adjusted_close=adj_close_p,
                    volume=volume,
                    data_label=data_label,
                )
            )
        except Exception as unexpected_exc:
            rejected_rows.append(
                RejectedOhlcvRow(
                    row_number=idx,
                    raw_data=row,
                    error_code="ROW_PARSE_ERROR",
                    error_message=str(unexpected_exc),
                )
            )

    missing_weekdays_by_symbol = detect_missing_weekdays(dates_by_symbol)
    return valid_rows, rejected_rows, missing_weekdays_by_symbol


def detect_missing_weekdays(dates_by_symbol: Dict[str, Set[date]]) -> Dict[str, List[str]]:
    """
    Phát hiện các ngày làm việc (Thứ Hai - Thứ Sáu) bị khuyết trong khoảng [min_date, max_date]
    của từng mã cổ phiếu để cảnh báo chất lượng chuỗi dữ liệu.
    """
    missing_report: Dict[str, List[str]] = {}
    for symbol, date_set in dates_by_symbol.items():
        if len(date_set) < 2:
            continue
        start_d = min(date_set)
        end_d = max(date_set)
        current = start_d + timedelta(days=1)
        missing_dates: List[str] = []
        while current < end_d:
            if current.weekday() < 5 and current not in date_set:
                missing_dates.append(current.isoformat())
            current += timedelta(days=1)
        if missing_dates:
            missing_report[symbol] = missing_dates
    return missing_report
