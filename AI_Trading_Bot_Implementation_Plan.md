# Implementation Plan: Personal AI Trading Assistant

> **Mục tiêu:** Xây dựng hệ thống hỗ trợ đầu tư chứng khoán Việt Nam
> theo phong cách Daily Trading, sử dụng AI để phân tích và giải thích
> tín hiệu, nhưng yêu cầu con người phê duyệt trước mọi giao dịch.
>
> **Phiên bản:** 1.0\
> **Phạm vi:** Personal MVP, vốn dự kiến dưới 50 triệu VNĐ, chạy local
> bằng Docker Compose.\
> **Nguyên tắc an toàn:** MVP chỉ hỗ trợ dữ liệu lịch sử, phân tích,
> backtest và Paper Trading. Không gửi lệnh thật, không kết nối quyền
> giao dịch broker trong MVP.

------------------------------------------------------------------------

## 1. Hướng dẫn cho AI Agent

Bạn là AI coding agent chịu trách nhiệm triển khai dự án theo kế hoạch
này. Hãy làm việc theo từng phase/sprint, không bỏ qua tiêu chí nghiệm
thu.

### Quy tắc bắt buộc

1.  Trước khi code, kiểm tra repository hiện tại, công nghệ đã có,
    convention, cấu trúc thư mục và trạng thái Git. Không ghi đè hoặc
    xóa mã nguồn hiện có khi chưa xác nhận.
2.  Nếu repository trống, khởi tạo theo cấu trúc tại mục 5.
3.  Ưu tiên giải pháp đơn giản, dễ chạy local và dễ bảo trì. Không tự ý
    biến MVP thành microservices hoặc thêm Kafka, Kubernetes, Redis nếu
    chưa có yêu cầu rõ ràng.
4.  Không tự ý thêm broker thật, endpoint đặt lệnh thật, credential giao
    dịch hoặc tính năng auto-trading.
5.  Không hardcode API key, mật khẩu, token hoặc dữ liệu tài khoản. Dùng
    biến môi trường và cung cấp `.env.example` không chứa secret.
6.  Mọi tính toán tài chính phải có unit test; mọi thay đổi schema phải
    có migration.
7.  Không tạo dữ liệu thị trường giả rồi trình bày như dữ liệu thật. Dữ
    liệu demo phải được gắn nhãn `SIMULATED` hoặc `SAMPLE`.
8.  Không dùng dữ liệu tương lai trong backtest (look-ahead bias). Tín
    hiệu tạo sau khi phiên kết thúc không được khớp ở giá đóng cửa của
    chính phiên đó.
9.  Mọi đề xuất giao dịch phải đi qua Risk Management và Human Approval.
    AI/LLM không được gọi trực tiếp broker hoặc tự thay đổi hạn mức rủi
    ro.
10. Khi hoàn thành mỗi task, chạy test/build liên quan, ghi rõ kết quả,
    file đã thay đổi, vấn đề còn tồn tại và cách chạy.
11. Nếu thiếu thông tin bên ngoài (ví dụ nhà cung cấp dữ liệu), xây dựng
    interface/adapter và CSV import trước; không tự đoán API hoặc điều
    khoản sử dụng.
12. Không tuyên bố chiến lược có lợi nhuận chỉ dựa trên backtest. Báo
    cáo phải nêu giả định, phí, thuế, trượt giá, giới hạn dữ liệu và rủi
    ro overfitting.

### Quy trình làm việc

Với mỗi sprint: - Đọc mục tiêu, task và acceptance criteria. - Đề xuất
kế hoạch ngắn trước khi sửa nhiều file. - Triển khai theo thứ tự phụ
thuộc. - Viết/cập nhật tests. - Chạy formatter, lint, tests và build. -
Cập nhật `README.md`, tài liệu API/schema nếu có thay đổi. - Đánh dấu
checklist hoàn thành trong file plan hoặc báo cáo tiến độ riêng. - Không
chuyển sprint nếu tiêu chí nghiệm thu của sprint hiện tại chưa đạt, trừ
khi nêu rõ blocker và xin quyết định.

------------------------------------------------------------------------

## 2. Product Definition

### 2.1. Người dùng và mục tiêu

-   Một người dùng cá nhân.
-   Thị trường: chứng khoán Việt Nam (HOSE, HNX, UPCOM).
-   Phong cách: Daily Trading / swing ngắn, phân tích dữ liệu ngày và dự
    kiến nắm giữ từ vài ngày đến vài tuần.
-   Vốn giả lập ban đầu: cấu hình được, mặc định 30.000.000 VNĐ.
-   Mức tự động hóa: Hybrid --- hệ thống phân tích và đề xuất; người
    dùng quyết định.
-   Triển khai: local Docker Compose.

### 2.2. MVP phải làm được

1.  Quản lý danh sách cổ phiếu.
2.  Import dữ liệu OHLCV ngày từ CSV.
3.  Kiểm tra chất lượng dữ liệu và truy xuất nguồn dữ liệu.
4.  Tính chỉ báo kỹ thuật: SMA/EMA, RSI, MACD, ATR, volume average.
5.  Quét cổ phiếu theo điều kiện chiến lược.
6.  Sinh tín hiệu BUY/SELL/HOLD có lý do và thời điểm dữ liệu.
7.  Backtest với giả định giao dịch rõ ràng, tính phí và trượt giá cấu
    hình được.
8.  Tạo báo cáo phân tích AI từ dữ liệu đầu vào có nguồn.
9.  Tạo trade proposal, kiểm tra risk và yêu cầu người dùng duyệt.
10. Paper trading, quản lý order/fill/portfolio và audit log.
11. Dashboard xem thị trường, tín hiệu, đề xuất, lệnh và danh mục.

### 2.3. Ngoài phạm vi MVP

-   Gửi lệnh tiền thật hoặc tích hợp quyền giao dịch broker.
-   Intraday/high-frequency trading.
-   Dự đoán giá bằng deep learning hoặc reinforcement learning.
-   Multi-agent tự hành.
-   Tự động thay đổi chiến lược hoặc risk config.
-   Multi-user, multi-tenant.
-   Kubernetes, Kafka, Redis Cluster.
-   Cam kết lợi nhuận hoặc khuyến nghị đầu tư cá nhân hóa.

