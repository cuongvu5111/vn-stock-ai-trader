# Ngày tạo: 2026-11-03
# Mục đích: Script CLI hỗ trợ import dữ liệu OHLCV ngày từ file CSV vào PostgreSQL một cách idempotent.
# Lý do: Hỗ trợ vận hành trực tiếp từ dòng lệnh và kiểm tra nhanh chất lượng dữ liệu CSV.

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "src" / "backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal  # noqa: E402
from app.market_data.service import MarketDataService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import dữ liệu giá OHLCV ngày từ CSV vào hệ thống Personal AI Trading Assistant."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Đường dẫn tới file CSV cần import (ví dụ: database/seeds/sample_ohlcv_data.csv)",
    )
    parser.add_argument(
        "--source",
        default="CSV_SAMPLE_SOURCE",
        help="Tên nguồn dữ liệu trong market.data_sources",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        default=True,
        help="Đánh dấu dữ liệu là SAMPLE / SIMULATED",
    )
    args = parser.parse_args()

    csv_path = Path(args.file)
    if not csv_path.exists():
        print(f"Lỗi: Không tìm thấy file CSV tại '{csv_path}'", file=sys.stderr)
        sys.exit(1)

    csv_text = csv_path.read_text(encoding="utf-8-sig")

    with SessionLocal() as session:
        service = MarketDataService(session=session)
        result = service.import_csv_content(
            csv_text=csv_text,
            file_name=csv_path.name,
            source_name=args.source,
            is_sample=args.sample,
        )
        print(
            json.dumps(
                result.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
