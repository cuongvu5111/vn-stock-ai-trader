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
# 1. Sao chép file cấu hình môi trường
Copy-Item .env.example .env

# 2. Khởi động PostgreSQL 16, FastAPI Backend và Angular Dashboard
docker compose up --build -d

# 3. Chạy Alembic migration & nạp dữ liệu khởi tạo (Idempotent)
docker compose exec trading-backend alembic upgrade head
docker compose exec trading-backend python /workspace/database/seeds/seed_initial.py
```
- **Angular Dashboard:** `http://localhost:4200`
- **FastAPI Swagger UI:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/api/v1/health`

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

### 4.1. Sao lưu (Backup) PostgreSQL ra file `.dump`
```powershell
# Tạo thư mục lưu trữ bản sao lưu
New-Item -ItemType Directory -Force -Path backups

# Chạy pg_dump bên trong container postgres
docker compose exec -T postgres pg_dump -U trader -d trading_db -F c > backups/trading_db_backup.dump
```

### 4.2. Phục hồi (Restore) từ file `.dump`
```powershell
# Khôi phục lại toàn bộ 6 schemas từ file backup
Get-Content backups/trading_db_backup.dump -Raw | docker compose exec -T postgres pg_restore -U trader -d trading_db --clean --if-exists
```
After restoring, chạy API `POST /api/v1/portfolio/reconcile` (hoặc nhấn nút **Reconcile** trên Màn hình 7) để xác nhận tính toàn vẹn 100% của sổ cái danh mục.
