# Ngày tạo: 2026-11-03
# Mục đích: Bộ kiểm thử Smoke Tests cho Sprint 1 — Foundation.
# Lý do: Xác minh cấu hình an toàn, endpoint /api/v1/health, X-Correlation-ID và 6 PostgreSQL schemas (24 bảng).

from decimal import Decimal
from sqlalchemy import Numeric
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.models_registry import POSTGRES_SCHEMAS, Base
from app.main import app


client = TestClient(app)


def test_health_endpoint_returns_expected_contract(monkeypatch) -> None:
    """Kiểm tra /api/v1/health trả về đúng cấu trúc, chế độ PAPER_ONLY và gắn X-Correlation-ID."""
    monkeypatch.setattr(
        "app.api.v1.health.check_database_connection",
        lambda: (True, "connected_mock_for_unit_test"),
    )

    custom_cid = "test-correlation-id-sprint-1"
    response = client.get("/api/v1/health", headers={"X-Correlation-ID": custom_cid})

    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == custom_cid

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["trading_mode"] == "PAPER_ONLY"
    assert payload["live_broker_enabled"] is False
    assert set(payload["registered_schemas"]) == set(POSTGRES_SCHEMAS)


def test_all_six_schemas_and_twenty_four_tables_registered() -> None:
    """Đảm bảo toàn bộ 6 schemas và 24 bảng theo đặc tả Mục 6 đã được đăng ký trong SQLAlchemy metadata."""
    tables = Base.metadata.tables
    discovered_schemas = {table.schema for table in tables.values()}

    assert discovered_schemas == {
        "market",
        "analysis",
        "strategy",
        "trading",
        "portfolio",
        "system",
    }

    expected_tables = {
        # market (4)
        "market.stocks",
        "market.data_sources",
        "market.import_batches",
        "market.daily_prices",
        # analysis (4)
        "analysis.analysis_runs",
        "analysis.technical_indicators",
        "analysis.stock_signals",
        "analysis.ai_reports",
        # strategy (4)
        "strategy.strategies",
        "strategy.strategy_versions",
        "strategy.backtest_runs",
        "strategy.backtest_trades",
        # trading (4)
        "trading.trade_proposals",
        "trading.approvals",
        "trading.orders",
        "trading.executions",
        # portfolio (4)
        "portfolio.accounts",
        "portfolio.positions",
        "portfolio.cash_transactions",
        "portfolio.daily_snapshots",
        # system (4)
        "system.risk_configs",
        "system.job_runs",
        "system.audit_logs",
        "system.app_settings",
    }

    assert set(tables.keys()) == expected_tables


def test_financial_columns_use_numeric_not_float() -> None:
    """Đảm bảo mọi cột tiền tệ và giá cổ phiếu đều dùng kiểu NUMERIC, không dùng Float."""
    numeric_columns_to_verify = [
        ("market.daily_prices", ["open", "high", "low", "close", "adjusted_close"]),
        ("analysis.stock_signals", ["score", "reference_price", "stop_loss"]),
        ("strategy.backtest_runs", ["initial_capital", "fee_rate", "tax_rate", "slippage_bps"]),
        ("strategy.backtest_trades", ["entry_price", "exit_price", "fees", "taxes", "pnl"]),
        ("trading.trade_proposals", ["limit_price", "stop_loss", "estimated_cost", "risk_amount"]),
        ("trading.orders", ["limit_price", "average_fill_price"]),
        ("trading.executions", ["price", "fee", "tax"]),
        ("portfolio.accounts", ["initial_capital", "cash_balance"]),
        ("portfolio.positions", ["average_cost"]),
        ("portfolio.cash_transactions", ["amount"]),
        ("portfolio.daily_snapshots", ["cash_balance", "market_value", "nav", "unrealized_pnl", "realized_pnl"]),
    ]

    for table_key, col_names in numeric_columns_to_verify:
        table = Base.metadata.tables[table_key]
        for col_name in col_names:
            col = table.c[col_name]
            assert isinstance(
                col.type, Numeric
            ), f"Cột {table_key}.{col_name} phải dùng kiểu NUMERIC, phát hiện: {type(col.type)}"


def test_default_settings_use_decimal_for_capital() -> None:
    """Kiểm tra vốn giả lập mặc định là kiểu Decimal."""
    settings = get_settings()
    assert isinstance(settings.INITIAL_PAPER_CAPITAL, Decimal)
    assert settings.INITIAL_PAPER_CAPITAL == Decimal("30000000.00")
