# Personal AI Trading Assistant (VN Stock MVP)

> **Hệ thống hỗ trợ phân tích kỹ thuật, kiểm định chiến lược (Backtest), giải thích tín hiệu bằng AI và giao dịch giả lập (Paper Trading) cho chứng khoán Việt Nam (`HOSE`, `HNX`, `UPCOM`).**

⚠️ **NGUYÊN TẮC AN TOÀN BẮT BUỘC:**  
Phiên bản MVP **chỉ hỗ trợ dữ liệu lịch sử, phân tích, Backtest và Paper Trading**. Hệ thống **không** kết nối quyền đặt lệnh thật tới bất kỳ công ty chứng khoán nào và **bắt buộc có sự phê duyệt của con người (Human Approval)** cùng **cổng kiểm soát rủi ro (Risk Engine)** trước mọi lệnh Paper.

---

## 1. Kiến trúc & Công nghệ

Dự án được tổ chức theo cấu trúc **Monorepo** với kiến trúc **Python Modular Monolith + Angular Dashboard + PostgreSQL 16**:

- **Backend (`src/backend/`):** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, APScheduler, Structlog.
- **Database (`PostgreSQL 16`):** Database `trading_db` chia thành 6 schemas logic (`market`, `analysis`, `strategy`, `trading`, `portfolio`, `system`) với 24 bảng sử dụng kiểu `NUMERIC` chuẩn xác cho mọi phép tính tài chính.
- **Frontend (`src/frontend/trading-dashboard/`):** Angular (Standalone Components, SCSS) cung cấp 8 màn hình quản trị.
- **Triển khai (`docker-compose.yml`):** 3 containers (`postgres`, `trading-backend`, `trading-frontend`).

Xem chi tiết tại:
- [docs/USER_GUIDE.md](file:///d:/www/vn-stock-ai-trader/docs/USER_GUIDE.md) — Hướng dẫn sử dụng 8 màn hình Dashboard, quy trình Daily EOD & Backup/Restore.
- [PROJECT.md](file:///d:/www/vn-stock-ai-trader/PROJECT.md) — Ngữ cảnh dự án & quy tắc nhanh.
- [DESIGN.md](file:///d:/www/vn-stock-ai-trader/DESIGN.md) — Thiết kế kiến trúc, database schemas, state machine & UI/UX.
- [AGENTS.md](file:///d:/www/vn-stock-ai-trader/AGENTS.md) — Quy tắc bắt buộc dành cho AI Coding Agents.
- [AI_Trading_Bot_Implementation_Plan.md](file:///d:/www/vn-stock-ai-trader/AI_Trading_Bot_Implementation_Plan.md) — Kế hoạch triển khai chi tiết 7 Sprints.

---

## 2. Cấu trúc Thư mục

```text
vn-stock-ai-trader/
├── src/
│   ├── backend/                  # Python FastAPI Modular Monolith
│   │   ├── app/
│   │   │   ├── core/             # Config, database, structured logging, exceptions
│   │   │   ├── api/              # REST API endpoints (/api/v1/...)
│   │   │   ├── market_data/      # Stocks, CSV provider, import batches
│   │   │   ├── indicators/       # SMA, EMA, RSI, MACD, ATR, Volume Avg
│   │   │   ├── screening/        # Stock scanner
│   │   │   ├── strategies/       # Trend Following & Pullback strategies
│   │   │   ├── backtesting/      # Walk-forward & no-look-ahead backtest engine
│   │   │   ├── ai/               # Isolated AI analysis & schema validation
│   │   │   ├── risk/             # Mandatory Risk Engine, sizing, kill switch
│   │   │   ├── trading/          # Proposals, human approvals, orders, Paper Broker
│   │   │   ├── portfolio/        # Accounts, positions, ledger, reconciliation
│   │   │   ├── system/           # Risk configs, job runs, audit logs, settings
│   │   │   └── schemas/          # Shared Pydantic DTOs
│   │   ├── alembic/              # Database migrations (6 schemas)
│   │   ├── tests/                # Unit & integration tests (pytest)
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── frontend/
│       └── trading-dashboard/    # Angular Dashboard (8 screens)
├── database/
│   ├── seeds/                    # Idempotent sample seed scripts (marked SAMPLE)
│   └── scripts/                  # Backup & restore helper scripts
├── infrastructure/
│   ├── docker/
│   └── postgres/
├── docs/
├── scripts/
├── .env.example
├── docker-compose.yml
├── PROJECT.md
├── AGENTS.md
├── DESIGN.md
└── README.md
```

---

## 3. Hướng dẫn Chạy Local bằng Docker Compose

### Bước 1: Chuẩn bị file môi trường `.env`
```bash
cp .env.example .env
```
*(Bạn có thể chỉnh sửa `DB_PASSWORD` trong `.env`. Tuyệt đối không commit file `.env` lên Git).*

### Bước 2: Khởi dựng toàn bộ контейners
```bash
docker compose up -d --build
```
Khi khởi chạy:
- **PostgreSQL 16** lắng nghe tại `127.0.0.1:5432` (chỉ bind loopback local để bảo mật).
- **FastAPI Backend** tự động chạy `alembic upgrade head`, khởi tạo đủ 6 schemas và lắng nghe tại `http://localhost:8000` (Swagger UI: `http://localhost:8000/docs`).
- **Angular Dashboard** lắng nghe tại `http://localhost:4200`.

### Bước 3: Kiểm tra trạng thái Health Check
```bash
curl http://localhost:8000/api/v1/health
```

### Bước 4: Nạp dữ liệu khởi tạo mẫu (Seed — gắn nhãn `SAMPLE`)
```bash
docker compose exec trading-backend python /app/database/seeds/seed_initial.py
```

---

## 4. Hướng dẫn Phát triển & Kiểm thử trên Máy Host

### Backend (Python FastAPI)
```bash
cd src/backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Chạy migration với PostgreSQL đang bật:
alembic upgrade head

# Chạy bộ kiểm thử (Smoke & Unit Tests):
pytest tests -v
```

### Frontend (Angular Dashboard)
```bash
cd src/frontend/trading-dashboard
npm install
npm run build
npm start
```

---

## 5. Sao lưu & Phục hồi Cơ sở Dữ liệu (Backup & Restore)

### Sao lưu (Backup)
```bash
docker compose exec -T postgres pg_dump -U trader -d trading_db -F c > backup_trading_db.dump
```

### Phục hồi (Restore)
```bash
docker compose exec -T postgres pg_restore -U trader -d trading_db --clean --if-exists < backup_trading_db.dump
```
(Hoặc sử dụng các script tiện ích trong `database/scripts/`).
