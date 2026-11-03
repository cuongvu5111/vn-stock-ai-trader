# AGENTS.md — Quy tắc & Hướng dẫn dành cho AI Coding Agents

> **Ngày cập nhật:** 2026-11-03  
> **Mục đích:** Định nghĩa quy tắc làm việc, ranh giới bảo mật, chuẩn mực kỹ thuật và quy trình nghiệm thu bắt buộc cho mọi AI Agent tham gia phát triển dự án **Personal AI Trading Assistant**.

---

## 1. Nguyên tắc An toàn Tài chính & Hệ thống (Tuyệt đối tuân thủ)

1. **Cấm Live Broker & Auto-Trading trong MVP:**
   - Không viết adapter đặt lệnh thật tới bất kỳ công ty chứng khoán nào.
   - Không lưu trữ tài khoản/mật khẩu/token giao dịch thật.
   - Không tạo cơ chế tự động duyệt lệnh (auto-approve). Mọi lệnh sang `PaperBrokerAdapter` bắt buộc phải có bản ghi `trading.approvals` hợp lệ từ người dùng.
2. **Cô lập Module AI (`src/backend/app/ai/`):**
   - AI/LLM chỉ đóng vai trò **giải thích và tổng hợp** dựa trên dữ liệu đầu vào có nguồn (`input_snapshot`).
   - Module `ai` không được import hay gọi trực tiếp tới `trading` (đặt lệnh/duyệt lệnh), `risk` (thay đổi hạn mức rủi ro), hoặc `portfolio` (thay đổi số dư).
   - Mọi dữ liệu tin tức/văn bản bên ngoài đưa vào prompt phải được coi là **untrusted input** (chống prompt injection).
3. **Độ chính xác Số học & Thời gian:**
   - Sử dụng `decimal.Decimal` (Python) và `NUMERIC` (PostgreSQL) cho mọi phép tính giá, tiền mặt, phí, thuế, P&L.
   - Mọi timestamp sự kiện lưu chuẩn UTC (`TIMESTAMPTZ` / `DateTime(timezone=True)`). Ngày giao dịch lưu kiểu `DATE` theo múi giờ thị trường `Asia/Ho_Chi_Minh`.
4. **Chống Sai lệch Dữ liệu (Anti-Bias):**
   - Không tạo dữ liệu giả rồi hiển thị như dữ liệu thị trường thật. Mọi dữ liệu mẫu phải gắn nhãn `SAMPLE` hoặc `SIMULATED`.
   - Trong Backtest, tín hiệu sinh ra từ giá đóng cửa ngày `T` chỉ được phép khớp sớm nhất vào phiên `T+1`.
5. **Bảo mật & Cấu hình:**
   - Không hardcode secret, password, API key trong code hoặc migration.
   - Chỉ sử dụng biến môi trường thông qua `app.core.config.Settings` và cập nhật `.env.example` (không chứa secret thật).

---

## 2. Ranh giới Kiến trúc (Python Modular Monolith)

Dự án tổ chức theo kiến trúc **Modular Monolith** trong `src/backend/app/`:

```text
src/backend/app/
├── core/          # Cấu hình, DB session, structured logging, exceptions
├── api/           # FastAPI routers (/api/v1/...) — chỉ điều phối HTTP, không chứa logic nghiệp vụ lõi
├── market_data/   # Quản lý mã CK, CSV import idempotent, kiểm tra chất lượng OHLCV
├── indicators/    # Tính toán SMA, EMA, RSI, MACD, ATR, Volume Average (deterministic)
├── screening/     # Quét cổ phiếu theo bộ lọc
├── strategies/    # Chiến lược Trend Following & Pullback (versioned)
├── backtesting/   # Mô phỏng lịch sử chống look-ahead, tính phí/thuế/slippage
├── ai/            # Phân tích AI có schema JSON & trích dẫn nguồn (cô lập hoàn toàn với trading)
├── risk/          # Cổng kiểm soát rủi ro bắt buộc (Position sizing, Kill Switch, Limits)
├── trading/       # Trade Proposals, Human Approvals, Orders, Paper Broker
├── portfolio/     # Accounts, Positions, Cash Ledger, Daily Snapshots, Reconciliation
├── system/        # Risk configs, Job runs, Audit logs, App settings, APScheduler
└── schemas/       # Pydantic v2 DTOs dùng chung
```

### Quy tắc phụ thuộc giữa các Module:
- `api` → gọi xuống các service trong từng module nghiệp vụ.
- `trading` → bắt buộc phải gọi `risk` để kiểm tra hạn mức trước khi tạo proposal **và** kiểm tra lại khi người dùng approve.
- `portfolio` → số dư tiền (`cash_balance`) và vị thế (`positions`) phải được suy dẫn nhất quán từ `trading.executions` và `portfolio.cash_transactions`. Không cho phép API/Frontend sửa trực tiếp số dư mà không qua bút toán sổ cái.

---

## 3. Quy trình Làm việc theo Sprint

Với mỗi task hoặc sprint trong [AI_Trading_Bot_Implementation_Plan.md](file:///d:/www/vn-stock-ai-trader/AI_Trading_Bot_Implementation_Plan.md):

1. **Đọc trước khi viết (Read before Write):** Kiểm tra các file hiện có, model SQLAlchemy và schema Pydantic trước khi chỉnh sửa.
2. **Tuân thủ kế hoạch:** Không tự ý nhảy cóc sang sprint tiếp theo khi sprint hiện tại chưa đạt toàn bộ Acceptance Criteria.
3. **Migration bắt buộc:** Mọi thay đổi đối với cấu trúc bảng trong 6 schema PostgreSQL phải đi kèm Alembic migration.
4. **Kiểm thử & Xác minh (Verify with Evidence):**
   - Mọi logic tính toán tài chính, chỉ báo, sizing, state transition đều phải có unit test (`pytest`).
   - Chạy thực tế lệnh test/build và đính kèm kết quả đầu ra trước khi báo cáo hoàn thành.
5. **Ghi chú & Tài liệu:**
   - Viết comment bằng tiếng Việt giải thích rõ lý do nghiệp vụ ("tại sao làm vậy").
   - Cập nhật `README.md` và `DESIGN.md` khi có thay đổi về API hoặc kiến trúc.
