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
- **Triển khai (`docker-compose.yml`):** 3 containers (`postgres`, `trading-backend`, `trading-frontend`) + service sao lưu tùy chọn `postgres-backup` (profile `backup`). Chạy local hoặc trong LAN bằng Docker Compose, không Kubernetes, **không giao dịch thật**.
- **Vận hành tự động:** Scheduler Daily EOD (APScheduler, mặc định tắt) chỉ chạy tới `TradeProposal(PendingApproval)`; CI GitHub Actions (`.github/workflows/ci.yml`) kiểm tra backend/frontend/Docker Compose.

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
│   │   │   ├── system/           # Risk configs, job runs, audit logs, settings, scheduler EOD (scheduler.py)
│   │   │   └── schemas/          # Shared Pydantic DTOs
│   │   ├── alembic/              # Database migrations (6 schemas)
│   │   ├── tests/                # Unit & integration tests (pytest)
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── frontend/
│       └── trading-dashboard/    # Angular Dashboard (8 screens) + nginx.conf & nginx/ (reverse proxy, header bảo mật)
├── database/
│   ├── seeds/                    # Idempotent sample seed scripts (marked SAMPLE)
│   └── scripts/                  # backup-db.ps1 / restore-db.ps1 (sao lưu & phục hồi qua Docker)
├── infrastructure/
│   ├── backup/                   # backup-loop.sh (service postgres-backup, retention cấu hình được)
│   ├── docker/
│   └── postgres/
├── .github/workflows/ci.yml      # CI: ruff + pytest (PostgreSQL) + frontend + docker compose
├── docs/
├── scripts/                      # generate-secrets.ps1 (sinh secret cho .env), script nghiệp vụ
├── .dockerignore                 # Chặn .env, .git, cache, node_modules, dist... khỏi build context
├── .env.example
├── docker-compose.yml
├── PROJECT.md
├── AGENTS.md
├── DESIGN.md
└── README.md
```

---

## 3. Hướng dẫn Chạy bằng Docker Compose (Local & LAN)

### Bước 1: Chuẩn bị file môi trường `.env` và tạo secret
```powershell
Copy-Item .env.example .env          # Linux/macOS: cp .env.example .env
.\scripts\generate-secrets.ps1       # in ra giá trị ngẫu nhiên (CSPRNG) để dán vào .env; không ghi file nào
```
Không có PowerShell? Sinh bằng Python rồi dán vào `.env`:
```bash
python -c "import secrets; print('DB_PASSWORD=' + secrets.token_hex(24)); print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48)); print('BOOTSTRAP_ADMIN_PASSWORD=' + secrets.token_urlsafe(18))"
```
Tuyệt đối không commit `.env` lên Git (đã nằm trong `.gitignore` và `.dockerignore`, không bao giờ vào image).

**Bắt buộc** — Docker Compose **dừng ngay** (không có giá trị mặc định) nếu thiếu một trong các biến sau:

| Biến | Yêu cầu |
|---|---|
| `DB_PASSWORD` | ≥ 12 ký tự ngẫu nhiên, chỉ gồm `A-Za-z0-9._~-` (được ghép vào URL kết nối). PostgreSQL chỉ nhận mật khẩu này khi khởi tạo volume lần đầu (xem mục *Đổi `DB_PASSWORD`* bên dưới). |
| `JWT_SECRET_KEY` | ≥ 32 ký tự ngẫu nhiên, không phải placeholder; backend từ chối khởi động nếu yếu. |
| `BOOTSTRAP_ADMIN_PASSWORD` | ≥ 12 ký tự. Dùng để tạo admin đầu tiên (xem *Admin đầu tiên* bên dưới). |

Tùy chọn (đã có mặc định trong `.env.example`): `MARKET_TIMEZONE` (**chỉ chấp nhận `Asia/Ho_Chi_Minh`**, dùng cho ngày giao dịch/chốt NAV; giá trị khác làm backend từ chối khởi động để không lệch với migration `0004`) và `SETTLEMENT_LAG_TRADING_DAYS` (mặc định `2`, hợp lệ 0..10): cổ phiếu mua ở ngày T chỉ bán được từ ngày làm việc thứ N sau T (bỏ thứ 7/Chủ nhật, chưa tính ngày lễ sàn).

Mọi endpoint (trừ `/health` và `/auth/login`) yêu cầu header `Authorization: Bearer <token>`; ma trận quyền xem tại `DESIGN.md` mục 2.7.

### Bước 2: Khởi dựng toàn bộ containers
```bash
docker compose up -d --build --wait
```
Mặc định chỉ truy cập được từ **chính máy chủ**:
- **Angular Dashboard (nginx, chạy không root):** `http://127.0.0.1:4200` — cũng là reverse proxy `/api` tới backend.
- **PostgreSQL 16:** `127.0.0.1:5432` (chỉ loopback, để chạy test/migration từ máy host).
- **FastAPI Backend:** tự chạy `alembic upgrade head` rồi seed idempotent khi container khởi động; cổng `127.0.0.1:8000` chỉ loopback. Swagger UI (`/docs`) chỉ có khi `APP_ENV=development` (Compose mặc định `APP_ENV=production`).

