// Ngày tạo: 2026-11-03
// Mục đích: Service tập trung kết nối toàn bộ REST APIs (/api/v1/*) của FastAPI Backend.
// Lý do: Mọi quyết định tính toán, kiểm tra rủi ro, phê duyệt và đối soát sổ cái đều do Backend xử lý (Frontend không tự bypass).

import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AiReportListResponse,
  AiReportResponse,
  BacktestRunResponse,
  CashLedgerListResponse,
  DailySnapshotItem,
  DailyWorkflowRunResponse,
  HealthStatus,
  ImportBatchItem,
  JobRunListResponse,
  MarketOverviewResponse,
  OrderItem,
  OrderListResponse,
  PortfolioOverviewResponse,
  PortfolioSnapshotsResponse,
  ProposalListResponse,
  ReconciliationReportResponse,
  RiskConfigPayload,
  RiskStatusResponse,
  ScannerRunResponse,
  SignalListResponse,
  StockHistoryResponse,
  StockIndicatorHistoryResponse,
  StockItem,
  StockListResponse,
  TradeProposalItem,
} from '../models/trading.models';

@Injectable({
  providedIn: 'root',
})
export class TradingApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = '/api/v1';

  getHealth(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>(`${this.baseUrl}/health`);
  }

  // ------------------------------------------------------------------
  // System & Daily Workflow
  // ------------------------------------------------------------------
  getJobRuns(limit = 20): Observable<JobRunListResponse> {
    return this.http.get<JobRunListResponse>(`${this.baseUrl}/system/jobs`, {
      params: new HttpParams().set('limit', limit),
    });
  }

  runDailyWorkflow(payload: {
    import_sample_csv_if_empty: boolean;
    run_ai_analysis: boolean;
    create_proposals: boolean;
  }): Observable<DailyWorkflowRunResponse> {
    return this.http.post<DailyWorkflowRunResponse>(
      `${this.baseUrl}/system/daily-workflow`,
      payload
    );
  }

  // ------------------------------------------------------------------
  // Market Data & Technical Indicators
  // ------------------------------------------------------------------
  getMarketOverview(): Observable<MarketOverviewResponse> {
    return this.http.get<MarketOverviewResponse>(`${this.baseUrl}/market/overview`);
  }

  syncRealMarketData(lookbackDays = 220): Observable<{
    batch_id: string;
    source_name: string;
    symbols_synced: string[];
    rows_inserted_or_updated: number;
    latest_trading_date: string | null;
    sample_records_purged: boolean;
  }> {
    return this.http.post<{
      batch_id: string;
      source_name: string;
      symbols_synced: string[];
      rows_inserted_or_updated: number;
      latest_trading_date: string | null;
      sample_records_purged: boolean;
    }>(`${this.baseUrl}/market/sync-real`, {
      lookback_days: lookbackDays,
      purge_sample_data: true,
    });
  }

  getStocks(exchange?: string, query?: string): Observable<StockListResponse> {
    let params = new HttpParams().set('limit', 200);
    if (exchange) {
      params = params.set('exchange', exchange);
    }
    if (query) {
      params = params.set('q', query);
    }
    return this.http.get<StockListResponse>(`${this.baseUrl}/stocks`, { params });
  }

  createStock(payload: {
    symbol: string;
    exchange: string;
    company_name?: string;
    sector?: string;
    is_sample: boolean;
  }): Observable<StockItem> {
    return this.http.post<StockItem>(`${this.baseUrl}/stocks`, payload);
  }

  importCsvContent(payload: {
    csv_content: string;
    file_name: string;
    source_name: string;
    is_sample: boolean;
  }): Observable<ImportBatchItem> {
    return this.http.post<ImportBatchItem>(`${this.baseUrl}/market/imports`, payload);
  }

  getStockHistory(symbol: string, limit = 120): Observable<StockHistoryResponse> {
    return this.http.get<StockHistoryResponse>(
      `${this.baseUrl}/stocks/${encodeURIComponent(symbol)}/history`,
      { params: new HttpParams().set('limit', limit) }
    );
  }

  getStockIndicators(symbol: string, limit = 120): Observable<StockIndicatorHistoryResponse> {
    return this.http.get<StockIndicatorHistoryResponse>(
      `${this.baseUrl}/stocks/${encodeURIComponent(symbol)}/indicators`,
      { params: new HttpParams().set('limit', limit) }
    );
  }

  calculateIndicators(symbols?: string[]): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.baseUrl}/indicators/calculate`, {
      symbols: symbols ?? null,
      calculation_version: 'v1.0',
    });
  }

  // ------------------------------------------------------------------
  // Scanner, Signals & Backtesting
  // ------------------------------------------------------------------
  runScanner(payload: {
    strategy_type: string;
    only_actionable: boolean;
    symbols?: string[];
  }): Observable<ScannerRunResponse> {
    return this.http.post<ScannerRunResponse>(`${this.baseUrl}/scanner/run`, payload);
  }

  getSignals(symbol?: string, action?: string): Observable<SignalListResponse> {
    let params = new HttpParams().set('limit', 100);
    if (symbol) {
      params = params.set('symbol', symbol);
    }
    if (action) {
      params = params.set('action', action);
    }
    return this.http.get<SignalListResponse>(`${this.baseUrl}/signals`, { params });
  }

  runBacktest(payload: {
    symbol: string;
    strategy_type: string;
    start_date: string;
    end_date: string;
    initial_capital: string;
  }): Observable<BacktestRunResponse> {
    return this.http.post<BacktestRunResponse>(`${this.baseUrl}/backtests`, {
      ...payload,
      strategy_version: 1,
      fee_rate: '0.0015',
      tax_rate: '0.0010',
      slippage_bps: '10.0000',
    });
  }

  // ------------------------------------------------------------------
  // AI Analysis
  // ------------------------------------------------------------------
  analyzeSignalWithAi(signalId: string): Observable<AiReportResponse> {
    return this.http.post<AiReportResponse>(`${this.baseUrl}/ai/analyze`, {
      signal_id: signalId,
      allow_mock_when_disabled: true,
      news_articles: [],
    });
  }

  getAiReports(symbol?: string, signalId?: string): Observable<AiReportListResponse> {
    let params = new HttpParams().set('limit', 50);
    if (symbol) {
      params = params.set('symbol', symbol);
    }
    if (signalId) {
      params = params.set('signal_id', signalId);
    }
    return this.http.get<AiReportListResponse>(`${this.baseUrl}/ai/reports`, { params });
  }

  // ------------------------------------------------------------------
  // Proposals, Approvals & Paper Orders
  // ------------------------------------------------------------------
  createProposal(signalId: string, expiryMinutes = 240): Observable<TradeProposalItem> {
    return this.http.post<TradeProposalItem>(`${this.baseUrl}/proposals`, {
      signal_id: signalId,
      order_type: 'LIMIT',
      expiry_minutes: expiryMinutes,
    });
  }

  getProposals(status?: string): Observable<ProposalListResponse> {
    let params = new HttpParams().set('limit', 100);
    if (status) {
      params = params.set('status', status);
    }
    return this.http.get<ProposalListResponse>(`${this.baseUrl}/proposals`, { params });
  }

  approveProposal(
    proposalId: string,
    payload: {
      approved_by: string;
      comment?: string;
      expected_quantity: number;
      expected_limit_price?: string | null;
      expected_stop_loss?: string | null;
      auto_submit_and_fill_in_paper: boolean;
    }
  ): Observable<TradeProposalItem> {
    return this.http.post<TradeProposalItem>(
      `${this.baseUrl}/proposals/${encodeURIComponent(proposalId)}/approve`,
      payload
    );
  }

  rejectProposal(
    proposalId: string,
    payload: { rejected_by: string; comment?: string }
  ): Observable<TradeProposalItem> {
    return this.http.post<TradeProposalItem>(
      `${this.baseUrl}/proposals/${encodeURIComponent(proposalId)}/reject`,
      payload
    );
  }

  getOrders(status?: string): Observable<OrderListResponse> {
    let params = new HttpParams().set('limit', 100);
    if (status) {
      params = params.set('status', status);
    }
    return this.http.get<OrderListResponse>(`${this.baseUrl}/orders`, { params });
  }

  simulateOrderFill(
    orderId: string,
    payload: { fill_quantity: number; fill_price?: string | null }
  ): Observable<OrderItem> {
    return this.http.post<OrderItem>(
      `${this.baseUrl}/orders/${encodeURIComponent(orderId)}/simulate-fill`,
      payload
    );
  }

  cancelOrder(orderId: string, actor = 'trader_user'): Observable<OrderItem> {
    return this.http.post<OrderItem>(
      `${this.baseUrl}/orders/${encodeURIComponent(orderId)}/cancel`,
      null,
      { params: new HttpParams().set('actor', actor) }
    );
  }

  // ------------------------------------------------------------------
  // Portfolio, Snapshots, Ledger & Reconciliation
  // ------------------------------------------------------------------
  getPortfolio(): Observable<PortfolioOverviewResponse> {
    return this.http.get<PortfolioOverviewResponse>(`${this.baseUrl}/portfolio`);
  }

  getSnapshots(limit = 90): Observable<PortfolioSnapshotsResponse> {
    return this.http.get<PortfolioSnapshotsResponse>(`${this.baseUrl}/portfolio/snapshots`, {
      params: new HttpParams().set('limit', limit),
    });
  }

  createSnapshot(): Observable<DailySnapshotItem> {
    return this.http.post<DailySnapshotItem>(`${this.baseUrl}/portfolio/snapshots`, null);
  }

  getCashLedger(limit = 100): Observable<CashLedgerListResponse> {
    return this.http.get<CashLedgerListResponse>(`${this.baseUrl}/portfolio/ledger`, {
      params: new HttpParams().set('limit', limit),
    });
  }

  reconcilePortfolio(actor = 'trader_user'): Observable<ReconciliationReportResponse> {
    return this.http.post<ReconciliationReportResponse>(
      `${this.baseUrl}/portfolio/reconcile`,
      null,
      { params: new HttpParams().set('actor', actor) }
    );
  }

  // ------------------------------------------------------------------
  // Risk Configuration & Kill Switch
  // ------------------------------------------------------------------
  getRiskStatus(): Observable<RiskStatusResponse> {
    return this.http.get<RiskStatusResponse>(`${this.baseUrl}/risk`);
  }

  updateRiskConfig(payload: {
    actor: string;
    reason: string;
    configuration: RiskConfigPayload;
  }): Observable<RiskStatusResponse> {
    return this.http.put<RiskStatusResponse>(`${this.baseUrl}/risk`, payload);
  }
}
