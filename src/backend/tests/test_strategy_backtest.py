# Ngày tạo: 2026-11-03
# Mục đích: Bộ kiểm thử toàn diện cho Sprint 4 — Strategy & Backtesting.
# Lý do: Xác minh toàn bộ tiêu chí nghiệm thu của Sprint 4:
#   1. Tín hiệu tạo sau phiên T KHÔNG được khớp ở giá đóng cửa phiên T mà chỉ khớp sớm nhất vào giá mở cửa phiên T+1.
#   2. Backtest tái lập được 100% (deterministic reproducibility) với cùng input/version.
#   3. Tính đúng phí mua/bán, thuế bán, slippage, giới hạn lô 100 cổ phiếu và sức mua tiền mặt.
#   4. Đầy đủ metrics, benchmark comparison và walk-forward time splits.
#   5. Cả 2 chiến lược Trend Following & Pullback hoạt động đúng qua Scanner/Signals/Backtest APIs.

from datetime import date, timedelta
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtesting.engine import run_backtest_simulation
from app.core.database import Base, get_db_session
from app.indicators.calculator import IndicatorPoint, OhlcvBar
from app.main import app
from app.strategies.engine import (
    BaseTradingStrategy,
    EvaluatedSignal,
    PullbackStrategy,
    TrendFollowingStrategy,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(_type, _compiler, **_kw) -> str:
    return "INTEGER"


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "market": None,
                "analysis": None,
                "strategy": None,
                "trading": None,
                "portfolio": None,
                "system": None,
            }
        },
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def test_client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class _DeterministicSignalOnDateStrategy(BaseTradingStrategy):
    """
    Chiến lược giả lập phục vụ kiểm thử chính xác quy tắc T+1:
    - Phát tín hiệu BUY vào cuối ngày `buy_signal_date` (T).
    - Phát tín hiệu SELL vào cuối ngày `sell_signal_date` (T_sell).
    """

    strategy_type = "TEST_T_PLUS_1"

    def __init__(self, buy_signal_date: date, sell_signal_date: date) -> None:
        super().__init__(strategy_id="test-strat", strategy_version=1)
        self.buy_signal_date = buy_signal_date
        self.sell_signal_date = sell_signal_date

    def evaluate_bar(
        self,
        symbol: str,
        bar: OhlcvBar,
        indicator: IndicatorPoint,
        source_data_version: str = "TEST",
    ) -> EvaluatedSignal:
        action = "HOLD"
        stop_loss = None
        if bar.trading_date == self.buy_signal_date:
            action = "BUY"
            stop_loss = Decimal("10000.0000")
        elif bar.trading_date == self.sell_signal_date:
            action = "SELL"

        return EvaluatedSignal(
            symbol=symbol,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            signal_date=bar.trading_date,
            data_as_of=bar.trading_date,
            action=action,
            score=Decimal("80.00"),
            reference_price=bar.close,
            stop_loss=stop_loss,
            reasons=[f"Signal {action} on {bar.trading_date}"],
            warnings=[],
            source_data_version=source_data_version,
            indicators_snapshot={},
        )