Container backend/frontend chạy bằng user không phải root, hệ thống file chỉ đọc, bỏ toàn bộ Linux capabilities, có healthcheck, giới hạn CPU/RAM/PID và xoay vòng log (10 MB × 5 file). Frontend chỉ khởi động khi backend `healthy`; backend chỉ khởi động khi PostgreSQL `healthy`.

### Bước 3: Kiểm tra trạng thái Health Check
```bash
docker compose ps                                   # cột STATUS phải là (healthy)
curl http://127.0.0.1:4200/health                   # nginx: "ok"
curl http://127.0.0.1:4200/api/v1/health            # backend qua nginx: status=healthy, database_status=connected
```

### Bước 4: Dữ liệu khởi tạo & admin đầu tiên
Backend tự seed idempotent mỗi lần khởi động (tài khoản Paper `DEFAULT_PAPER_ACCOUNT`, chiến lược, risk config, mã mẫu gắn nhãn `SAMPLE`); chạy lại thủ công nếu cần: `docker compose exec trading-backend python /app/database/seeds/seed_initial.py`.

**Admin đầu tiên (first-run):** seed tạo user `BOOTSTRAP_ADMIN_USERNAME` (mặc định `admin`) với mật khẩu `BOOTSTRAP_ADMIN_PASSWORD` **chỉ khi chưa có user trùng tên** và không bao giờ ghi đè mật khẩu của user đã tồn tại. Đăng nhập tại dashboard (hoặc `POST /api/v1/auth/login`), đổi mật khẩu bằng chức năng đổi mật khẩu, rồi tạo user `trader`/`viewer` qua tab **User Admin** hoặc `POST /api/v1/auth/users`. Sau khi admin đã tồn tại, giá trị trong `.env` không còn tác dụng với user đó.

### Chạy trong LAN (truy cập từ máy khác trong mạng nội bộ)

> ⚠️ **Cảnh báo HTTP trong LAN:** dashboard phục vụ qua **HTTP thường, không mã hóa**. Mật khẩu đăng nhập và JWT đi qua mạng dạng văn bản, có thể bị nghe lén bởi bất kỳ ai cùng mạng. Chỉ dùng trong LAN tin cậy (không Wi-Fi công cộng/khách), **không port-forward hay mở ra Internet**. Nginx cố ý không bật HSTS/`upgrade-insecure-requests` vì sẽ làm hỏng truy cập qua `http://IP:cổng`. Cần mã hóa thì đặt thêm một reverse proxy TLS hoặc VPN (WireGuard/Tailscale) phía trước — ngoài phạm vi repo này.

1. Trong `.env`, đặt `FRONTEND_BIND_ADDRESS=<IP LAN của máy chủ>` (ví dụ `192.168.1.10`; tránh `0.0.0.0` vì mở trên mọi giao diện mạng, kể cả VPN) và `APP_ENV=production`. Cổng mặc định `FRONTEND_PORT=4200`.
2. `docker compose up -d --build --wait`, mở `http://192.168.1.10:4200` trên máy khác.
3. Chỉ mở firewall của máy chủ cho **cổng frontend** và chỉ từ mạng LAN, ví dụ (PowerShell quản trị): `New-NetFirewallRule -DisplayName "VN Stock Dashboard" -Direction Inbound -Protocol TCP -LocalPort 4200 -RemoteAddress LocalSubnet -Action Allow`.

| Service | Cổng trên máy chủ | Phơi bày |
|---|---|---|
| `trading-frontend` (nginx, cổng 8080 trong container) | `${FRONTEND_BIND_ADDRESS:-127.0.0.1}:${FRONTEND_PORT:-4200}` | **Duy nhất** có thể ra LAN (qua `FRONTEND_BIND_ADDRESS`) |
| `trading-backend` | `127.0.0.1:8000` (cố định) | Chỉ loopback; nginx gọi qua mạng nội bộ Docker, Host luôn là `trading-backend` |
| `postgres` | `127.0.0.1:5432` (cố định) | Chỉ loopback, không bao giờ ra LAN |

Cứng hóa khi `APP_ENV` không phải `development`/`test`: backend **từ chối khởi động** nếu `DB_PASSWORD` yếu/placeholder/không URL-safe, `CORS_ORIGINS` rỗng hoặc có wildcard/giá trị sai định dạng, `TRUSTED_HOSTS` rỗng hoặc có `*` (Compose mặc định `localhost,127.0.0.1,trading-backend`), hoặc `BOOTSTRAP_ADMIN_PASSWORD` < 12 ký tự. Backend chỉ chấp nhận Host trong `TRUSTED_HOSTS` (chống DNS rebinding vào cổng loopback). Dashboard gọi API cùng origin qua nginx nên không cần thêm IP LAN vào `CORS_ORIGINS`.