------------------------------------------------------------------------

## 3. Architecture Decisions

### 3.1. Kiến trúc

Dùng **Python Modular Monolith (FastAPI) + Angular + PostgreSQL** trong cấu trúc **Monorepo**:

-   Angular: giao diện người dùng (Dashboard).
-   Python 3.12 + FastAPI: toàn bộ Backend API, nghiệp vụ điều phối (Signals, Risk Management, Trade Proposals, Approval, Paper Broker, Portfolio) và Analysis Engine (phân tích định lượng, scanner, backtest, AI orchestration).
-   SQLAlchemy 2.0 + Alembic: ORM và quản lý schema/migration trên PostgreSQL.
-   PostgreSQL 16: lưu trữ chính (chia 6 schema logic).
-   APScheduler: lịch chạy background jobs định kỳ ngay trong hệ sinh thái Python.
-   Docker Compose: local deployment.

Không cần Redis/Kafka hay tách nhiều ngôn ngữ backend trong MVP. Toàn bộ tính toán tiền tệ, giá, phí, thuế và khối lượng trong Python bắt buộc dùng `decimal.Decimal` ánh xạ với kiểu `NUMERIC` trong PostgreSQL.

### 3.2. Sơ đồ luồng

``` text
CSV / Licensed Data Provider
          |
          v
Market Data Adapter (Python)
          |
          v
Validation + Normalization
          |
          v
PostgreSQL (6 Schemas: market, analysis, strategy, trading, portfolio, system)
          |
          v
Python Backend (FastAPI Modular Monolith)
  ├── Analysis Modules:
  │     - Indicators
  │     - Scanner
  │     - Strategies
  │     - Backtesting
  │     - AI Analysis (isolated, read-only context)
  └── Core Trading Modules:
        - Signals
        - Risk Management (mandatory gate)
        - Trade Proposals & Human Approval
        - Paper Broker
        - Portfolio & Ledger Reconciliation
          |
          v
Angular Dashboard
```

### 3.3. Ranh giới trách nhiệm

**Python Analysis Modules (`market_data`, `indicators`, `screening`, `strategies`, `backtesting`, `ai`)**
- Tính chỉ báo và feature.
- Scanner và strategy signal.
- Backtest.
- Phân tích tin tức/báo cáo bằng LLM.
- Module `ai` hoàn toàn cô lập: không có quyền truy cập/gọi trực tiếp `PaperBrokerAdapter`, không được tự approve proposal hoặc sửa cấu hình rủi ro.

**Python Core Trading Modules (`risk`, `trading`, `portfolio`, `system`)**
- Quản lý dữ liệu nghiệp vụ và REST API.
- Quản lý chiến lược/config phiên bản.
- Quản lý proposal, approval, order và portfolio.
- Risk validation bắt buộc phía server trước và tại thời điểm approve.
- Paper Broker và đối soát sổ cái (ledger reconciliation).
- Audit log và authorization.

**Angular (`trading-dashboard`)**
- Chỉ hiển thị và gửi yêu cầu người dùng.
- Không tự quyết định risk hoặc trạng thái giao dịch.
- Không được coi việc ẩn/hiện nút là kiểm soát bảo mật.

### 3.4. Adapter interfaces

Tạo abstraction (Python Protocol / ABC) để thay provider mà không đổi nghiệp vụ:

-   `MarketDataProvider`
-   `BrokerAdapter`
-   `AiAnalysisProvider`

MVP triển khai:
-   `CsvMarketDataProvider`
-   `PaperBrokerAdapter`
-   `MockAiAnalysisProvider` cho test; LLM adapter thật là tùy chọn có cấu hình.

Không tạo adapter broker thật trong MVP.

------------------------------------------------------------------------

## 4. Non-Functional Requirements

### Reliability & data integrity

-   Import CSV idempotent: chạy lại không tạo dữ liệu trùng.
-   Có source, import batch, timestamp và trạng thái validation.
-   Lưu giá bằng `NUMERIC`, không dùng floating point cho tiền/giá trong
    database.
-   Mọi timestamp lưu UTC (`TIMESTAMPTZ`); ngày giao dịch dùng `DATE`,
    timezone thị trường `Asia/Ho_Chi_Minh`.
-   Mọi thay đổi trạng thái proposal/order có audit trail.
-   Order và fill là hai thực thể riêng; một order có thể có nhiều
    fills.
-   Có backup/restore hướng dẫn cho PostgreSQL.

### Security

-   Secret chỉ qua environment variables.
-   `.env` nằm trong `.gitignore`.
-   PostgreSQL chỉ bind localhost trong local setup.
-   CORS chỉ cho origin dashboard local.
-   Có authentication tối thiểu cho dashboard/API nếu API không chỉ bind
    loopback.
-   AI prompt và tin tức là untrusted input; không cho phép prompt
    injection thực thi hành động.
-   Không log API keys, tokens hoặc dữ liệu nhạy cảm.

### Observability

-   Structured logging.
-   Correlation ID cho request/job.
-   Ghi job status, thời gian chạy, số bản ghi xử lý và lỗi.
-   Health endpoints cho API, analysis engine và database.

### Quality

-   Unit test cho chỉ báo, risk sizing, state transitions và portfolio
    calculations.
-   Integration test cho import, proposal approval và paper order.
-   Deterministic tests: cùng input/config/version phải cho cùng output.
-   Pin dependency versions và cung cấp lock file phù hợp.

------------------------------------------------------------------------

## 5. Repository Structure