def test_signal_on_day_t_never_fills_at_close_t_and_fills_at_open_t_plus_1() -> None:
    """
    Acceptance Criteria quan trọng nhất của Sprint 4:
    - Có test xác minh signal ngày T không được khớp tại close ngày T nếu signal chỉ được tạo sau phiên.
    - Signal BUY tạo cuối ngày T (2026-05-02, close = 50,000) bắt buộc phải khớp tại ngày T+1 (2026-05-03, open = 55,000 + slippage).
    - Signal SELL tạo cuối ngày T_sell (2026-05-04, close = 60,000) bắt buộc phải khớp tại ngày T_sell+1 (2026-05-05, open = 58,000 - slippage).
    """
    bars = [
        OhlcvBar(date(2026, 5, 1), Decimal("48000"), Decimal("49000"), Decimal("47000"), Decimal("48500"), 1000000),
        # Ngày T = 2026-05-02: phát tín hiệu BUY sau khi đóng cửa ở giá 50,000
        OhlcvBar(date(2026, 5, 2), Decimal("49000"), Decimal("51000"), Decimal("48500"), Decimal("50000"), 1500000),
        # Ngày T+1 = 2026-05-03: giá mở cửa nhảy gap lên 55,000 -> lệnh phải khớp tại 55,000 * (1 + slippage)
        OhlcvBar(date(2026, 5, 3), Decimal("55000"), Decimal("57000"), Decimal("54000"), Decimal("56500"), 1800000),
        # Ngày T_sell = 2026-05-04: phát tín hiệu SELL sau khi đóng cửa ở giá 60,000
        OhlcvBar(date(2026, 5, 4), Decimal("57000"), Decimal("61000"), Decimal("56500"), Decimal("60000"), 2000000),
        # Ngày T_sell+1 = 2026-05-05: mở cửa ở giá 58,000 -> lệnh bán phải khớp tại 58,000 * (1 - slippage)
        OhlcvBar(date(2026, 5, 5), Decimal("58000"), Decimal("59000"), Decimal("57000"), Decimal("58500"), 1400000),
    ]

    strat = _DeterministicSignalOnDateStrategy(
        buy_signal_date=date(2026, 5, 2),
        sell_signal_date=date(2026, 5, 4),
    )

    result = run_backtest_simulation(
        symbol="FPT",
        bars=bars,
        strategy=strat,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
        initial_capital=Decimal("30000000.00"),
        fee_rate=Decimal("0.0015"),      # 0.15%
        tax_rate=Decimal("0.0010"),      # 0.10%
        slippage_bps=Decimal("10.0000"), # 0.10% = 0.001
        lot_size=100,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]

    # Xác minh ngày tín hiệu là 2026-05-02 nhưng ngày khớp lệnh mua (entry_date) là 2026-05-03 (T+1)
    assert trade.signal_date == date(2026, 5, 2)
    assert trade.entry_date == date(2026, 5, 3)
    assert trade.entry_date != date(2026, 5, 2)

    # Giá khớp mua phải tính từ Open ngày T+1 (55,000 * 1.001 = 55,055.0000), tuyệt đối không phải Close ngày T (50,000)
    assert trade.entry_price == Decimal("55055.0000")
    assert trade.entry_price != Decimal("50000.0000")

    # Ngày khớp bán là 2026-05-05 (T_sell + 1) ở giá Open 58,000 * (1 - 0.001) = 57,942.0000
    assert trade.exit_date == date(2026, 5, 5)
    assert trade.exit_price == Decimal("57942.0000")
    assert trade.exit_reason == "STRATEGY_SIGNAL_NEXT_OPEN"

    # Kiểm tra quy tắc lô chẵn 100 cổ phiếu:
    # Vốn 30,000,000 / (55,055 * 1.0015 * 100) = 5.44 lô -> làm tròn xuống = 500 cổ phiếu
    assert trade.quantity == 500
    assert trade.quantity % 100 == 0

    # Kiểm tra phí & thuế:
    # Giá trị mua = 500 * 55,055 = 27,527,500 -> phí mua 0.15% = 41,291.25
    # Giá trị bán = 500 * 57,942 = 28,971,000 -> phí bán 0.15% = 43,456.50; thuế bán 0.10% = 28,971.00
    # Tổng phí = 41,291.25 + 43,456.50 = 84,747.75
    assert trade.fees == Decimal("84747.75")
    assert trade.taxes == Decimal("28971.00")