Nginx: `server_tokens off`; CSP (`script-src 'self'`, `frame-ancestors 'none'`...), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`; body tối đa 1 MB (riêng `POST /api/v1/market/imports` cho CSV tối đa 10 MB); rate limit riêng `POST /api/v1/auth/login` (10 lần/phút/IP, burst 5, vượt thì `429`) và rate limit chung cho `/api/`; tài nguyên build có hash cache 1 năm (`immutable`), `index.html` `no-cache`; `/health` cho healthcheck. Trên Docker Desktop (Windows/macOS) mọi client LAN có thể hiện cùng một IP nguồn nên rate limit dùng chung hạn mức.

**Đổi `DB_PASSWORD` sau lần khởi tạo đầu:** PostgreSQL chỉ áp dụng `POSTGRES_PASSWORD` khi tạo volume. Đổi mật khẩu: `docker compose exec postgres psql -U trader -d trading_db` (thay `trader`/`trading_db` nếu đã đổi `POSTGRES_USER`/`POSTGRES_DB`) rồi chạy `ALTER USER trader PASSWORD '<mật khẩu mới>';`, cập nhật `.env`, sau đó `docker compose up -d`. Muốn bắt đầu lại từ đầu (**xóa toàn bộ dữ liệu**): `docker compose down -v`.

### Scheduler Daily EOD (APScheduler)

Mặc định **tắt**. Bật bằng `SCHEDULER_ENABLED=true` trong `.env` (chạy đúng **1 container backend với 1 worker** uvicorn):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `SCHEDULER_ENABLED` | `false` | Bật scheduler trong lifespan FastAPI (tắt sạch khi backend dừng). |
| `DAILY_EOD_HOUR` / `DAILY_EOD_MINUTE` | `16` / `30` | Giờ chạy theo `Asia/Ho_Chi_Minh` (múi giờ **cố định**, không cấu hình), thứ 2 → thứ 6. |
| `SCHEDULER_MISFIRE_GRACE_SECONDS` | `3600` | Lỡ giờ chạy (vd. backend đang tắt) quá ngưỡng này thì bỏ qua lần đó. |

An toàn: job gọi `SystemWorkflowService.run_daily_eod_workflow` với payload cố định — **không** import dữ liệu mẫu `SAMPLE`, chỉ chạy bước AI khi `AI_ENABLED=true`, tạo `TradeProposal(PendingApproval)` và **dừng ở đó**: không tự duyệt, không tạo Order/Execution (lệnh Paper chỉ có sau khi bạn bấm Approve). `coalesce=true`, `max_instances=1`, mỗi lần chạy dùng một DB session riêng. Lỗi → rollback, ghi `system.job_runs` `FAILED` + `error_detail` (cập nhật chính bản ghi `RUNNING` nếu đã commit, không tạo bản ghi lỗi trùng), ghi `audit_logs` `DAILY_EOD_WORKFLOW_FAILED` và log JSON `scheduler_daily_eod_failed`. Scheduler **không tự nạp dữ liệu giá**: hãy import dữ liệu của ngày giao dịch trước giờ chạy; dữ liệu `SAMPLE` đã có sẵn trong DB vẫn được dùng để sinh đề xuất, nên hãy nạp dữ liệu thật (xóa SAMPLE) trước khi bật. Theo dõi: dashboard/`GET /api/v1/system/jobs`, hoặc `docker compose logs trading-backend | findstr scheduler_`.

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

# Lint + chạy bộ kiểm thử (Smoke, Unit, Scheduler, cấu hình cứng hóa...):
ruff check .
pytest tests -v

# (Tùy chọn) Test migration 0003/0004/0005 và test khớp/hủy lệnh đồng thời (nhiều session/thread, khóa Order -> Stock -> Account) trên PostgreSQL thật:
# mỗi test tự tạo/xóa một database tạm (user cần quyền CREATE DATABASE). Không đặt biến này thì các test PostgreSQL được bỏ qua
# (35 test), các test SQL offline vẫn chạy. CI luôn đặt biến này và coi việc có test bị skip là lỗi.
# $env:MIGRATION_TEST_POSTGRES_URL = "postgresql+psycopg://<user>:<mật khẩu>@127.0.0.1:<port>/postgres"
```
Test không bao giờ khởi động scheduler thật hay dùng đồng hồ thật (`conftest.py` ép `SCHEDULER_ENABLED=false`; `tests/test_scheduler.py` kích hoạt job bằng `next_run_time` giả).
Migration `0003_order_approval_integrity` dừng với lỗi nêu rõ nếu còn order cũ không gán được Approval `APPROVED` cùng proposal (không bao giờ gán sai); xem `DESIGN.md` mục 2.6.
Migration `0005_unique_account_name` thêm UNIQUE `portfolio.accounts.account_name` và dừng với lỗi nêu rõ (không tự gộp dữ liệu) nếu DB cũ đã có tên tài khoản trùng; cần xử lý thủ công rồi chạy lại `alembic upgrade head`.

