# Ngày tạo: 2026-11-03
# Mục đích: Khởi tạo dữ liệu mẫu ban đầu (Idempotent Seed) cho hệ thống Personal AI Trading Assistant.
# Lý do: Mọi dữ liệu mẫu phải gắn nhãn rõ ràng là SAMPLE hoặc SIMULATED theo Quy tắc 7 trong Implementation Plan.

import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

# Cho phép chạy script từ thư mục gốc hoặc từ trong container
BACKEND_DIR = Path(__file__).resolve().parents[2] / "src" / "backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.market_data.models import DataSource, Stock  # noqa: E402
from app.portfolio.models import Account, CashTransaction  # noqa: E402
from app.strategies.models import Strategy, StrategyVersion  # noqa: E402
from app.system.models import AppSetting, RiskConfig  # noqa: E402

SAMPLE_STOCKS = [
    ("FPT", "HOSE", "[SAMPLE] CTCP FPT (Dữ liệu mẫu thử nghiệm)", "Technology"),
    ("VCB", "HOSE", "[SAMPLE] Ngân hàng TMCP Ngoại thương Việt Nam (Dữ liệu mẫu)", "Banking"),
    ("HPG", "HOSE", "[SAMPLE] CTCP Tập đoàn Hòa Phát (Dữ liệu mẫu)", "Materials"),
    ("ACB", "HOSE", "[SAMPLE] Ngân hàng TMCP Á Châu (Dữ liệu mẫu)", "Banking"),
    ("PVS", "HNX", "[SAMPLE] Tổng CTCP Dịch vụ Kỹ thuật Dầu khí Việt Nam (Dữ liệu mẫu)", "Energy"),
]

DEFAULT_RISK_CONFIG = {
    "max_position_percent": 20,
    "max_risk_per_trade_percent": 1,
    "max_daily_loss_percent": 2,
    "max_open_positions": 5,
    "max_portfolio_allocation_percent": 70,
    "require_human_approval": True,
    "trading_enabled": True,
    "environment_label": "SIMULATED_PAPER_MVP",
}


def run_seed() -> None:
    """Chạy seed dữ liệu khởi tạo một cách idempotent (chạy nhiều lần không tạo bản ghi trùng)."""
    settings = get_settings()
    with SessionLocal() as session:
        # 1. Seed DataSource mẫu có nhãn SAMPLE
        existing_source = session.scalar(
            select(DataSource).where(DataSource.name == "CSV_SAMPLE_SOURCE")
        )
        if not existing_source:
            session.add(
                DataSource(
                    name="CSV_SAMPLE_SOURCE",
                    provider_type="CSV",
                    license_notes="SAMPLE / SIMULATED DATA ONLY — Không phải dữ liệu giao dịch thời gian thực.",
                )
            )

        # 2. Seed danh sách mã cổ phiếu mẫu có nhãn [SAMPLE]
        for symbol, exchange, company_name, sector in SAMPLE_STOCKS:
            existing_stock = session.scalar(select(Stock).where(Stock.symbol == symbol))
            if not existing_stock:
                session.add(
                    Stock(
                        symbol=symbol,
                        exchange=exchange,
                        company_name=company_name,
                        sector=sector,
                        is_active=True,
                    )
                )

        # 3. Seed cấu hình rủi ro mặc định (Mục 9.1)
        existing_risk = session.scalar(
            select(RiskConfig).where(RiskConfig.name == "DEFAULT_PAPER_RISK_CONFIG")
        )
        if not existing_risk:
            session.add(
                RiskConfig(
                    name="DEFAULT_PAPER_RISK_CONFIG",
                    configuration=DEFAULT_RISK_CONFIG,
                    is_active=True,
                )
            )

        # 4. Seed tài khoản Paper mặc định (30.000.000 VNĐ) và bút toán sổ cái gốc
        existing_account = session.scalar(
            select(Account).where(Account.account_name == "DEFAULT_PAPER_ACCOUNT")
        )
        if not existing_account:
            initial_cap = Decimal(str(settings.INITIAL_PAPER_CAPITAL))
            paper_account = Account(
                account_name="DEFAULT_PAPER_ACCOUNT",
                initial_capital=initial_cap,
                cash_balance=initial_cap,
                currency="VND",
                account_type="PAPER",
            )
            session.add(paper_account)
            session.flush()

            session.add(
                CashTransaction(
                    account_id=paper_account.id,
                    transaction_type="INITIAL_DEPOSIT",
                    amount=initial_cap,
                    reference_type="SEED_INIT",
                    reference_id=paper_account.id,
                    description="[SIMULATED] Vốn giả lập khởi tạo cho tài khoản Paper Trading MVP",
                )
            )

        # 5. Seed 2 chiến lược mặc định (Trend Following & Pullback)
        for strat_name, strat_type, config_json in [
            (
                "Trend Following EOD",
                "TREND_FOLLOWING",
                {
                    "ma_fast": 20,
                    "ma_slow": 50,
                    "rsi_min": 50,
                    "rsi_max": 70,
                    "volume_multiplier": "1.2",
                    "exit_rule": "CLOSE_BELOW_MA20_OR_STOP_LOSS",
                },
            ),
            (
                "Pullback to Support EOD",
                "PULLBACK",
                {
                    "trend_ma": 50,
                    "pullback_zone_ma": 20,
                    "rsi_recovery_threshold": 45,
                    "exit_rule": "CLOSE_BELOW_MA50_OR_STOP_LOSS",
                },
            ),
        ]:
            strategy = session.scalar(select(Strategy).where(Strategy.name == strat_name))
            if not strategy:
                strategy = Strategy(
                    name=strat_name,
                    description=f"[SAMPLE CONFIG] Chiến lược {strat_name} cho Daily Trading.",
                    strategy_type=strat_type,
                    is_active=True,
                )
                session.add(strategy)
                session.flush()

                session.add(
                    StrategyVersion(
                        strategy_id=strategy.id,
                        version=1,
                        configuration=config_json,
                        code_version="0.1.0",
                    )
                )

        # 6. Seed AppSetting đánh dấu chế độ an toàn
        existing_setting = session.scalar(
            select(AppSetting).where(AppSetting.key == "system.safety_mode")
        )
        if not existing_setting:
            session.add(
                AppSetting(
                    key="system.safety_mode",
                    value={
                        "mode": "PAPER_TRADING_ONLY",
                        "live_broker_allowed": False,
                        "require_human_approval": True,
                        "data_notice": "SAMPLE_AND_HISTORICAL_CSV_ONLY",
                    },
                )
            )

        session.commit()
        print("Seed initial data completed successfully (Idempotent, marked SAMPLE/SIMULATED).")


if __name__ == "__main__":
    run_seed()
