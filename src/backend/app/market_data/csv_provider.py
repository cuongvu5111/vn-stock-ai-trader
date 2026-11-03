# Ngày tạo: 2026-11-03
# Mục đích: Triển khai CsvMarketDataProvider tuân thủ MarketDataProvider Protocol.
# Lý do: Tách biệt logic đọc/băm file CSV khỏi tầng xử lý nghiệp vụ và database.

import csv
import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Tuple


class CsvMarketDataProvider:
    """Adapter đọc dữ liệu OHLCV theo ngày từ file CSV hoặc chuỗi nội dung CSV."""

    provider_name: str = "CSV"

    def load_daily_ohlcv(self, source_identifier: str) -> List[Dict[str, Any]]:
        """Đọc danh sách dòng từ đường dẫn file CSV trên đĩa."""
        rows, _ = self.load_from_file(Path(source_identifier))
        return rows

    def load_from_file(self, file_path: Path) -> Tuple[List[Dict[str, Any]], str]:
        """Đọc từ file CSV và trả về (danh_sách_dòng_dict, sha256_checksum)."""
        raw_bytes = file_path.read_bytes()
        return self.load_from_bytes(raw_bytes)

    def load_from_bytes(self, content_bytes: bytes) -> Tuple[List[Dict[str, Any]], str]:
        """Đọc từ mảng bytes CSV (UTF-8 / UTF-8-SIG) và tính mã băm SHA-256."""
        checksum = hashlib.sha256(content_bytes).hexdigest()
        text_content = content_bytes.decode("utf-8-sig")
        return self.load_from_string(text_content, precomputed_checksum=checksum)

    def load_from_string(
        self, csv_text: str, precomputed_checksum: str | None = None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Phân tích chuỗi CSV thành danh sách dict và trả về kèm SHA-256 checksum."""
        checksum = precomputed_checksum or hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        stream = io.StringIO(csv_text)
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            return [], checksum
        rows: List[Dict[str, Any]] = [dict(row) for row in reader]
        return rows, checksum
