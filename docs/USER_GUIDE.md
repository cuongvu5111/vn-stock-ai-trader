# Hướng Dẫn Sử Dụng & Vận Hành (User Guide) — Personal AI Trading Assistant (VN Stock MVP)

> **Ngày cập nhật:** 2026-11-03  
> **Phiên bản:** 0.1.0 (MVP — Paper Trading Only)  
> **Đối tượng:** Nhà đầu tư cá nhân nghiên cứu thị trường chứng khoán Việt Nam (`HOSE`, `HNX`, `UPCOM`) theo phong cách Daily / Swing EOD.

---

## 1. Cảnh Báo An Toàn Tài Chính (Bắt Buộc Đọc Trước Khi Sử Dụng)

1. **Không Giao Dịch Tiền Thật (No Live Broker):** Phiên bản MVP chỉ hỗ trợ dữ liệu lịch sử, phân tích kỹ thuật, Backtest và **Paper Trading** với vốn giả lập mặc định `30,000,000 VND`.
2. **Không Tự Động Đặt Lệnh (No Auto-Trading):** Quy trình tự động hàng ngày (`Daily EOD Pipeline`) luôn dừng ở bước tạo đề xuất giao dịch (`TradeProposal` ở trạng thái `PendingApproval`). Lệnh Paper chỉ được tạo khi chính bạn nhấn nút **Approve**.
3. **AI Chỉ Đóng Vai Trò Giải Thích:** Báo cáo AI (`Explainable AI`) tổng hợp luận điểm kèm trích dẫn nguồn (`SIGNAL_...`, `NEWS_...`, `FIN_...`) và nêu rõ giới hạn dữ liệu (`limitations`). AI hoàn toàn cô lập với module đặt lệnh và quản trị rủi ro.

---

## 2. Khởi Động Hệ Thống Local

### Cách 1: Chạy trọn bộ bằng Docker Compose (Khuyến nghị)
```powershell
# 1. Sao chép file cấu hình môi trường và sinh secret ngẫu nhiên
Copy-Item .env.example .env
.\scripts\generate-secrets.ps1     # dán DB_PASSWORD, JWT_SECRET_KEY, BOOTSTRAP_ADMIN_PASSWORD vào .env (KHÔNG commit .env)

# 2. Khởi động PostgreSQL 16, FastAPI Backend và Angular Dashboard (tự chạy Alembic migration + seed idempotent)
docker compose up --build -d --wait
```
- **Angular Dashboard:** `http://127.0.0.1:4200` — đăng nhập bằng `BOOTSTRAP_ADMIN_USERNAME` (mặc định `admin`) và `BOOTSTRAP_ADMIN_PASSWORD` trong `.env` (admin đầu tiên chỉ được tạo khi chưa có user trùng tên; sau đó hãy đổi mật khẩu ngay trong dashboard).
- **Health Check:** `http://127.0.0.1:4200/api/v1/health` (qua nginx) hoặc `http://127.0.0.1:8000/api/v1/health` (cổng loopback của backend).
- **FastAPI Swagger UI:** `http://127.0.0.1:8000/docs` — **chỉ** khi đặt `APP_ENV=development` trong `.env` (Compose mặc định `production` nên Swagger tắt).
- Thiếu `DB_PASSWORD`, `JWT_SECRET_KEY` hoặc `BOOTSTRAP_ADMIN_PASSWORD` thì `docker compose` dừng ngay với thông báo rõ ràng.

### Cách 1b: Truy cập từ máy khác trong LAN
> ⚠️ **HTTP thường, không mã hóa:** mật khẩu và JWT có thể bị nghe lén trong cùng mạng. Chỉ dùng LAN tin cậy, không mở ra Internet. Cần mã hóa thì đặt thêm reverse proxy TLS hoặc VPN.

1. Trong `.env`: `FRONTEND_BIND_ADDRESS=192.168.1.10` (IP LAN của máy chủ) và `APP_ENV=production`.
2. `docker compose up -d --build --wait`, rồi mở `http://192.168.1.10:4200` trên máy khác.
3. Chỉ mở firewall cho cổng `4200` từ mạng LAN. PostgreSQL (`5432`) và backend (`8000`) **luôn chỉ bind `127.0.0.1`**, không thể truy cập từ LAN.

Chi tiết cứng hóa nginx, `TRUSTED_HOSTS`/`CORS_ORIGINS`, rate limit đăng nhập và đổi `DB_PASSWORD` xem `README.md` mục 3 và `DESIGN.md` mục 5.

### Cách 2: Chạy trực tiếp trên máy phát triển
```powershell
# Terminal 1 — FastAPI Backend
$env:PYTHONPATH="src/backend"
src\backend\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — Angular Dashboard
cd src/frontend/trading-dashboard
npm install
npm start
```

---

## 3. Hướng Dẫn Quy Trình Nghiệp Vụ Chuẩn Hàng Ngày (8 Màn Hình Dashboard)