``` text
personal-ai-trading/
├── src/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/            # Config, logging, security, database session
│   │   │   ├── api/             # FastAPI routers (/api/v1/...)
│   │   │   ├── market_data/     # Stocks, CSV provider, import batches, validation
│   │   │   ├── indicators/      # SMA, EMA, RSI, MACD, ATR, Volume Avg
│   │   │   ├── screening/       # Stock scanner
│   │   │   ├── strategies/      # Trend Following, Pullback, versioning
│   │   │   ├── backtesting/     # Walk-forward, metrics, execution simulation
│   │   │   ├── ai/              # Isolated AI analysis & schema validation
│   │   │   ├── risk/            # Mandatory Risk Engine, position sizing, kill switch
│   │   │   ├── trading/         # Proposals, human approvals, orders, Paper Broker
│   │   │   ├── portfolio/       # Accounts, positions, ledger, reconciliation
│   │   │   ├── system/          # Job runs, audit logs, app settings, scheduler
│   │   │   └── schemas/         # Pydantic DTOs & API contracts
│   │   ├── alembic/             # Database migrations
│   │   ├── tests/
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── frontend/
│       └── trading-dashboard/
├── database/
│   ├── seeds/
│   └── scripts/
├── infrastructure/
│   ├── docker/
│   └── postgres/
├── docs/
│   ├── architecture/
│   ├── database/
│   ├── api/
│   ├── strategies/
│   └── decisions/
├── scripts/
│   ├── import-market-data.py
│   ├── run-backtest.py
│   └── daily-analysis.py
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

Agent có thể điều chỉnh tên project/file theo convention thực tế nhưng
phải giữ các module và ranh giới trách nhiệm nêu trên.

------------------------------------------------------------------------

## 6. Database Schema

Dùng một PostgreSQL database tên `trading_db`, chia schema logic:

-   `market`
-   `analysis`
-   `strategy`
-   `trading`
-   `portfolio`
-   `system`

### 6.1. `market`

#### `market.stocks`

-   `id UUID PRIMARY KEY`
-   `symbol VARCHAR(20) NOT NULL UNIQUE`
-   `exchange VARCHAR(20) NOT NULL`
-   `company_name VARCHAR(255)`
-   `sector VARCHAR(100)`
-   `is_active BOOLEAN NOT NULL DEFAULT TRUE`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `market.data_sources`

-   `id UUID PRIMARY KEY`
-   `name VARCHAR(100) NOT NULL`
-   `provider_type VARCHAR(30) NOT NULL` --- CSV/API
-   `license_notes TEXT`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `market.import_batches`

-   `id UUID PRIMARY KEY`
-   `source_id UUID REFERENCES market.data_sources(id)`
-   `file_name TEXT`
-   `checksum VARCHAR(128)`
-   `started_at TIMESTAMPTZ`
-   `completed_at TIMESTAMPTZ`
-   `status VARCHAR(30)`
-   `rows_read INTEGER`
-   `rows_inserted INTEGER`
-   `rows_rejected INTEGER`
-   `error_detail JSONB`

#### `market.daily_prices`

-   `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
-   `stock_id UUID NOT NULL REFERENCES market.stocks(id)`
-   `source_id UUID NOT NULL REFERENCES market.data_sources(id)`
-   `import_batch_id UUID REFERENCES market.import_batches(id)`
-   `trading_date DATE NOT NULL`
-   `open NUMERIC(18,4) NOT NULL`
-   `high NUMERIC(18,4) NOT NULL`
-   `low NUMERIC(18,4) NOT NULL`
-   `close NUMERIC(18,4) NOT NULL`
-   `adjusted_close NUMERIC(18,4)`
-   `volume BIGINT NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   Unique `(stock_id, trading_date, source_id)`

Ràng buộc dữ liệu: - Giá phải dương. - `high >= low`. - `high >= open`
và `high >= close`. - `low <= open` và `low <= close`. - `volume >= 0`.

Không trộn dữ liệu giá điều chỉnh và chưa điều chỉnh trong cùng một phép
tính mà không có quy tắc rõ ràng. Ghi nhận phương pháp điều chỉnh và
nguồn dữ liệu.

### 6.2. `analysis`

#### `analysis.analysis_runs`

-   `id UUID PRIMARY KEY`
-   `run_type VARCHAR(30) NOT NULL`
-   `started_at TIMESTAMPTZ`
-   `completed_at TIMESTAMPTZ`
-   `status VARCHAR(30)`
-   `data_as_of DATE`
-   `parameters JSONB`
-   `error_detail JSONB`

#### `analysis.technical_indicators`

-   `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
-   `stock_id UUID NOT NULL REFERENCES market.stocks(id)`
-   `trading_date DATE NOT NULL`
-   `ma20 NUMERIC(18,4)`
-   `ma50 NUMERIC(18,4)`
-   `ma200 NUMERIC(18,4)`
-   `ema20 NUMERIC(18,4)`
-   `ema50 NUMERIC(18,4)`
-   `rsi14 NUMERIC(10,4)`
-   `macd NUMERIC(18,6)`
-   `macd_signal NUMERIC(18,6)`
-   `macd_histogram NUMERIC(18,6)`
-   `atr14 NUMERIC(18,4)`
-   `volume_avg20 NUMERIC(20,2)`
-   `calculation_version VARCHAR(30) NOT NULL`
-   Unique `(stock_id, trading_date, calculation_version)`

#### `analysis.stock_signals`