### Frontend (Angular Dashboard)
```bash
cd src/frontend/trading-dashboard
npm ci
npm run build
npm run lint
npm test        # Karma + Jasmine, ChromeHeadless, không watch
npm start
```

Dashboard yêu cầu đăng nhập (`/api/v1/auth/login`) trước khi hiển thị 8 màn hình; access token chỉ lưu ở `sessionStorage` (MVP chạy LAN, đóng tab là mất phiên), 401 sẽ đưa UI về màn hình đăng nhập. Tài khoản có `must_change_password` bị buộc đổi mật khẩu trước khi vào dashboard. Admin có thêm tab **9. User Admin** để quản lý người dùng. Ma trận hiển thị theo vai trò chỉ để ẩn/disable nút — backend vẫn là nơi quyết định quyền.

### CI (GitHub Actions — `.github/workflows/ci.yml`)
Chạy khi push lên `main`/`master`, pull request hoặc thủ công; **không deploy**, chỉ dùng secret thử nghiệm sống trong runner tạm:
- **backend:** Python 3.12, cache pip, PostgreSQL 16 service; `ruff check`, `alembic upgrade head` + seed (chạy 2 lần để kiểm tra idempotent), `pytest` với `MIGRATION_TEST_POSTGRES_URL` (gồm test PostgreSQL thật; có test bị skip là CI thất bại).
- **frontend:** Node 22, cache npm; `npm ci`, `npm run lint`, `npm test` (ChromeHeadless), `npm run build`, kiểm tra `index.html` không có script/handler inline (tương thích CSP).
- **docker:** `docker compose config` (kể cả profile `backup`), thiếu secret bắt buộc phải thất bại ngay, chỉ frontend được bind LAN, `docker compose build`, `up --wait`, smoke test qua nginx (health, header bảo mật, đăng nhập admin, Swagger tắt, Host lạ bị chặn).

---

## 5. Sao lưu & Phục hồi Cơ sở Dữ liệu (Backup & Restore)

Bản sao lưu là file `.dump` (`pg_dump -Fc`) chứa **dữ liệu nhạy cảm** (băm mật khẩu, sổ lệnh, audit): bảo vệ file và nên chép thêm sang ổ/máy khác. Hãy thử khôi phục định kỳ.

### Sao lưu thủ công
```powershell
.\database\scripts\backup-db.ps1                          # -> backups\trading_db_<UTC>.dump
.\database\scripts\backup-db.ps1 -OutputDir D:\backups\trading -KeepLast 14
```
Script dump **bên trong container** rồi `docker compose cp` ra máy chủ (không dùng `> file` của PowerShell vì làm hỏng file nhị phân). Linux/macOS (bash) có thể dùng: `docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/trading_db.dump`.

### Sao lưu tự động (service `postgres-backup`, profile `backup`)
```bash
docker compose --profile backup up -d postgres-backup
docker compose logs postgres-backup
```
Sao lưu ngay khi khởi động rồi lặp lại mỗi `BACKUP_INTERVAL_HOURS` (mặc định 24) vào `BACKUP_DIR` (mặc định `./backups`). Chỉ bản `pg_restore --list` đọc được mới được giữ; xóa bản cũ hơn `BACKUP_RETENTION_DAYS` (mặc định 14) nhưng luôn giữ tối thiểu `BACKUP_MIN_KEEP` (mặc định 3) bản mới nhất. Service chỉ có quyền ghi vào thư mục sao lưu và không dùng `initdb`/cron của máy chủ.

### Phục hồi (Restore)
```powershell
.\database\scripts\restore-db.ps1 -InputFile .\backups\trading_db_20261117T093000Z.dump
```
Script yêu cầu gõ `RESTORE` để xác nhận (bỏ qua bằng `-Force`), tạm dừng `trading-backend` (tránh khóa tranh chấp và scheduler chạy giữa chừng), khôi phục trong **một transaction** (`--clean --if-exists --single-transaction --exit-on-error`: lỗi thì dữ liệu hiện tại giữ nguyên) rồi khởi động lại backend. **Thao tác ghi đè toàn bộ dữ liệu hiện tại** — nên sao lưu trước. Sau khi phục hồi, chạy `POST /api/v1/portfolio/reconcile` (hoặc nút **Reconcile** ở Màn hình 7) để xác nhận sổ cái nhất quán.