### Bước 1: Chạy Daily EOD Pipeline (`Màn hình 1. Overview`)
- Nhấn nút **⚡ Chạy Daily EOD Pipeline** ở thanh điều hướng bên trái.
- Hệ thống tự động thực hiện tuần tự:
  1. Kiểm tra và nạp dữ liệu mẫu `sample_ohlcv_data.csv` (55 phiên cho `HPG`, `ACB`, `FPT` gắn nhãn `SAMPLE`) nếu cơ sở dữ liệu đang trống.
  2. Tính toán bộ chỉ báo kỹ thuật (`SMA20/50/200`, `EMA20/50`, `RSI14`, `MACD`, `ATR14`, `Volume Avg 20`).
  3. Quét toàn bộ mã cổ phiếu theo hai chiến lược `Trend Following` và `Pullback`.
  4. Sinh báo cáo giải thích AI có trích dẫn nguồn cho các tín hiệu `BUY` / `SELL`.
  5. Chạy `Risk Engine` tính toán khối lượng đặt lệnh tối ưu theo lô 100 cổ phiếu và tạo `TradeProposal` ở trạng thái `PendingApproval`.
  6. Chốt bản chụp `Daily Snapshot` cho danh mục Paper.
- **Tự động hằng ngày (tùy chọn):** đặt `SCHEDULER_ENABLED=true` trong `.env` để backend tự chạy pipeline này lúc **16:30 thứ 2 → thứ 6 (giờ `Asia/Ho_Chi_Minh`)**; đổi giờ bằng `DAILY_EOD_HOUR`/`DAILY_EOD_MINUTE`. Bản tự động **không nạp dữ liệu mẫu**, chỉ chạy AI khi `AI_ENABLED=true`, và **luôn dừng ở đề xuất `PendingApproval`** — không tự duyệt, không tự khớp lệnh. Hãy import dữ liệu giá của ngày giao dịch trước 16:30 vì scheduler không tự nạp dữ liệu; nếu DB còn dữ liệu `SAMPLE` đã nạp trước đó, đề xuất vẫn được sinh từ dữ liệu đó nên hãy nạp dữ liệu thật (xóa SAMPLE) trước khi bật scheduler. Kết quả (`COMPLETED`/`FAILED` kèm `error_detail`) nằm ở `GET /api/v1/system/jobs` và log `scheduler_daily_eod_*` (`docker compose logs trading-backend`). Chạy đúng một backend/một worker khi bật scheduler.

### Bước 2: Kiểm tra Dữ liệu & Biểu đồ (`Màn hình 2. Market Data`)
- Chọn mã cổ phiếu (`HPG`, `ACB`, `FPT`) để quan sát biểu đồ SVG hiển thị đường giá đóng cửa (`Close`) và đường trung bình động `MA20`.
- Để nạp thêm dữ liệu CSV mới: dán nội dung theo định dạng `symbol,trading_date,open,high,low,close,volume,exchange,data_label` và nhấn **Kiểm Tra & Import CSV**. Hệ thống tự động từ chối các dòng lỗi (`high < low`, giá âm, trùng lặp) và cảnh báo ngày làm việc bị khuyết.

### Bước 3: Quét Tín hiệu & Chạy Backtest (`Màn hình 3. Stock Scanner`)
- Lọc theo chiến lược `TREND_FOLLOWING` hoặc `PULLBACK` và nhấn **🔍 Chạy Stock Scanner Ngay**.
- Để kiểm증 hiệu quả lịch sử trước khi giao dịch Paper: nhập mã cổ phiếu, khoảng thời gian và nhấn **📊 Chạy Backtest Chiến Lược**. Hệ thống mô phỏng khớp lệnh tại giá mở cửa phiên kế tiếp (`T+1 Open` + trượt giá `10 bps` + phí mua/bán `0.15%` + thuế bán `0.10%`) và hiển thị đầy đủ `Total Return`, `Max Drawdown`, `Win Rate`, `Benchmark Buy & Hold`.

### Bước 4: Xem Chi tiết Tín hiệu & Báo cáo AI (`Màn hình 4. Signal Detail & AI`)
- Nhấn **Chi Tiết & AI** trên bất kỳ tín hiệu nào để xem:
  - Điểm nội bộ (`score`), giá tham chiếu (`reference_price`), mức cắt lỗ bắt buộc (`stop_loss`).
  - Luận điểm tổng hợp (`thesis`), bằng chứng kỹ thuật được gắn nhãn `[FACT]` / `[INFERENCE]` kèm mã nguồn (`SIGNAL_...`), rủi ro, bằng chứng trái chiều và giới hạn dữ liệu (`limitations`).

### Bước 5: Phê duyệt Đề xuất Giao dịch (`Màn hình 5. Trade Approval`)
- Kiểm tra kỹ các thông số đã được `Risk Engine` tính toán:
  - `KL Đề Xuất`: đã làm tròn xuống theo bội số lô `100` cổ phiếu.
  - `Chi Phí Ước Tính`: đã bao gồm phí giao dịch và dự phòng trượt giá.
  - `Rủi Ro Tối Đa`: đảm bảo không vượt quá `1% NAV` (`300,000 VND`) trên khoảng cách từ giá đặt tới `Stop Loss`.