-   `id UUID PRIMARY KEY`
-   `stock_id UUID NOT NULL REFERENCES market.stocks(id)`
-   `strategy_version_id UUID`
-   `analysis_run_id UUID REFERENCES analysis.analysis_runs(id)`
-   `trading_date DATE NOT NULL`
-   `action VARCHAR(10) NOT NULL` --- BUY/SELL/HOLD
-   `score NUMERIC(5,2)`
-   `reference_price NUMERIC(18,4)`
-   `stop_loss NUMERIC(18,4)`
-   `reason JSONB NOT NULL`
-   `status VARCHAR(30) NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `analysis.ai_reports`

-   `id UUID PRIMARY KEY`
-   `stock_id UUID REFERENCES market.stocks(id)`
-   `signal_id UUID REFERENCES analysis.stock_signals(id)`
-   `provider VARCHAR(50)`
-   `model VARCHAR(100)`
-   `prompt_version VARCHAR(30)`
-   `input_snapshot JSONB`
-   `report JSONB`
-   `source_references JSONB`
-   `created_at TIMESTAMPTZ`
-   `status VARCHAR(30)`

AI report phải lưu input snapshot, model và prompt version để truy vết.
Không lưu secret hoặc dữ liệu tài khoản trong prompt.

### 6.3. `strategy`

#### `strategy.strategies`

-   `id UUID PRIMARY KEY`
-   `name VARCHAR(100) NOT NULL`
-   `description TEXT`
-   `strategy_type VARCHAR(50) NOT NULL`
-   `is_active BOOLEAN NOT NULL DEFAULT FALSE`
-   `created_at TIMESTAMPTZ`

#### `strategy.strategy_versions`

-   `id UUID PRIMARY KEY`
-   `strategy_id UUID NOT NULL REFERENCES strategy.strategies(id)`
-   `version INTEGER NOT NULL`
-   `configuration JSONB NOT NULL`
-   `code_version VARCHAR(100)`
-   `created_at TIMESTAMPTZ`
-   Unique `(strategy_id, version)`

#### `strategy.backtest_runs`

-   `id UUID PRIMARY KEY`
-   `strategy_version_id UUID NOT NULL REFERENCES strategy.strategy_versions(id)`
-   `start_date DATE NOT NULL`
-   `end_date DATE NOT NULL`
-   `initial_capital NUMERIC(18,2) NOT NULL`
-   `fee_rate NUMERIC(10,6)`
-   `tax_rate NUMERIC(10,6)`
-   `slippage_bps NUMERIC(10,4)`
-   `assumptions JSONB`
-   `metrics JSONB`
-   `status VARCHAR(30)`
-   `created_at TIMESTAMPTZ`

#### `strategy.backtest_trades`

-   `id UUID PRIMARY KEY`
-   `backtest_run_id UUID NOT NULL REFERENCES strategy.backtest_runs(id)`
-   `stock_id UUID NOT NULL REFERENCES market.stocks(id)`
-   `entry_date DATE`
-   `exit_date DATE`
-   `entry_price NUMERIC(18,4)`
-   `exit_price NUMERIC(18,4)`
-   `quantity INTEGER`
-   `fees NUMERIC(18,2)`
-   `taxes NUMERIC(18,2)`
-   `pnl NUMERIC(18,2)`
-   `exit_reason VARCHAR(50)`

### 6.4. `trading`

#### `trading.trade_proposals`

-   `id UUID PRIMARY KEY`
-   `signal_id UUID NOT NULL REFERENCES analysis.stock_signals(id)`
-   `symbol VARCHAR(20) NOT NULL`
-   `side VARCHAR(10) NOT NULL`
-   `proposed_quantity INTEGER NOT NULL`
-   `limit_price NUMERIC(18,4)`
-   `stop_loss NUMERIC(18,4)`
-   `estimated_cost NUMERIC(18,2)`
-   `risk_amount NUMERIC(18,2)`
-   `risk_check_result JSONB`
-   `status VARCHAR(30) NOT NULL`
-   `expires_at TIMESTAMPTZ NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `trading.approvals`

-   `id UUID PRIMARY KEY`
-   `proposal_id UUID NOT NULL REFERENCES trading.trade_proposals(id)`
-   `decision VARCHAR(20) NOT NULL`
-   `approved_by VARCHAR(100) NOT NULL`
-   `comment TEXT`
-   `approved_at TIMESTAMPTZ NOT NULL`

#### `trading.orders`

-   `id UUID PRIMARY KEY`
-   `proposal_id UUID REFERENCES trading.trade_proposals(id)`
-   `broker_name VARCHAR(50) NOT NULL DEFAULT 'PAPER'`
-   `broker_order_id VARCHAR(100)`
-   `client_order_id VARCHAR(100) NOT NULL UNIQUE`
-   `symbol VARCHAR(20) NOT NULL`
-   `side VARCHAR(10) NOT NULL`
-   `order_type VARCHAR(20) NOT NULL`
-   `quantity INTEGER NOT NULL`
-   `filled_quantity INTEGER NOT NULL DEFAULT 0`
-   `limit_price NUMERIC(18,4)`
-   `average_fill_price NUMERIC(18,4)`
-   `status VARCHAR(30) NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   `updated_at TIMESTAMPTZ NOT NULL`

#### `trading.executions`

-   `id UUID PRIMARY KEY`
-   `order_id UUID NOT NULL REFERENCES trading.orders(id)`
-   `execution_id VARCHAR(100) NOT NULL UNIQUE`
-   `quantity INTEGER NOT NULL`
-   `price NUMERIC(18,4) NOT NULL`
-   `fee NUMERIC(18,2) NOT NULL DEFAULT 0`
-   `tax NUMERIC(18,2) NOT NULL DEFAULT 0`
-   `executed_at TIMESTAMPTZ NOT NULL`

### 6.5. `portfolio`

#### `portfolio.accounts`

-   `id UUID PRIMARY KEY`
-   `account_name VARCHAR(100) NOT NULL`
-   `initial_capital NUMERIC(18,2) NOT NULL`
-   `cash_balance NUMERIC(18,2) NOT NULL`
-   `currency VARCHAR(10) NOT NULL DEFAULT 'VND'`
-   `account_type VARCHAR(20) NOT NULL DEFAULT 'PAPER'`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `portfolio.positions`

-   `id UUID PRIMARY KEY`
-   `account_id UUID NOT NULL REFERENCES portfolio.accounts(id)`
-   `stock_id UUID NOT NULL REFERENCES market.stocks(id)`
-   `quantity INTEGER NOT NULL`
-   `available_quantity INTEGER NOT NULL`
-   `average_cost NUMERIC(18,4) NOT NULL`
-   `updated_at TIMESTAMPTZ NOT NULL`
-   Unique `(account_id, stock_id)`

#### `portfolio.cash_transactions`

-   `id UUID PRIMARY KEY`
-   `account_id UUID NOT NULL REFERENCES portfolio.accounts(id)`
-   `transaction_type VARCHAR(30) NOT NULL`
-   `amount NUMERIC(18,2) NOT NULL`
-   `reference_type VARCHAR(30)`
-   `reference_id UUID`
-   `description TEXT`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `portfolio.daily_snapshots`

-   `id UUID PRIMARY KEY`
-   `account_id UUID NOT NULL REFERENCES portfolio.accounts(id)`
-   `snapshot_date DATE NOT NULL`
-   `cash_balance NUMERIC(18,2) NOT NULL`
-   `market_value NUMERIC(18,2) NOT NULL`
-   `nav NUMERIC(18,2) NOT NULL`
-   `unrealized_pnl NUMERIC(18,2)`
-   `realized_pnl NUMERIC(18,2)`
-   Unique `(account_id, snapshot_date)`

**Accounting rule:** executions và cash transactions là dữ liệu giao
dịch gốc; positions, cash balance và snapshots là dữ liệu tổng hợp. Phải
có logic tái dựng và đối soát, không cập nhật số dư tùy tiện từ
frontend.

### 6.6. `system`

#### `system.risk_configs`

-   `id UUID PRIMARY KEY`
-   `name VARCHAR(100) NOT NULL`
-   `configuration JSONB NOT NULL`
-   `is_active BOOLEAN NOT NULL DEFAULT FALSE`
-   `created_at TIMESTAMPTZ`

#### `system.job_runs`

-   `id UUID PRIMARY KEY`
-   `job_name VARCHAR(100) NOT NULL`
-   `started_at TIMESTAMPTZ`
-   `completed_at TIMESTAMPTZ`
-   `status VARCHAR(30)`
-   `records_processed INTEGER`
-   `error_detail JSONB`

#### `system.audit_logs`

-   `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
-   `actor VARCHAR(100) NOT NULL`
-   `action VARCHAR(100) NOT NULL`
-   `entity_type VARCHAR(100)`
-   `entity_id VARCHAR(100)`
-   `before_state JSONB`
-   `after_state JSONB`
-   `correlation_id VARCHAR(100)`
-   `created_at TIMESTAMPTZ NOT NULL`

