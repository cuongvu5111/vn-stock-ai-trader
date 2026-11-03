# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa các Adapter Interfaces (Protocols) để dễ dàng hoán đổi provider mà không sửa logic nghiệp vụ.
# Lý do: Tuân thủ Mục 3.4 trong Implementation Plan (MarketDataProvider, BrokerAdapter, AiAnalysisProvider).

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Protocol


class MarketDataProvider(Protocol):
    """Interface chuẩn cho nhà cung cấp dữ liệu thị trường (CSV, API có bản quyền)."""

    provider_name: str

    def load_daily_ohlcv(self, source_identifier: str) -> List[Dict[str, Any]]:
        """Đọc và chuẩn hóa dữ liệu OHLCV theo ngày từ nguồn cung cấp."""
        ...


class BrokerAdapter(Protocol):
    """Interface chuẩn cho Broker (MVP chỉ triển khai PaperBrokerAdapter, không có Live Broker)."""

    broker_name: str

    def submit_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: Decimal | None = None,
    ) -> Dict[str, Any]:
        """Gửi lệnh sang môi trường mô phỏng Paper Trading."""
        ...


class AiAnalysisProvider(Protocol):
    """Interface chuẩn cho bộ giải thích tín hiệu bằng AI (Isolated, Read-only context)."""

    provider_name: str
    model_name: str

    def analyze_signal(
        self,
        symbol: str,
        as_of_date: date,
        input_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Sinh báo cáo giải thích định dạng JSON có trích dẫn nguồn."""
        ...
