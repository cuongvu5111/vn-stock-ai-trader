# Ngày tạo: 2026-11-03
# Mục đích: Script CLI chạy mô phỏng Backtest chống look-ahead cho một mã cổ phiếu và in báo cáo chi tiết.

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "src" / "backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.backtesting.service import BacktestService  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.schemas.strategy import BacktestCreateRequest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chạy Backtest chiến lược giao dịch EOD (Chống Look-Ahead Bias, khớp từ T+1 Open)."
    )
    parser.add_argument("--symbol", required=True, help="Mã cổ phiếu (VD: FPT)")
    parser.add_argument(
        "--strategy",
        default="TREND_FOLLOWING",
        choices=["TREND_FOLLOWING", "PULLBACK"],
        help="Loại chiến lược",
    )
    parser.add_argument("--start-date", required=True, help="Ngày bắt đầu YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Ngày kết thúc YYYY-MM-DD")
    parser.add_argument("--capital", default="30000000", help="Vốn giả lập ban đầu (VNĐ)")
    args = parser.parse_args()

    payload = BacktestCreateRequest(
        symbol=args.symbol,
        strategy_type=args.strategy,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        initial_capital=Decimal(args.capital),
    )

    with SessionLocal() as session:
        service = BacktestService(session=session)
        result = service.create_and_run_backtest(payload)
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
