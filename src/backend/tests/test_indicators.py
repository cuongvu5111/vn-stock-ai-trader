# Ngày tạo: 2026-11-03
# Mục đích: Bộ kiểm thử toàn diện cho Sprint 3 — Technical Analysis.
# Lý do: Xác minh toàn bộ tiêu chí nghiệm thu của Sprint 3:
#   1. Kết quả deterministic và khớp với bộ dữ liệu tham chiếu đã biết.
#   2. Không tính indicator khi thiếu dữ liệu warm-up (trả về None).
#   3. Không dùng dữ liệu tương lai (No Look-Ahead Bias).
#   4. Xử lý đúng các trường hợp biên: giá đi ngang (flat prices), thiếu dòng (short/missing rows), khối lượng bằng 0 (zero volume).
#   5. Lưu trữ idempotent kèm calculation_version và truy vấn qua API.

from datetime import date, timedelta
from decimal import Decimal
from typing import Generator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db_session
from app.indicators.calculator import OhlcvBar, calculate_indicator_series
from app.main import app


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


def _build_linear_bars(count: int, start_price: int = 10000, step: int = 100) -> List[OhlcvBar]:
    """Tạo chuỗi nến tăng tuyến tính để kiểm tra chính xác công thức toán học."""
    base_date = date(2026, 1, 1)
    bars: List[OhlcvBar] = []
    for i in range(count):
        close_p = Decimal(start_price + i * step)
        open_p = close_p - Decimal(50)
        high_p = close_p + Decimal(100)
        low_p = close_p - Decimal(100)
        bars.append(
            OhlcvBar(
                trading_date=base_date + timedelta(days=i),
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=100000 + i * 1000,
            )
        )
    return bars


def test_deterministic_and_known_reference_values() -> None:
    """
    Acceptance Criteria 1:
    - Kết quả deterministic (chạy 2 lần giống hệt nhau).
    - Khớp với giá trị toán học đã biết trên chuỗi tuyến tính:
      Với close_i = 10000 + i*100 (i = 0..39):
      + Tại index 19 (20 phiên đầu: 10000 .. 11900):
        SMA20 = EMA20 = (10000 + 11900) / 2 = 10950.0000
        VolumeAvg20 (100000 .. 119000) = 109500.00
      + Vì giá tăng đều mỗi ngày +100 (Loss = 0, Gain = 100):
        RSI14 từ index 14 trở đi = 100.0000
      + True Range mỗi phiên (i >= 1):
        high_i - low_i = 200; |high_i - close_{i-1}| = |(close_{i-1}+100+100) - close_{i-1}| = 200
        => TR_i = 200 => ATR14 từ index 14 trở đi = 200.0000
    """
    bars = _build_linear_bars(40)
    run_1 = calculate_indicator_series(bars, calculation_version="v1.0")
    run_2 = calculate_indicator_series(list(reversed(bars)), calculation_version="v1.0")

    assert run_1 == run_2

    pt_19 = run_1[19]
    assert pt_19.ma20 == Decimal("10950.0000")
    assert pt_19.ema20 == Decimal("10950.0000")
    assert pt_19.volume_avg20 == Decimal("109500.00")

    pt_14 = run_1[14]
    assert pt_14.rsi14 == Decimal("100.0000")
    assert pt_14.atr14 == Decimal("200.0000")


def test_warmup_periods_return_none_when_insufficient_data() -> None:
    """
    Acceptance Criteria 2:
    - Không tính indicator khi thiếu dữ liệu warm-up:
      + index 0..13: rsi14 và atr14 phải là None; từ index 14 khác None.
      + index 0..18: ma20, ema20, volume_avg20 phải là None; từ index 19 khác None.
      + index 0..24: macd phải là None; từ index 25 khác None.
      + index 0..32: macd_signal và macd_histogram phải là None; từ index 33 khác None.
      + với 40 phiên: ma50, ema50, ma200 luôn là None.
    """
    bars = _build_linear_bars(40)
    series = calculate_indicator_series(bars)

    for i in range(14):
        assert series[i].rsi14 is None
        assert series[i].atr14 is None
    assert series[14].rsi14 is not None
    assert series[14].atr14 is not None

    for i in range(19):
        assert series[i].ma20 is None
        assert series[i].ema20 is None
        assert series[i].volume_avg20 is None
    assert series[19].ma20 is not None
    assert series[19].ema20 is not None
    assert series[19].volume_avg20 is not None

    for i in range(25):
        assert series[i].macd is None
    assert series[25].macd is not None

    for i in range(33):
        assert series[i].macd_signal is None
        assert series[i].macd_histogram is None
    assert series[33].macd_signal is not None
    assert series[33].macd_histogram is not None

    for pt in series:
        assert pt.ma50 is None
        assert pt.ema50 is None
        assert pt.ma200 is None