#### `system.app_settings`

-   `key VARCHAR(100) PRIMARY KEY`
-   `value JSONB NOT NULL`
-   `updated_at TIMESTAMPTZ NOT NULL`

### 6.7. Database implementation requirements

-   Tạo migration cho toàn bộ schema, index và constraints.
-   Tạo seed danh sách mã cổ phiếu mẫu có nhãn sample; không giả định
    danh sách mẫu là danh sách niêm yết đầy đủ.
-   Index tối thiểu: `(stock_id, trading_date)`, `(status, created_at)`,
    `(account_id, snapshot_date)`.
-   Dùng `NUMERIC` cho giá, tiền và tỷ lệ cần độ chính xác.
-   Không dùng cascade delete cho lịch sử order/execution/ledger.
-   Tạo repository/query tối ưu cho lịch sử giá và dashboard.
-   Cân nhắc partition `daily_prices` chỉ khi dữ liệu thực tế đủ lớn;
    không partition quá sớm.

------------------------------------------------------------------------

## 7. Trading Strategies

MVP có hai chiến lược có thể giải thích. Tham số phải cấu hình và
version hóa.

### 7.1. Trend Following

Điều kiện nghiên cứu ban đầu: - Close \> MA20. - MA20 \> MA50. - RSI14
trong khoảng 50--70. - Volume \> 1.2 × volume average 20 phiên. - Có đủ
dữ liệu warm-up cho mọi indicator.

Tín hiệu SELL/exit phải được định nghĩa rõ trong strategy config, ví dụ
xu hướng gãy hoặc stop rule. Không được chỉ có điều kiện BUY mà thiếu
quy tắc thoát lệnh.

### 7.2. Pullback

Điều kiện nghiên cứu ban đầu: - Xu hướng trung hạn tăng. - Giá điều
chỉnh về vùng MA20 hoặc vùng hỗ trợ được định nghĩa. - RSI hồi phục từ
vùng yếu. - Có xác nhận giá/khối lượng theo quy tắc. - Có quy tắc
invalidation và exit.

### 7.3. Signal contract

Mỗi signal cần có: - `symbol` - `strategy_id` - `strategy_version` -
`signal_date` - `data_as_of` - `action` - `score` - `reference_price` -
`stop_loss` - `reason[]` - `warnings[]` - `source_data_version`

Score là điểm nội bộ, không được diễn giải là xác suất sinh lời nếu chưa
được hiệu chuẩn và kiểm định.

------------------------------------------------------------------------

## 8. Backtesting Requirements

Backtest là hạng mục bắt buộc trước Paper Trading.

### 8.1. Chống sai lệch

-   Không look-ahead bias.
-   Không survivorship bias nếu có thể tránh; ghi rõ giới hạn universe
    dữ liệu.
-   Dùng dữ liệu đã biết tại thời điểm ra quyết định.
-   Signal sau phiên T chỉ được giả lập thực thi từ phiên T+1 hoặc theo
    execution rule đã công bố.
-   Tính phí mua/bán, thuế bán, trượt giá và giới hạn lô giao dịch.
-   Mô phỏng tiền mặt, vị thế, sức mua và lệnh không khớp.
-   Không dùng giá điều chỉnh cho execution giả lập nếu không xử lý nhất
    quán corporate actions.
-   Chia train/validation/test theo thời gian; dùng walk-forward
    validation.
-   Không tối ưu tham số trên toàn bộ dữ liệu rồi báo kết quả trên chính
    dữ liệu đó.

### 8.2. Metrics

Báo cáo tối thiểu: - Total Return. - CAGR nếu khoảng thời gian phù
hợp. - Maximum Drawdown. - Win Rate. - Profit Factor. - Expectancy per
trade. - Average win / average loss. - Number of trades. - Exposure /
time in market. - Turnover. - Fees, taxes, slippage. - Benchmark
comparison (ví dụ VN-Index nếu dữ liệu phù hợp).

Backtest phải lưu strategy version, dữ liệu đầu vào, tham số, giả định
và code version.

------------------------------------------------------------------------

## 9. Risk Management

Risk Engine chạy trong module `risk` của Python Backend và là cổng bắt buộc trước khi tạo order.

### 9.1. Default paper configuration

Các giá trị dưới đây chỉ là cấu hình thử nghiệm, phải chỉnh được và
không phải khuyến nghị đầu tư:

``` json
{
  "max_position_percent": 20,
  "max_risk_per_trade_percent": 1,
  "max_daily_loss_percent": 2,
  "max_open_positions": 5,
  "max_portfolio_allocation_percent": 70,
  "require_human_approval": true,
  "trading_enabled": true
}
```

### 9.2. Position sizing