- Nhập tên người duyệt (`approved_by`), ghi chú (`comment`) và nhấn **✓ Approve** (hoặc **✕ Reject**):
  - Khi nhấn **Approve**, Backend sẽ khóa bản ghi (`SELECT ... FOR UPDATE`), kiểm tra hạn hiệu lực (`expires_at`), đối chiếu `Snapshot` và **Re-validate toàn bộ hạn mức rủi ro + Kill Switch** ngay tại thời điểm duyệt.
  - Nếu hợp lệ, đúng **1 lệnh Paper (`Order`)** sẽ được khởi tạo sang `Paper Broker`.

### Bước 6: Mô phỏng Khớp lệnh Paper (`Màn hình 6. Paper Orders`)
- Với các lệnh đang ở trạng thái `Submitted` hoặc `PartiallyFilled`:
  - Nhập khối lượng muốn khớp (hỗ trợ khớp từng phần — **Partial Fill** theo lô 100 hoặc khớp toàn bộ) và giá khớp, sau đó nhấn **Khớp Lệnh**.
  - Mỗi lần khớp sinh ra một bản ghi bất biến trong `trading.executions`, đồng thời trừ/cộng tiền mặt trong `portfolio.cash_transactions` và cập nhật giá vốn bình quân trong `portfolio.positions`.

### Bước 7: Quản lý Danh mục & Đối soát Sổ cái (`Màn hình 7. Portfolio & Ledger`)
- Xem toàn bộ lịch sử bút toán tiền mặt (`INITIAL_DEPOSIT`, `BUY_EXECUTION`, `SELL_EXECUTION`) và lịch sử chốt NAV cuối ngày (`Daily Snapshots`).
- Nhấn **🔄 Đối Soát & Rebuild Từ Sổ Cái (Reconcile)** bất cứ lúc nào để hệ thống kiểm tra chéo và tái dựng lại số dư tiền mặt cùng vị thế cổ phiếu từ hai bảng gốc bất biến (`cash_transactions` và `executions`).

### Bước 8: Cấu hình Hạn mức Rủi ro & Kill Switch (`Màn hình 8. Risk Settings`)
- Điều chỉnh các hạn mức (`max_position_percent`, `max_risk_per_trade_percent`, `max_daily_loss_percent`, `max_open_positions`, `max_portfolio_allocation_percent`).
- **Kill Switch Khẩn Cấp:** Nhấn nút **Bật Kill Switch** trên thanh tiêu đề (hoặc bỏ chọn `trading_enabled` rồi bấm Lưu). Khi Kill Switch đang bật, mọi yêu cầu tạo Proposal mới hoặc Approve Proposal đang chờ đều bị chặn ngay lập tức và được ghi nhận vào `system.audit_logs`.

---

## 4. Hướng Dẫn Sao Lưu & Phục Hồi Cơ Sở Dữ Liệu (Backup & Restore)

> File .dump chứa dữ liệu nhạy cảm (băm mật khẩu, sổ lệnh, audit). Hãy bảo vệ file, chép thêm sang ổ/máy khác và thử khôi phục định kỳ.

### 4.1. Sao lưu thủ công (PostgreSQL ra file `.dump`)
```powershell
.\database\scripts\backup-db.ps1                                   # -> backups\trading_db_<UTC>.dump
.\database\scripts\backup-db.ps1 -OutputDir D:\backups\trading -KeepLast 14
```
Script dump bên trong container rồi `docker compose cp` ra máy chủ; **không** dùng `docker compose exec ... > file` trong PowerShell vì chuyển hướng văn bản làm hỏng file nhị phân.

### 4.2. Sao lưu tự động theo lịch (service `postgres-backup`)
```powershell
docker compose --profile backup up -d postgres-backup
docker compose logs postgres-backup
```
Cấu hình trong `.env`: `BACKUP_DIR` (mặc định `./backups`), `BACKUP_INTERVAL_HOURS` (24), `BACKUP_RETENTION_DAYS` (14), `BACKUP_MIN_KEEP` (3 — luôn giữ tối thiểu số bản mới nhất này dù đã quá hạn). Bản sao lưu được kiểm tra bằng `pg_restore --list` trước khi tính là hợp lệ; lỗi thì thử lại sau vài phút và ghi log `THAT BAI`.

### 4.3. Phục hồi (Restore) từ file `.dump`
```powershell
.\database\scripts\restore-db.ps1 -InputFile .\backups\trading_db_20261117T093000Z.dump
```
Script yêu cầu gõ `RESTORE` để xác nhận (`-Force` để bỏ qua), tạm dừng `trading-backend`, khôi phục trong một transaction (lỗi thì dữ liệu hiện tại giữ nguyên) rồi khởi động lại backend. **Ghi đè toàn bộ dữ liệu hiện tại** — nên sao lưu trước.

Sau khi phục hồi, chạy API `POST /api/v1/portfolio/reconcile` (hoặc nhấn nút **Reconcile** trên Màn hình 7) để xác nhận tính toàn vẹn 100% của sổ cái danh mục.
