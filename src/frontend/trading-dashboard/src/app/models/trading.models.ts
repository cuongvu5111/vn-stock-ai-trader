// Ngày tạo: 2026-11-03
// Mục đích: Định nghĩa đầy đủ TypeScript interfaces khớp 100% với Pydantic DTOs từ FastAPI Backend (/api/v1/*).

export interface HealthStatus {
  status: string;
  app_name: string;
  version: string;
  environment: string;
  trading_mode: string;
  live_broker_enabled: boolean;
  database_status: string;
  registered_schemas: string[];
  timestamp_utc: string;
}

export interface StockItem {
  id: string;
  symbol: string;
  exchange: string;
  company_name: string | null;
  sector: string | null;
  is_active: boolean;
  created_at: string;
}

export interface StockListResponse {
  total: number;
  limit: number;
  offset: number;
  items: StockItem[];
}

export interface ImportBatchItem {
  id: string;
  source_id: string | null;
  source_name: string | null;
  file_name: string | null;
  checksum: string | null;
  started_at: string | null;
  completed_at: string | null;
  status: string | null;
  rows_read: number | null;
  rows_inserted: number | null;
  rows_rejected: number | null;
  error_detail: Record<string, unknown> | null;
}

export interface MarketOverviewResponse {
  total_stocks: number;
  active_stocks: number;
  total_daily_price_records: number;
  latest_trading_date: string | null;
  data_sources_count: number;
  recent_import_batches: ImportBatchItem[];
}

export interface DailyPriceItem {
  id: number;
  stock_id: string;
  source_id: string;
  source_name: string | null;
  import_batch_id: string | null;
  trading_date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  adjusted_close: string | null;
  volume: number;
  created_at: string;
}

export interface StockHistoryResponse {
  symbol: string;
  exchange: string;
  company_name: string | null;
  start_date: string | null;
  end_date: string | null;
  total_records: number;
  items: DailyPriceItem[];
}

export interface TechnicalIndicatorItem {
  trading_date: string;
  ma20: string | null;
  ma50: string | null;
  ma200: string | null;
  ema20: string | null;
  ema50: string | null;
  rsi14: string | null;
  macd: string | null;
  macd_signal: string | null;
  macd_histogram: string | null;
  atr14: string | null;
  volume_avg20: string | null;
  calculation_version: string;
  warm_up_core_ready: boolean;
}

export interface StockIndicatorHistoryResponse {
  symbol: string;
  exchange: string;
  calculation_version: string;
  start_date: string | null;
  end_date: string | null;
  total_records: number;
  items: TechnicalIndicatorItem[];
}

export interface SignalContractItem {
  id: string;
  symbol: string;
  strategy_id: string;
  strategy_version: number;
  signal_date: string;
  data_as_of: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  score: string;
  reference_price: string;
  stop_loss: string | null;
  reason: string[];
  warnings: string[];
  source_data_version: string;
  status: string;
  created_at: string;
}

export interface ScannerRunResponse {
  analysis_run_id: string;
  strategy_type: string;
  strategy_version: number;
  total_scanned: number;
  signals_generated: number;
  signals: SignalContractItem[];
}

export interface SignalListResponse {
  total: number;
  items: SignalContractItem[];
}

export interface BacktestTradeItem {
  id: string;
  stock_id: string;
  symbol: string;
  entry_date: string;
  exit_date: string | null;
  entry_price: string;
  exit_price: string | null;
  quantity: number;
  fees: string;
  taxes: string;
  pnl: string | null;
  exit_reason: string | null;
}

export interface BacktestRunResponse {
  id: string;
  strategy_version_id: string;
  strategy_type: string;
  strategy_version: number;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: string;
  fee_rate: string;
  tax_rate: string;
  slippage_bps: string;
  assumptions: Record<string, unknown>;
  metrics: Record<string, unknown>;
  status: string;
  created_at: string;
  trades: BacktestTradeItem[];
}

export interface AiSourceReference {
  source_id: string;
  source_type: string;
  description: string;
  as_of_date: string;
}

export interface AiStructuredReportPayload {
  summary: string;
  positive_factors: string[];
  negative_factors: string[];
  risks: string[];
  conflicting_evidence: string[];
  source_references: AiSourceReference[];
  data_as_of: string;
  limitations: string[];
}