``` text
risk_amount = NAV * risk_percent
risk_per_share = entry_price - stop_loss
quantity_by_risk = floor(risk_amount / risk_per_share)
quantity_by_position_cap = floor(max_position_value / entry_price)
quantity_by_cash = floor(available_cash / estimated_total_cost)

final_quantity = minimum of all applicable limits
```

Sau đó áp dụng quy tắc lô giao dịch hiện hành của từng sàn/mã và làm
tròn xuống. Nếu khối lượng hợp lệ bằng 0 thì từ chối proposal.

### 9.3. Risk checks

-   Proposal chưa hết hạn.
-   Dữ liệu giá đủ mới theo policy.
-   Stop loss hợp lệ và nằm đúng phía so với entry.
-   Có đủ cash/sức mua.
-   Không vượt max position.
-   Không vượt tổng allocation.
-   Không vượt số vị thế.
-   Không vượt daily loss limit.
-   Không có order/proposal xung đột.
-   Tính phí, thuế và slippage dự kiến.
-   Có Kill Switch.
-   Revalidate toàn bộ risk khi người dùng approve, không chỉ khi tạo
    proposal.

### 9.4. Approval security

-   Chỉ user đã xác thực mới được approve/reject.
-   Server kiểm tra trạng thái và expiry trong transaction.
-   Ghi audit log.
-   Dùng concurrency control để không thể approve cùng proposal hai lần.
-   Approval phải gắn với snapshot đề xuất cụ thể; nếu
    quantity/price/stop thay đổi thì yêu cầu duyệt lại.
-   Không có endpoint public để tự động approve.
-   Không có AI tool được cấp quyền approve hoặc place order.

------------------------------------------------------------------------

## 10. Paper Broker & Order Lifecycle

### 10.1. Order states

``` text
PendingApproval
  -> Rejected
  -> Expired
  -> Approved
       -> RiskValidation
            -> Blocked
            -> Submitted
                 -> PartiallyFilled
                 -> Filled
                 -> Cancelled
                 -> Failed
```

Định nghĩa transition hợp lệ trong Domain, không cho phép controller cập
nhật status tùy ý.

### 10.2. Paper Broker

Paper Broker phải hỗ trợ: - Market/limit order theo phạm vi MVP. - Lệnh
không khớp. - Khớp một phần. - Khớp hoàn toàn. - Hủy lệnh. - Phí và thuế
cấu hình được. - Slippage cấu hình được. - Kiểm tra sức mua và khối
lượng. - Deterministic simulation để test.

Không mặc định mọi lệnh đều khớp ở giá đóng cửa. Xác định execution
model, ví dụ dùng giá mở cửa phiên tiếp theo có điều chỉnh slippage,
hoặc limit fill dựa trên OHLC với giả định bảo thủ được ghi rõ.

### 10.3. Idempotency

-   `client_order_id` unique.
-   Không retry mù khi chưa biết kết quả.
-   Mỗi execution có unique ID.
-   Update order và ledger phải có transaction hoặc cơ chế xử lý nhất
    quán.
-   Có reconciliation job để tính lại positions/cash từ ledger và
    executions.

------------------------------------------------------------------------

## 11. AI Analysis

AI là lớp giải thích và tổng hợp, không phải bộ phận điều khiển giao
dịch.

### Input

-   Signal và strategy rationale.
-   Technical indicator snapshot.
-   Financial metrics nếu có nguồn đáng tin cậy.
-   News articles và metadata nguồn/ngày.
-   Warnings về độ mới/độ đầy đủ dữ liệu.

### Output JSON có schema

-   `summary`
-   `positive_factors[]`
-   `negative_factors[]`
-   `risks[]`
-   `conflicting_evidence[]`
-   `source_references[]`
-   `data_as_of`
-   `limitations[]`

### Rules

-   Không bịa nguồn, số liệu hoặc giá.
-   Nếu thiếu dữ liệu phải ghi rõ.
-   Phân biệt fact, inference và opinion.
-   Không phát sinh quantity hoặc gửi lệnh.
-   Tin tức và tài liệu bên ngoài là untrusted content.
-   Validate output bằng schema; retry có giới hạn.
-   Lưu provider/model/prompt version và input snapshot.
-   Có thể tắt AI mà hệ thống phân tích kỹ thuật/backtest vẫn hoạt động.

------------------------------------------------------------------------

## 12. API Contract

Base path: `/api/v1`

### Python FastAPI Backend

  Method   Endpoint                        Mục đích
  -------- ------------------------------- ----------------------
  GET      `/health`                       Health check (API & DB)
  GET      `/stocks`                       Danh sách cổ phiếu
  GET      `/market/overview`              Tổng quan thị trường
  GET      `/stocks/{symbol}/history`      Lịch sử giá
  GET      `/stocks/{symbol}/indicators`   Chỉ báo kỹ thuật
  POST     `/indicators/calculate`         Tính toán indicators
  POST     `/market/imports`               Tạo import job (CSV)
  GET      `/market/imports/{id}`          Trạng thái import
  POST     `/scanner/run`                  Chạy stock scanner
  GET      `/signals`                      Danh sách tín hiệu
  POST     `/signals/generate`             Sinh tín hiệu chiến lược
  POST     `/ai/analyze`                   Phân tích AI cho tín hiệu
  GET      `/proposals`                    Đề xuất chờ duyệt
  POST     `/proposals/{id}/approve`       Duyệt proposal (Human Approval)
  POST     `/proposals/{id}/reject`        Từ chối proposal
  GET      `/orders`                       Danh sách lệnh Paper
  GET      `/portfolio`                    Tổng quan danh mục
  GET      `/portfolio/snapshots`          NAV lịch sử
  GET      `/risk`                         Risk status & cấu hình
  POST     `/backtests`                    Tạo & chạy backtest
  GET      `/backtests/{id}`               Kết quả backtest

-   Dùng Pydantic v2 schemas cho toàn bộ request/response DTOs.
-   Sử dụng kiểu `Decimal` cho các trường tiền tệ, giá và tỷ lệ.
-   Có API versioning (`/api/v1`).
-   Chuẩn hóa error response.
-   Có pagination/filter/sort cho list endpoint.
-   Module `ai` chỉ được gọi qua service nội bộ với dữ liệu read-only; tuyệt đối không có quyền gọi sang `trading` hoặc `paper_broker`.