def test_lot_size_and_cash_constraint_blocks_unaffordable_order() -> None:
    """Kiểm tra khi vốn giả lập không đủ mua tối thiểu 1 lô (100 cổ phiếu) thì lệnh không được khớp."""
    bars = [
        OhlcvBar(date(2026, 5, 1), Decimal("100000"), Decimal("101000"), Decimal("99000"), Decimal("100000"), 1000000),
        OhlcvBar(date(2026, 5, 2), Decimal("100000"), Decimal("102000"), Decimal("99500"), Decimal("101000"), 1000000),
    ]
    strat = _DeterministicSignalOnDateStrategy(
        buy_signal_date=date(2026, 5, 1),
        sell_signal_date=date(2026, 5, 2),
    )

    # 1 lô 100 cổ phiếu giá 100,000 cần > 10,000,000 VNĐ; cấp vốn chỉ 5,000,000 VNĐ
    result = run_backtest_simulation(
        symbol="VCB",
        bars=bars,
        strategy=strat,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
        initial_capital=Decimal("5000000.00"),
        lot_size=100,
    )

    assert len(result.trades) == 0
    assert result.metrics["unfilled_orders_count"] == 1
    assert result.final_nav == Decimal("5000000.00")


def test_trend_following_and_pullback_strategies_generate_buy_and_sell_signals() -> None:
    """Kiểm tra cả 2 chiến lược TrendFollowing và Pullback đều sinh đúng tín hiệu BUY và SELL khi thỏa điều kiện."""
    tf_strat = TrendFollowingStrategy(strategy_id="tf-1", strategy_version=1)
    pb_strat = PullbackStrategy(strategy_id="pb-1", strategy_version=1)

    bar_date = date(2026, 7, 15)
    # Kịch bản 1: Hội tụ đủ điều kiện BUY của Trend Following (Close > MA20 > MA50, RSI 60, Volume > 1.2x VolAvg20)
    tf_bar = OhlcvBar(bar_date, Decimal("51000"), Decimal("53000"), Decimal("50800"), Decimal("52500"), 3000000)
    tf_ind = IndicatorPoint(
        trading_date=bar_date,
        ma20=Decimal("50000.0000"),
        ma50=Decimal("48000.0000"),
        ma200=Decimal("45000.0000"),
        ema20=Decimal("50200.0000"),
        ema50=Decimal("48200.0000"),
        rsi14=Decimal("60.0000"),
        macd=Decimal("500.000000"),
        macd_signal=Decimal("400.000000"),
        macd_histogram=Decimal("100.000000"),
        atr14=Decimal("800.0000"),
        volume_avg20=Decimal("2000000.00"),
        calculation_version="v1.0",
    )
    tf_buy_sig = tf_strat.evaluate_bar("FPT", tf_bar, tf_ind)
    assert tf_buy_sig.action == "BUY"
    assert tf_buy_sig.stop_loss == Decimal("50900.0000")  # 52500 - 2.0 * 800

    # Kịch bản 2: Điều kiện SELL của Trend Following khi Close thủng MA20
    tf_sell_bar = OhlcvBar(bar_date, Decimal("50000"), Decimal("50200"), Decimal("48800"), Decimal("49000"), 2500000)
    tf_sell_sig = tf_strat.evaluate_bar("FPT", tf_sell_bar, tf_ind)
    assert tf_sell_sig.action == "SELL"

    # Kịch bản 3: Điều kiện BUY của Pullback (Close > MA50, MA20 >= MA50, giá điều chỉnh sát MA20 = 50,000, nến xanh, RSI = 50)
    pb_bar = OhlcvBar(bar_date, Decimal("49900"), Decimal("50600"), Decimal("49800"), Decimal("50300"), 1800000)
    pb_ind = IndicatorPoint(
        trading_date=bar_date,
        ma20=Decimal("50000.0000"),
        ma50=Decimal("48000.0000"),
        ma200=None,
        ema20=Decimal("50000.0000"),
        ema50=Decimal("48000.0000"),
        rsi14=Decimal("50.0000"),
        macd=None,
        macd_signal=None,
        macd_histogram=None,
        atr14=Decimal("600.0000"),
        volume_avg20=Decimal("1500000.00"),
        calculation_version="v1.0",
    )
    pb_buy_sig = pb_strat.evaluate_bar("VCB", pb_bar, pb_ind)
    assert pb_buy_sig.action == "BUY"
    assert pb_buy_sig.stop_loss is not None