export interface AiReportResponse {
  id: string;
  stock_id: string | null;
  symbol: string | null;
  signal_id: string | null;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  status: string;
  input_snapshot: Record<string, unknown> | null;
  report: AiStructuredReportPayload | null;
  source_references: Record<string, unknown> | null;
  created_at: string | null;
}

export interface AiReportListResponse {
  total: number;
  items: AiReportResponse[];
}

export interface TradeProposalItem {
  id: string;
  signal_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  proposed_quantity: number;
  limit_price: string | null;
  stop_loss: string | null;
  estimated_cost: string | null;
  risk_amount: string | null;
  risk_check_result: Record<string, unknown> | null;
  status: string;
  expires_at: string;
  created_at: string;
  order_id: string | null;
}

export interface ProposalListResponse {
  total: number;
  items: TradeProposalItem[];
}

export interface ExecutionItem {
  id: string;
  order_id: string;
  execution_id: string;
  quantity: number;
  price: string;
  fee: string;
  tax: string;
  executed_at: string;
}

export interface OrderItem {
  id: string;
  proposal_id: string | null;
  broker_name: string;
  broker_order_id: string | null;
  client_order_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  order_type: string;
  quantity: number;
  filled_quantity: number;
  limit_price: string | null;
  average_fill_price: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  executions: ExecutionItem[];
}

export interface OrderListResponse {
  total: number;
  items: OrderItem[];
}

export interface PositionItem {
  symbol: string;
  exchange: string;
  quantity: number;
  available_quantity: number;
  average_cost: string;
  market_price: string;
  market_value: string;
  unrealized_pnl: string;
  weight_pct: string;
}

export interface PortfolioOverviewResponse {
  account_id: string;
  account_name: string;
  account_type: string;
  currency: string;
  initial_capital: string;
  cash_balance: string;
  market_value: string;
  nav: string;
  unrealized_pnl: string;
  realized_pnl: string;
  allocation_pct: string;
  open_positions_count: number;
  positions: PositionItem[];
}

export interface DailySnapshotItem {
  id: string;
  account_id: string;
  snapshot_date: string;
  cash_balance: string;
  market_value: string;
  nav: string;
  unrealized_pnl: string | null;
  realized_pnl: string | null;
}

export interface PortfolioSnapshotsResponse {
  total: number;
  items: DailySnapshotItem[];
}

export interface CashTransactionItem {
  id: string;
  account_id: string;
  transaction_type: string;
  amount: string;
  reference_type: string | null;
  reference_id: string | null;
  description: string | null;
  created_at: string;
}

export interface CashLedgerListResponse {
  total: number;
  items: CashTransactionItem[];
}

export interface ReconciliationReportResponse {
  account_id: string;
  is_consistent_before_rebuild: boolean;
  previous_cash_balance: string;
  rebuilt_cash_balance: string;
  discrepancies: string[];
  positions_rebuilt_count: number;
  reconciled_at: string;
}

export interface RiskConfigPayload {
  max_position_percent: string;
  max_risk_per_trade_percent: string;
  max_daily_loss_percent: string;
  max_open_positions: number;
  max_portfolio_allocation_percent: string;
  require_human_approval: boolean;
  trading_enabled: boolean;
  fee_rate: string;
  tax_rate: string;
  slippage_bps: string;
  lot_size: number;
}

export interface AuditLogItem {
  id: number;
  actor: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  correlation_id: string | null;
  created_at: string;
}

export interface RiskStatusResponse {
  config_id: string;
  config_name: string;
  configuration: RiskConfigPayload;
  kill_switch_active: boolean;
  recent_audit_logs: AuditLogItem[];
}

export interface JobRunItem {
  id: string;
  job_name: string;
  started_at: string | null;
  completed_at: string | null;
  status: string | null;
  records_processed: number | null;
  error_detail: Record<string, unknown> | null;
}

export interface JobRunListResponse {
  total: number;
  items: JobRunItem[];
}

export interface DailyWorkflowRunResponse {
  job_run_id: string;
  status: string;
  as_of_date: string | null;
  imported_rows: number;
  indicators_upserted: number;
  signals_generated: number;
  ai_reports_created: number;
  proposals_created: number;
  proposals_blocked_or_skipped: number;
  snapshot_nav: string | null;
  steps_summary: string[];
  started_at: string;
  completed_at: string;
}