------------------------------------------------------------------------

## 13. Daily Workflow & Scheduling

Lịch dự kiến theo `Asia/Ho_Chi_Minh`, sau khi provider xác nhận dữ liệu
ngày đã hoàn tất:

1.  Import daily market data.
2.  Validate dữ liệu.
3.  Tính indicators.
4.  Run stock scanner.
5.  Run strategies.
6.  AI analysis (nếu bật).
7.  Risk assessment.
8.  Create proposals.
9.  Notify/show proposals cho người dùng.
10. Người dùng approve/reject.
11. Paper Broker xử lý lệnh theo execution model.
12. Reconcile portfolio.
13. Generate daily report.

Mọi job phải: - Idempotent. - Có job run record. - Có retry policy có
giới hạn. - Không chạy phân tích nếu dữ liệu chưa hoàn tất hoặc
validation fail. - Không tạo proposal trùng cho cùng
signal/strategy/version. - Hỗ trợ chạy lại theo ngày và mã cổ phiếu.

------------------------------------------------------------------------

## 14. Frontend Scope

Angular dashboard gồm các màn hình:

1.  **Overview**
    -   Tổng NAV paper.
    -   Cash, market value, P&L.
    -   Danh sách vị thế.
    -   Tình trạng job gần nhất.
2.  **Market**
    -   Danh sách mã.
    -   Lịch sử OHLCV.
    -   Biểu đồ giá và indicators.
    -   Nguồn dữ liệu và ngày cập nhật.
3.  **Stock Scanner**
    -   Bộ lọc chiến lược.
    -   Danh sách tín hiệu.
    -   Lý do và warnings.
4.  **Signal Detail**
    -   Indicator snapshot.
    -   Strategy/version.
    -   AI report và nguồn.
    -   Risk assessment.
5.  **Trade Approval**
    -   BUY/SELL.
    -   Quantity, limit price, stop loss.
    -   Estimated cost/risk.
    -   Expiry.
    -   Approve/reject và comment.
    -   Cảnh báo khi proposal hết hạn/thay đổi.
6.  **Orders**
    -   Order status.
    -   Partial fills.
    -   Execution history.
7.  **Portfolio**
    -   Cash/positions/NAV.
    -   Realized/unrealized P&L.
    -   Daily snapshots.
8.  **Risk Settings**
    -   Các hạn mức.
    -   Kill switch.
    -   Audit history.
    -   Thay đổi risk config cần xác nhận và audit.

------------------------------------------------------------------------

## 15. Docker Compose

MVP tối thiểu:
- `trading-backend` (Python 3.12 + FastAPI)
- `trading-frontend` (Angular)
- `postgres` (PostgreSQL 16)

Có thể thêm `trading-worker` (chạy cùng Docker image với `trading-backend`) nếu muốn tách riêng APScheduler worker khỏi API process. Không bắt buộc Redis.

Yêu cầu: - Healthcheck PostgreSQL. - Volume persistent. -
`.env.example`. - `.gitignore` cho `.env`, logs, build outputs và local
data. - Port database bind `127.0.0.1` khi chỉ chạy local. - Có lệnh
migrate/seed rõ ràng. - Có hướng dẫn backup/restore.

Ví dụ biến môi trường:

``` dotenv
DB_PASSWORD=change_me
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=trading_db
POSTGRES_USER=trader
AI_PROVIDER=
AI_API_KEY=
AI_MODEL=
```

Không dùng giá trị mẫu này làm secret production.

------------------------------------------------------------------------

## 16. Implementation Roadmap

### Sprint 1 --- Foundation

Tasks:
- [x] Inspect repository và xác nhận baseline.
- [x] Tạo monorepo structure.
- [x] Khởi tạo Python FastAPI project (Modular Monolith structure).
- [x] Khởi tạo Angular app.
- [x] Docker Compose PostgreSQL, Backend và Frontend.
- [x] Health endpoints.
- [x] Cấu hình structured logging.
- [x] SQLAlchemy 2.0 models, Alembic migrations và 6 database schemas.
- [x] README.md, AGENTS.md, DESIGN.md, PROJECT.md hướng dẫn chạy local & quy chuẩn dự án.

Acceptance criteria: - `docker compose up --build` chạy được các
container. - FastAPI Backend và PostgreSQL healthy. - Có thể chạy Alembic
migration. - Không có secret trong Git. - Có smoke tests.

### Sprint 2 --- Market Data

Tasks:
- [x] Tạo stock CRUD/read APIs.
- [x] Thiết kế CSV format và validation rules.
- [x] Implement CSV provider.
- [x] Import batch tracking/checksum.
- [x] Idempotent upsert daily prices.
- [x] Phát hiện duplicate, missing dates, invalid OHLC.
- [x] Lưu source metadata.
- [x] Tạo sample CSV có nhãn SAMPLE, không giả làm dữ liệu thật.
- [x] Unit/integration tests.

Acceptance criteria: - Import cùng file hai lần không nhân đôi dữ
liệu. - Dữ liệu lỗi được báo cáo và không âm thầm chấp nhận. - Có thể
query OHLCV theo symbol/date range. - Biết được nguồn và batch của mỗi
record.

### Sprint 3 --- Technical Analysis

Tasks:
- [x] Implement SMA20/50/200.
- [x] Implement EMA20/50.
- [x] Implement RSI14.
- [x] Implement MACD.
- [x] Implement ATR14.
- [x] Implement volume average 20.
- [x] Xác định warm-up period và missing-data behavior.
- [x] Persist indicators/version.
- [x] Tạo API và tests đối chiếu với bộ dữ liệu kiểm thử đã biết.

Acceptance criteria: - Kết quả deterministic. - Không tính indicator khi
thiếu dữ liệu warm-up. - Không dùng dữ liệu tương lai. - Có test cho
edge cases, flat prices, missing rows và zero volume.

### Sprint 4 --- Strategy & Backtesting

Tasks:
- [x] Strategy interface/base class.
- [x] Trend Following strategy.
- [x] Pullback strategy.
- [x] Strategy config/version.
- [x] Signal persistence.
- [x] Backtest engine.
- [x] Execution model từ phiên kế tiếp.
- [x] Fee/tax/slippage configuration.
- [x] Lot size and cash constraints.
- [x] Walk-forward/time split.
- [x] Metrics và report.

