# Ngày tạo: 2026-11-03
# Mục đích: Kết nối cổng dữ liệu lịch sử & giá mới nhất thực tế của thị trường chứng khoán Việt Nam (VNDirect DChart API).
# Lý do:
#   - Thay thế dữ liệu mẫu [SAMPLE] bằng dữ liệu OHLCV thực tế của các mã HOSE/HNX/UPCOM mà không cần crawl HTML.
#   - Quy đổi chính xác đơn vị giá (1,000 VND -> VND) bằng kiểu Decimal.

import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List
from zoneinfo import ZoneInfo

import httpx

from app.market_data.validators import ValidatedOhlcvRow

Q_PRICE_4 = Decimal("0.0001")
THOUSAND = Decimal("1000")
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

DEFAULT_REAL_VN_STOCKS: Dict[str, tuple[str, str, str]] = {
    "FPT": ("HOSE", "CTCP FPT", "Công nghệ thông tin"),
    "HPG": ("HOSE", "CTCP Tập đoàn Hòa Phát", "Thép & Vật liệu"),
    "VCB": ("HOSE", "Ngân hàng TMCP Ngoại thương Việt Nam", "Ngân hàng"),
    "ACB": ("HOSE", "Ngân hàng TMCP Á Châu", "Ngân hàng"),
    "MBB": ("HOSE", "Ngân hàng TMCP Quân Đội", "Ngân hàng"),
    "TCB": ("HOSE", "Ngân hàng TMCP Kỹ thương Việt Nam", "Ngân hàng"),
    "SSI": ("HOSE", "CTCP Chứng khoán SSI", "Chứng khoán"),
    "MWG": ("HOSE", "CTCP Đầu tư Thế Giới Di Động", "Bán lẻ"),
    "CTG": ("HOSE", "Ngân hàng TMCP Công Thương Việt Nam", "Ngân hàng"),
    "VNM": ("HOSE", "CTCP Sữa Việt Nam (Vinamilk)", "Thực phẩm & Đồ uống"),
}


def _to_vnd_decimal(val: float | int | str) -> Decimal:
    return (Decimal(str(val)) * THOUSAND).quantize(Q_PRICE_4, rounding=ROUND_HALF_UP)


class VnMarketLiveHttpProvider:
    """Provider tải dữ liệu OHLCV thực tế của chứng khoán Việt Nam từ VNDirect DChart UDF API."""

    endpoint_url: str = "https://dchart-api.vndirect.com.vn/dchart/history"

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_symbol_daily_bars(
        self,
        symbol: str,
        lookback_days: int = 220,
    ) -> List[ValidatedOhlcvRow]:
        """Lấy chuỗi nến ngày (`1D`) thực tế cho một mã cổ phiếu."""
        norm_symbol = symbol.strip().upper()
        exchange = DEFAULT_REAL_VN_STOCKS.get(norm_symbol, ("HOSE", f"Cổ phiếu {norm_symbol}", "Cổ phiếu niêm yết"))[0]

        now_ts = int(time.time())
        from_ts = now_ts - max(30, lookback_days) * 86400

        headers = {
            "User-Agent": "Mozilla/5.0",
        }
        params = {
            "symbol": norm_symbol,
            "resolution": "D",
            "from": from_ts,
            "to": now_ts,
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.get(self.endpoint_url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("s") != "ok":
            return []

        timestamps = payload.get("t") or []
        opens = payload.get("o") or []
        highs = payload.get("h") or []
        lows = payload.get("l") or []
        closes = payload.get("c") or []
        volumes = payload.get("v") or []

        rows: List[ValidatedOhlcvRow] = []
        seen_dates = set()

        for idx, ts in enumerate(timestamps):
            try:
                trading_dt = datetime.fromtimestamp(int(ts), tz=VN_TZ).date()
                if trading_dt in seen_dates:
                    continue

                raw_o = _to_vnd_decimal(opens[idx])
                raw_h = _to_vnd_decimal(highs[idx])
                raw_l = _to_vnd_decimal(lows[idx])
                raw_c = _to_vnd_decimal(closes[idx])
                vol = max(0, int(float(volumes[idx])))

                if raw_o <= 0 or raw_c <= 0:
                    continue

                high_p = max(raw_h, raw_o, raw_c)
                low_p = min(raw_l, raw_o, raw_c)
                if low_p <= 0:
                    low_p = min(raw_o, raw_c)

                seen_dates.add(trading_dt)
                rows.append(
                    ValidatedOhlcvRow(
                        row_number=idx + 1,
                        symbol=norm_symbol,
                        exchange=exchange,
                        trading_date=trading_dt,
                        open=raw_o,
                        high=high_p,
                        low=low_p,
                        close=raw_c,
                        adjusted_close=raw_c,
                        volume=vol,
                        data_label="REAL_MARKET_EOD",
                    )
                )
            except Exception:
                continue

        rows.sort(key=lambda r: r.trading_date)
        return rows
