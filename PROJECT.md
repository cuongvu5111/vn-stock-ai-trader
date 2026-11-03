# PROJECT.md — Ngữ cảnh Dự án (Project Context)

> **Ngày khởi tạo:** 2026-11-03  
> **Mục đích:** Cung cấp ngữ cảnh chuẩn về công nghệ, kiến trúc, quy ước và nguyên tắc an toàn cho toàn bộ dự án **Personal AI Trading Assistant**.

---

## 1. Tổng quan Dự án
- **Tên dự án:** Personal AI Trading Assistant (`vn-stock-ai-trader`)
- **Thị trường mục tiêu:** Chứng khoán Việt Nam (`HOSE`, `HNX`, `UPCOM`)
- **Phong cách giao dịch:** Daily Trading / Swing ngắn hạn (phân tích dữ liệu EOD, nắm giữ từ vài ngày đến vài tuần)
- **Vốn giả lập mặc định:** `30.000.000 VNĐ` (cấu hình được)
- **Chế độ hoạt động (MVP):** **Paper Trading & Backtesting 100%**. Hệ thống phân tích, chấm điểm và đề xuất (`Trade Proposal`); con người bắt buộc phê duyệt (`Human Approval`) trước khi chuyển sang `Paper Broker`.

---

## 2. Tech Stack & Kiến trúc (Monorepo)
- **Kiến trúc:** Python Modular Monolith + Angular Dashboard + PostgreSQL 16.
- **Backend (`src/backend/`):**
  - Ngôn ngữ: Python 3.12 (tương thích `>=3.10` cho môi trường dev host)
  - Framework: FastAPI + Pydantic v2 + Pydantic Settings
  - ORM & Migration: SQLAlchemy 2.0 + Alembic + `psycopg` (v3)
  - Background Jobs: `APScheduler`
  - Logging: `structlog` (Structured JSON logs + `X-Correlation-ID`)
  - Testing: `pytest` + `httpx`
- **Database (`PostgreSQL 16`):**
  - Tên DB: `trading_db`
  - 6 Schemas logic: `market`, `analysis`, `strategy`, `trading`, `portfolio`, `system` (tổng cộng 22 bảng).
- **Frontend (`src/frontend/trading-dashboard/`):**
  - Framework: Angular (Standalone Components, TypeScript, SCSS)
- **Hạ tầng (`docker-compose.yml`):**
  - 3 containers chính: `postgres`, `trading-backend`, `trading-frontend`.

---

## 3. Các Nguyên tắc Bắt buộc (Non-Negotiable Rules)
1. **Không gửi lệnh thật (No Live Trading):** Tuyệt đối không kết nối API đặt lệnh của công ty chứng khoán thật trong MVP.
2. **Độ chính xác số học tài chính:** Mọi giá trị tiền tệ, giá cổ phiếu, phí, thuế, tỷ lệ trong Python phải dùng `decimal.Decimal` và trong PostgreSQL phải dùng `NUMERIC`. Không dùng `float` cho tính toán tài chính.
3. **Chống Look-ahead Bias:** Tín hiệu tạo sau phiên `T` chỉ được phép giả lập khớp từ phiên `T+1`.
4. **Cổng kiểm soát Rủi ro & Con người (Risk + Human Gate):**
   - Mọi đề xuất giao dịch phải qua `Risk Engine` kiểm tra khi tạo và **kiểm tra lại (re-validate)** ngay tại thời điểm người dùng nhấn `Approve`.
   - Module `ai` chỉ có quyền đọc dữ liệu và xuất báo cáo JSON theo schema; không có quyền tạo lệnh hoặc tự duyệt proposal.
5. **Nhãn dữ liệu mẫu:** Mọi dữ liệu tạo phục vụ demo/test phải gắn nhãn `SAMPLE` hoặc `SIMULATED`.
6. **Ngôn ngữ giao tiếp & tài liệu:** Sử dụng tiếng Việt rõ ràng, chuyên nghiệp cho comment giải thích nghiệp vụ, báo cáo và tài liệu.

---

## 4. Các lệnh thường dùng

```bash
# 1. Khởi chạy toàn bộ hệ thống bằng Docker Compose
docker compose up -d --build

# 2. Chạy Alembic migration (từ thư mục src/backend)
alembic upgrade head

# 3. Chạy seed dữ liệu mẫu (idempotent)
python database/seeds/seed_initial.py

# 4. Chạy bộ kiểm thử Backend
pytest src/backend/tests -v

# 5. Build kiểm tra Frontend Angular
npm --prefix src/frontend/trading-dashboard run build
```