def test_no_look_ahead_bias_when_future_bars_added() -> None:
    """
    Acceptance Criteria 3:
    - Không dùng dữ liệu tương lai: chỉ báo tại phiên thứ 35 khi tính trên tập 35 phiên
      phải giống hệt 100% với chỉ báo tại phiên thứ 35 khi thêm 15 phiên tương lai biến động cực mạnh.
    """
    base_bars = _build_linear_bars(35)
    series_as_of_35 = calculate_indicator_series(base_bars)

    future_shock_bars: List[OhlcvBar] = []
    last_date = base_bars[-1].trading_date
    for j in range(1, 16):
        shock_price = Decimal(999999 - j * 50000)
        future_shock_bars.append(
            OhlcvBar(
                trading_date=last_date + timedelta(days=j),
                open=shock_price,
                high=shock_price + Decimal(10000),
                low=shock_price - Decimal(10000),
                close=shock_price,
                volume=99999999,
            )
        )

    series_with_future = calculate_indicator_series(base_bars + future_shock_bars)

    for idx in range(35):
        assert series_as_of_35[idx] == series_with_future[idx]


def test_edge_cases_flat_prices_zero_volume_and_short_series() -> None:
    """
    Acceptance Criteria 4:
    - Kiểm thử trường hợp giá đi ngang (flat prices), khối lượng bằng 0 (zero volume) và chuỗi quá ngắn (missing/short rows).
    """
    base_date = date(2026, 2, 1)
    flat_bars = [
        OhlcvBar(
            trading_date=base_date + timedelta(days=i),
            open=Decimal("50000.0000"),
            high=Decimal("50000.0000"),
            low=Decimal("50000.0000"),
            close=Decimal("50000.0000"),
            volume=0,
        )
        for i in range(40)
    ]

    flat_series = calculate_indicator_series(flat_bars)
    last_pt = flat_series[-1]

    assert last_pt.ma20 == Decimal("50000.0000")
    assert last_pt.ema20 == Decimal("50000.0000")
    assert last_pt.rsi14 == Decimal("50.0000")
    assert last_pt.atr14 == Decimal("0.0000")
    assert last_pt.macd == Decimal("0.000000")
    assert last_pt.macd_signal == Decimal("0.000000")
    assert last_pt.macd_histogram == Decimal("0.000000")
    assert last_pt.volume_avg20 == Decimal("0.00")

    # Chuỗi ngắn chỉ có 5 dòng (ít hơn mọi ngưỡng warm-up)
    short_series = calculate_indicator_series(flat_bars[:5])
    assert len(short_series) == 5
    for pt in short_series:
        assert pt.ma20 is None
        assert pt.rsi14 is None
        assert pt.atr14 is None
        assert pt.macd is None


def test_indicators_api_persistence_and_idempotency(test_client: TestClient) -> None:
    """
    Kiểm tra luồng tích hợp:
    1. Import 35 phiên dữ liệu mẫu cho mã FPT.
    2. Gọi POST /api/v1/indicators/calculate hai lần liên tiếp (idempotent).
    3. Gọi GET /api/v1/stocks/FPT/indicators kiểm tra kết quả lưu trữ.
    """
    lines = ["symbol,trading_date,open,high,low,close,volume,exchange,data_label"]
    start_d = date(2026, 6, 1)
    for i in range(35):
        d = start_d + timedelta(days=i)
        c = 100000 + i * 500
        lines.append(
            f"FPT,{d.isoformat()},{c - 200},{c + 300},{c - 300},{c},{2000000 + i * 10000},HOSE,SAMPLE"
        )
    csv_payload = "\n".join(lines)

    imp_resp = test_client.post(
        "/api/v1/market/imports",
        json={"csv_content": csv_payload, "file_name": "fpt_35_days.csv"},
    )
    assert imp_resp.status_code == 201

    # Chạy tính toán chỉ báo lần 1
    calc1 = test_client.post(
        "/api/v1/indicators/calculate",
        json={"symbols": ["FPT"], "calculation_version": "v1.0"},
    )
    assert calc1.status_code == 200
    body1 = calc1.json()
    assert body1["status"] == "COMPLETED"
    assert body1["symbols_processed"] == 1
    assert body1["rows_upserted"] == 35

    # Chạy tính toán chỉ báo lần 2 (Idempotent update)
    calc2 = test_client.post(
        "/api/v1/indicators/calculate",
        json={"symbols": ["FPT"], "calculation_version": "v1.0"},
    )
    assert calc2.status_code == 200
    assert calc2.json()["rows_upserted"] == 35

    # Truy vấn lịch sử chỉ báo qua API
    get_resp = test_client.get("/api/v1/stocks/FPT/indicators?calculation_version=v1.0")
    assert get_resp.status_code == 200
    ind_history = get_resp.json()
    assert ind_history["total_records"] == 35

    items = ind_history["items"]
    assert items[0]["warm_up_core_ready"] is False
    assert items[18]["warm_up_core_ready"] is False
    assert items[19]["warm_up_core_ready"] is True
    assert items[34]["macd"] is not None
    assert items[34]["macd_signal"] is not None
    assert items[34]["macd_histogram"] is not None
