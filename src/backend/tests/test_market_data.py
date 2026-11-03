# Ngày tạo: 2026-11-03
# Mục đích: Bộ kiểm thử Unit & Integration Tests cho Sprint 2 — Market Data.
# Lý do: Xác minh toàn bộ tiêu chí nghiệm thu của Sprint 2:
#   1. Import cùng file CSV hai lần không nhân đôi dữ liệu (Idempotency).
#   2. Dữ liệu lỗi (giá âm, high < low, low > open, volume âm, trùng dòng) bị từ chối và báo cáo rõ ràng.
#   3. Phát hiện ngày giao dịch bị khuyết (missing_weekdays warning).
#   4. Truy vấn lịch sử OHLCV theo symbol & date range, trả về đúng nguồn (source_id) và batch (import_batch_id).

from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db_session
from app.main import app


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kw) -> str:
    """Cho phép SQLite in-memory biên dịch cột JSONB của PostgreSQL thành JSON khi chạy unit test."""
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(_type, _compiler, **_kw) -> str:
    """Cho phép khóa chính BigInteger tự động tăng (INTEGER PRIMARY KEY) trên SQLite in-memory."""
    return "INTEGER"


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """
    Tạo SQLite in-memory engine dùng schema_translate_map để ánh xạ 6 PostgreSQL schemas
    về default schema khi chạy test nhanh trên máy local không cần kết nối Postgres.
    """
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
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def test_client(db_session: Session) -> Generator[TestClient, None, None]:
    """Cấu hình TestClient sử dụng db_session cô lập cho từng test case."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_stock_crud_and_filtering(test_client: TestClient) -> None:
    """Kiểm tra thêm mới, cập nhật và lọc danh sách cổ phiếu."""
    create_resp = test_client.post(
        "/api/v1/stocks",
        json={
            "symbol": "fpt",
            "exchange": "hose",
            "company_name": "CTCP FPT",
            "sector": "Technology",
            "is_sample": True,
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["symbol"] == "FPT"
    assert created["exchange"] == "HOSE"
    assert created["company_name"].startswith("[SAMPLE]")

    # Tạo trùng mã phải trả về 409 Conflict
    dup_resp = test_client.post(
        "/api/v1/stocks",
        json={"symbol": "FPT", "exchange": "HOSE"},
    )
    assert dup_resp.status_code == 409

    # Cập nhật thông tin ngành
    patch_resp = test_client.patch(
        "/api/v1/stocks/FPT",
        json={"sector": "IT & Telecom"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["sector"] == "IT & Telecom"

    # Danh sách cổ phiếu
    list_resp = test_client.get("/api/v1/stocks?exchange=HOSE&q=fp")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 1
    assert data["items"][0]["symbol"] == "FPT"


def test_idempotent_csv_import_and_provenance_tracking(test_client: TestClient) -> None:
    """
    Acceptance Criteria 1, 3, 4:
    - Import cùng một file CSV hai lần không nhân đôi dữ liệu.
    - Có thể query OHLCV theo symbol/date range.
    - Biết được nguồn (source_id, source_name) và batch (import_batch_id) của mỗi record.
    """
    sample_csv = (
        "symbol,trading_date,open,high,low,close,adjusted_close,volume,exchange,data_label\n"
        "FPT,2026-09-01,130000.0000,131500.0000,129200.0000,131000.0000,131000.0000,2450000,HOSE,SAMPLE\n"
        "FPT,2026-09-02,131000.0000,132800.0000,130500.0000,132200.0000,132200.0000,2610000,HOSE,SAMPLE\n"
        "FPT,2026-09-03,132200.0000,133500.0000,131800.0000,133000.0000,133000.0000,2890000,HOSE,SAMPLE\n"
    )

    # Lần import thứ 1
    resp1 = test_client.post(
        "/api/v1/market/imports",
        json={
            "csv_content": sample_csv,
            "file_name": "fpt_sample.csv",
            "source_name": "CSV_SAMPLE_SOURCE",
            "is_sample": True,
        },
    )
    assert resp1.status_code == 201
    batch1 = resp1.json()
    assert batch1["status"] == "COMPLETED"
    assert batch1["rows_read"] == 3
    assert batch1["rows_inserted"] == 3
    assert batch1["rows_rejected"] == 0
    assert len(batch1["checksum"]) == 64

    # Lần import thứ 2 với đúng cùng nội dung file CSV
    resp2 = test_client.post(
        "/api/v1/market/imports",
        json={
            "csv_content": sample_csv,
            "file_name": "fpt_sample.csv",
            "source_name": "CSV_SAMPLE_SOURCE",
            "is_sample": True,
        },
    )
    assert resp2.status_code == 201
    batch2 = resp2.json()
    assert batch2["status"] == "COMPLETED"
    assert batch2["checksum"] == batch1["checksum"]
    assert batch2["rows_inserted"] == 0
    assert batch2["error_detail"]["rows_updated_or_idempotent"] == 3

    # Kiểm tra tổng số bản ghi trong DB vẫn chỉ là 3 (không bị nhân đôi thành 6)
    overview = test_client.get("/api/v1/market/overview").json()
    assert overview["total_daily_price_records"] == 3
    assert overview["latest_trading_date"] == "2026-09-03"

    # Truy vấn theo khoảng ngày [2026-09-02, 2026-09-03]
    hist_resp = test_client.get(
        "/api/v1/stocks/FPT/history?start_date=2026-09-02&end_date=2026-09-03"
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert history["total_records"] == 2
    first_item = history["items"][0]
    assert first_item["trading_date"] == "2026-09-02"
    assert first_item["close"] == "132200.0000"
    assert first_item["source_name"] == "CSV_SAMPLE_SOURCE"
    assert first_item["source_id"] == batch2["source_id"]
    assert first_item["import_batch_id"] == batch2["id"]


def test_invalid_ohlcv_rows_rejected_and_missing_dates_detected(test_client: TestClient) -> None:
    """
    Acceptance Criteria 2:
    - Dữ liệu lỗi (giá âm, high < low, high < open, low > close, volume âm, duplicate trong batch)
      phải bị từ chối và báo cáo chi tiết trong error_detail, không âm thầm chấp nhận.
    - Phát hiện ngày làm việc bị khuyết (2026-09-02 bị thiếu giữa 2026-09-01 và 2026-09-03).
    """
    mixed_csv = (
        "symbol,trading_date,open,high,low,close,volume,exchange,data_label\n"
        # Dòng 2: Hợp lệ (Thứ Ba 2026-09-01)
        "VCB,2026-09-01,91000,92000,90500,91500,1500000,HOSE,SAMPLE\n"
        # Dòng 3: Hợp lệ nhưng nhảy cóc qua Thứ Tư 2026-09-02 sang Thứ Năm 2026-09-03 -> tạo warning missing_weekdays
        "VCB,2026-09-03,91500,92500,91000,92000,1600000,HOSE,SAMPLE\n"
        # Dòng 4: Trùng lặp (VCB, 2026-09-03) ngay trong cùng file
        "VCB,2026-09-03,91500,92500,91000,92000,1600000,HOSE,SAMPLE\n"
        # Dòng 5: Giá âm
        "VCB,2026-09-04,-91000,92000,90000,91500,1000000,HOSE,SAMPLE\n"
        # Dòng 6: high < low
        "VCB,2026-09-07,91000,89000,90000,91000,1000000,HOSE,SAMPLE\n"
        # Dòng 7: low > close
        "VCB,2026-09-08,91000,93000,91500,91000,1000000,HOSE,SAMPLE\n"
        # Dòng 8: volume âm
        "VCB,2026-09-09,91000,92000,90500,91500,-500,HOSE,SAMPLE\n"
    )

    resp = test_client.post(
        "/api/v1/market/imports",
        json={
            "csv_content": mixed_csv,
            "file_name": "vcb_mixed_errors.csv",
            "source_name": "CSV_SAMPLE_SOURCE",
        },
    )
    assert resp.status_code == 201
    batch = resp.json()
    assert batch["status"] == "COMPLETED_WITH_ERRORS"
    assert batch["rows_read"] == 7
    assert batch["rows_inserted"] == 2
    assert batch["rows_rejected"] == 5

    rejected_codes = [item["error_code"] for item in batch["error_detail"]["rejected_rows"]]
    assert rejected_codes == [
        "DUPLICATE_IN_BATCH",
        "INVALID_PRICE",
        "INVALID_OHLC_HIGH_LOW",
        "INVALID_OHLC_LOW_BOUND",
        "NEGATIVE_VOLUME",
    ]

    # Kiểm tra phát hiện ngày làm việc bị thiếu (2026-09-02)
    missing_weekdays = batch["error_detail"]["warnings"]["missing_weekdays"]
    assert "VCB" in missing_weekdays
    assert "2026-09-02" in missing_weekdays["VCB"]

    # Kiểm tra endpoint GET /api/v1/market/imports/{id}
    status_resp = test_client.get(f"/api/v1/market/imports/{batch['id']}")
    assert status_resp.status_code == 200
    assert status_resp.json()["rows_rejected"] == 5

    # Xác nhận chỉ có đúng 2 dòng hợp lệ được lưu vào DB
    history = test_client.get("/api/v1/stocks/VCB/history").json()
    assert history["total_records"] == 2