def test_scanner_and_backtest_api_end_to_end_reproducibility(test_client: TestClient) -> None:
    """
    Kiểm tra tích hợp qua REST API:
    1. Import 65 phiên dữ liệu cho mã FPT.
    2. Chạy POST /api/v1/scanner/run và GET /api/v1/signals.
    3. Chạy POST /api/v1/backtests hai lần liên tiếp và xác minh kết quả tái lập 100% (reproducible),
       đầy đủ metrics bắt buộc và walk_forward_splits.
    """
    lines = ["symbol,trading_date,open,high,low,close,volume,exchange,data_label"]
    start_d = date(2026, 3, 1)
    price = 50000
    for i in range(65):
        d = start_d + timedelta(days=i)
        # Tạo nhịp tăng có xen kẽ nhịp chỉnh nhỏ để RSI nằm trong vùng 55-68 và sau đó đảo chiều để đóng lệnh
        if i < 55:
            delta = 400 if (i % 4 != 0) else -250
        else:
            delta = -1200
        open_p = price
        close_p = max(10000, price + delta)
        high_p = max(open_p, close_p) + 300
        low_p = min(open_p, close_p) - 300
        vol = 3000000 if i == 52 else 1500000
        lines.append(
            f"FPT,{d.isoformat()},{open_p},{high_p},{low_p},{close_p},{vol},HOSE,SAMPLE"
        )
        price = close_p

    imp_resp = test_client.post(
        "/api/v1/market/imports",
        json={"csv_content": "\n".join(lines), "file_name": "fpt_65_days.csv"},
    )
    assert imp_resp.status_code == 201

    # Chạy Scanner tại phiên thứ 52 (2026-04-22)
    scan_date = (start_d + timedelta(days=52)).isoformat()
    scan_resp = test_client.post(
        "/api/v1/scanner/run",
        json={
            "symbols": ["FPT"],
            "strategy_type": "TREND_FOLLOWING",
            "as_of_date": scan_date,
        },
    )
    assert scan_resp.status_code == 200
    scan_data = scan_resp.json()
    assert scan_data["total_scanned"] == 1
    assert len(scan_data["signals"]) == 1

    # Kiểm tra GET /api/v1/signals
    sig_list = test_client.get("/api/v1/signals?symbol=FPT").json()
    assert sig_list["total"] >= 1

    # Chạy Backtest lần 1
    bt_payload = {
        "symbol": "FPT",
        "strategy_type": "TREND_FOLLOWING",
        "strategy_version": 1,
        "start_date": start_d.isoformat(),
        "end_date": (start_d + timedelta(days=64)).isoformat(),
        "initial_capital": "30000000.00",
        "fee_rate": "0.0015",
        "tax_rate": "0.0010",
        "slippage_bps": "10.0000",
    }
    bt_resp1 = test_client.post("/api/v1/backtests", json=bt_payload)
    assert bt_resp1.status_code == 201
    bt1 = bt_resp1.json()

    # Chạy Backtest lần 2 với cùng input/version -> phải tái lập 100% metrics & trades
    bt_resp2 = test_client.post("/api/v1/backtests", json=bt_payload)
    assert bt_resp2.status_code == 201
    bt2 = bt_resp2.json()

    assert bt1["metrics"] == bt2["metrics"]
    assert len(bt1["trades"]) == len(bt2["trades"])

    # Kiểm tra các trường bắt buộc trong metrics (Mục 8.2)
    required_metric_keys = {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "profit_factor",
        "expectancy_per_trade",
        "average_win",
        "average_loss",
        "number_of_trades",
        "exposure_time_in_market_pct",
        "turnover_pct",
        "total_fees",
        "total_taxes",
        "total_slippage_cost",
        "benchmark_buy_and_hold_return_pct",
        "walk_forward_splits",
    }
    assert required_metric_keys.issubset(set(bt1["metrics"].keys()))

    # Kiểm tra GET /api/v1/backtests/{id}
    get_bt = test_client.get(f"/api/v1/backtests/{bt1['id']}")
    assert get_bt.status_code == 200
    assert get_bt.json()["id"] == bt1["id"]