Acceptance criteria: - Backtest tái lập được với cùng input/version. -
Không look-ahead bias. - Có phí, thuế, slippage. - Có benchmark và các
metrics bắt buộc. - Có test xác minh signal ngày T không được khớp tại
close ngày T nếu signal chỉ được tạo sau phiên.

### Sprint 5 --- AI Analysis

Tasks:
- [x] AI provider abstraction.
- [x] Mock provider cho tests.
- [x] LLM provider cấu hình qua environment.
- [x] Prompt/schema versioning.
- [x] Structured JSON output validation.
- [x] Phân tích tín hiệu và tin tức có nguồn.
- [x] Lưu input snapshot/model/prompt version.
- [x] Timeout, retry giới hạn và fallback.
- [x] Security tests cho prompt injection.

Acceptance criteria: - AI có thể tắt mà các chức năng kỹ thuật vẫn
chạy. - Không có output không hợp lệ được lưu như report thành công. -
Report nêu rõ thiếu dữ liệu/nguồn. - AI không có quyền gọi broker hoặc
approve proposal.

### Sprint 6 --- Risk & Paper Trading

Tasks:
- [x] Risk config và versioning.
- [x] Position sizing.
- [x] Risk checks.
- [x] Proposal creation/expiry.
- [x] Approval/rejection workflow.
- [x] Concurrency protection.
- [x] Paper Broker.
- [x] Order state machine.
- [x] Partial fill/execution.
- [x] Cash ledger và portfolio projection.
- [x] Reconciliation job.
- [x] Kill switch.
- [x] Audit logs.

Acceptance criteria: - Không tạo paper order nếu proposal chưa được
approve. - Approve cùng proposal đồng thời chỉ tạo tối đa một order. -
Proposal hết hạn không thể approve. - Risk được revalidate khi
approve. - Partial fills cập nhật đúng quantity, cash và position. - Có
thể rebuild portfolio từ ledger/executions. - Kill switch chặn tạo order
mới.

### Sprint 7 --- Dashboard & Validation

Tasks:
- [x] Overview.
- [x] Market/stock detail.
- [x] Scanner.
- [x] Signal detail.
- [x] AI report.
- [x] Proposal approval.
- [x] Orders/fills.
- [x] Portfolio/NAV.
- [x] Risk configuration.
- [x] Error/empty/loading states.
- [x] End-to-end tests.
- [x] User guide.

Acceptance criteria: - Người dùng hoàn thành được luồng import → scan →
signal → proposal → approve → paper order → portfolio. - Dashboard không
tự quyết định hoặc bypass backend validation. - Có audit trail cho thao
tác quan trọng. - Toàn bộ hệ thống chạy local bằng Docker Compose.

------------------------------------------------------------------------

## 17. Definition of Done

Một task chỉ được coi là hoàn thành khi: - Code đã được implement. - Có
tests phù hợp. - Tests/build/lint chạy thành công hoặc ghi rõ blocker. -
Không có secret hoặc dữ liệu nhạy cảm trong repository. -
API/schema/documentation được cập nhật. - Có log/exception handling phù
hợp. - Không phá vỡ acceptance criteria của sprint. - Có hướng dẫn kiểm
thử thủ công nếu cần.

Một sprint chỉ hoàn thành khi tất cả acceptance criteria đạt hoặc có
blocker được ghi nhận và người dùng chấp thuận.

------------------------------------------------------------------------

## 18. Final MVP Acceptance Checklist

-   [x] Local Docker Compose startup thành công.
-   [x] PostgreSQL migration/seed thành công.
-   [x] CSV import có validation, source tracking và idempotency.
-   [x] Daily indicators hoạt động đúng.
-   [x] Hai chiến lược sinh tín hiệu.
-   [x] Backtest không look-ahead và tính chi phí.
-   [x] AI report có nguồn và giới hạn rõ ràng.
-   [x] Risk Engine chặn proposal không hợp lệ.
-   [x] Human Approval bắt buộc.
-   [x] Paper Broker mô phỏng order/fill.
-   [x] Portfolio reconcile được từ ledger.
-   [x] Dashboard hoàn tất workflow.
-   [x] Audit log đầy đủ.
-   [x] Backup/restore được hướng dẫn.
-   [x] Không có chức năng gửi lệnh tiền thật.

## 19. Future Roadmap --- Chưa triển khai trong MVP

Chỉ xem xét sau khi MVP ổn định và Paper Trading được đánh giá đủ lâu:

1.  Chọn broker và xác minh điều khoản API, quyền sử dụng dữ liệu và
    quyền tự động hóa bằng văn bản.
2.  Implement broker market-data adapter.
3.  Implement live broker adapter trong môi trường tách biệt.
4.  Bổ sung xác thực mạnh, OTP/2FA theo yêu cầu broker.
5.  Bổ sung live order reconciliation, circuit breaker và emergency
    stop.
6.  Chỉ bật live execution sau khi có kiểm thử, phê duyệt rõ ràng và
    giới hạn vốn.
7.  Cân nhắc Redis, message broker, microservices hoặc Kubernetes khi có
    nhu cầu thực tế.

**Không tự động chuyển Paper Broker sang Live Broker. Việc kích hoạt
giao dịch thật phải là một dự án/phase riêng, yêu cầu người dùng xác
nhận rõ ràng.**

------------------------------------------------------------------------

## 20. Báo cáo tiến độ cho người dùng

Sau mỗi sprint, AI Agent phải trả lời theo mẫu:

``` text
Sprint:
Status: COMPLETED / BLOCKED / IN_PROGRESS

Implemented:
- ...

Files changed:
- ...

Database/API changes:
- ...

Tests:
- Passed:
- Failed:
- Not run:

How to run:
- ...

Acceptance criteria:
- Passed:
- Pending:

Known issues / risks:
- ...

Next recommended tasks:
- ...
```

Khi bắt đầu, hãy thực hiện **Sprint 1 --- Foundation** trước. Không
triển khai các sprint tiếp theo trong cùng một đợt nếu Sprint 1 chưa
được kiểm thử và nghiệm thu.
