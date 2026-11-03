// Ngày tạo: 2026-11-03
// Mục đích: Component điều phối 8 màn hình quản trị & phê duyệt giao dịch của Angular Dashboard (Sprint 7).
// Lý do:
//   - Kết nối trực tiếp tới toàn bộ Backend APIs (/api/v1/*) mà không tự ý bypass kiểm tra rủi ro/phê duyệt.
//   - Hiển thị rõ ràng các trạng thái Loading, Empty, Error bằng tiếng Việt chuyên nghiệp.

import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AiReportResponse,
  BacktestRunResponse,
  CashTransactionItem,
  DailyPriceItem,
  DailySnapshotItem,
  DailyWorkflowRunResponse,
  HealthStatus,
  JobRunItem,
  MarketOverviewResponse,
  OrderItem,
  PortfolioOverviewResponse,
  ReconciliationReportResponse,
  RiskConfigPayload,
  RiskStatusResponse,
  SignalContractItem,
  StockItem,
  TechnicalIndicatorItem,
  TradeProposalItem,
} from './models/trading.models';
import { TradingApiService } from './services/trading-api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnInit {
  private readonly api = inject(TradingApiService);

  activeTab = 'overview';
  isLoading = false;
  toastMessage = '';
  toastType: 'success' | 'error' | 'info' = 'info';

  readonly tabs = [
    { id: 'overview', label: '1. Overview' },
    { id: 'market', label: '2. Market Data' },
    { id: 'scanner', label: '3. Stock Scanner' },
    { id: 'signals', label: '4. Signal Detail & AI' },
    { id: 'proposals', label: '5. Trade Approval' },
    { id: 'orders', label: '6. Paper Orders' },
    { id: 'portfolio', label: '7. Portfolio & Ledger' },
    { id: 'risk', label: '8. Risk Settings' },
  ];

  // 1. Overview & System state
  health: HealthStatus | null = null;
  portfolio: PortfolioOverviewResponse | null = null;
  jobRuns: JobRunItem[] = [];
  lastWorkflowResult: DailyWorkflowRunResponse | null = null;

  // 2. Market Data state
  marketOverview: MarketOverviewResponse | null = null;
  stocks: StockItem[] = [];
  selectedSymbol = 'HPG';
  priceHistory: DailyPriceItem[] = [];
  indicatorHistory: TechnicalIndicatorItem[] = [];
  csvImportContent = '';
  csvFileName = 'manual_upload.csv';

  // 3. Scanner & Backtest state
  scannerStrategyType = 'TREND_FOLLOWING';
  onlyActionableSignals = false;
  signals: SignalContractItem[] = [];
  backtestSymbol = 'HPG';
  backtestStartDate = '2026-03-02';
  backtestEndDate = '2026-05-15';
  backtestResult: BacktestRunResponse | null = null;

  // 4. Signal Detail & AI Report state
  selectedSignal: SignalContractItem | null = null;
  aiReports: AiReportResponse[] = [];
  currentAiReport: AiReportResponse | null = null;

  // 5. Trade Proposals & Human Approval state
  proposals: TradeProposalItem[] = [];
  proposalFilterStatus = '';
  approverName = 'trader_cuong';
  approvalComment = 'Đã kiểm tra tín hiệu, báo cáo AI và hạn mức rủi ro.';
  autoFillOnApprove = false;

  // 6. Paper Orders & Fills state
  orders: OrderItem[] = [];
  fillQuantityMap: Record<string, number> = {};
  fillPriceMap: Record<string, string> = {};

  // 7. Portfolio, Snapshots & Cash Ledger state
  snapshots: DailySnapshotItem[] = [];
  cashLedger: CashTransactionItem[] = [];
  lastReconcileReport: ReconciliationReportResponse | null = null;

  // 8. Risk Settings & Kill Switch state
  riskStatus: RiskStatusResponse | null = null;
  editableRiskConfig: RiskConfigPayload = {
    max_position_percent: '20',
    max_risk_per_trade_percent: '1',
    max_daily_loss_percent: '2',
    max_open_positions: 5,
    max_portfolio_allocation_percent: '70',
    require_human_approval: true,
    trading_enabled: true,
    fee_rate: '0.0015',
    tax_rate: '0.0010',
    slippage_bps: '10.0000',
    lot_size: 100,
  };
  riskUpdateActor = 'risk_admin';
  riskUpdateReason = 'Cập nhật cấu hình hạn mức rủi ro từ Dashboard';

  get currentTabLabel(): string {
    return this.tabs.find((t) => t.id === this.activeTab)?.label ?? 'Overview';
  }

  ngOnInit(): void {
    this.refreshAllCoreData();
  }

  selectTab(tabId: string): void {
    this.activeTab = tabId;
    if (tabId === 'market') {
      this.loadMarketTab();
    } else if (tabId === 'scanner' || tabId === 'signals') {
      this.loadSignalsAndAi();
    } else if (tabId === 'proposals') {
      this.loadProposals();
    } else if (tabId === 'orders') {
      this.loadOrders();
    } else if (tabId === 'portfolio') {
      this.loadPortfolioDetails();
    } else if (tabId === 'risk') {
      this.loadRiskStatus();
    }
  }

  refreshAllCoreData(): void {
    this.isLoading = true;
    this.api.getHealth().subscribe({
      next: (res) => {
        this.health = res;
      },
      error: (err) => this.handleApiError(err, 'Không thể kết nối tới /api/v1/health'),
    });

    this.api.getPortfolio().subscribe({
      next: (res) => {
        this.portfolio = res;
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      },
    });

    this.api.getJobRuns().subscribe({
      next: (res) => (this.jobRuns = res.items),
    });

    this.loadRiskStatus();
    this.loadProposals();
    this.loadOrders();
  }

  // ------------------------------------------------------------------
  // 1. Overview & Daily EOD Workflow
  // ------------------------------------------------------------------
  triggerDailyWorkflow(): void {
    this.isLoading = true;
    this.showToast('Đang chạy quy trình Daily EOD Workflow (Import -> Indicators -> Scanner -> AI -> Proposals)...', 'info');
    this.api
      .runDailyWorkflow({
        import_sample_csv_if_empty: true,
        run_ai_analysis: true,
        create_proposals: true,
      })
      .subscribe({
        next: (res) => {
          this.lastWorkflowResult = res;
          this.isLoading = false;
          this.showToast(
            `Hoàn tất Daily EOD Workflow: ${res.signals_generated} tín hiệu, ${res.proposals_created} đề xuất chờ duyệt!`,
            'success'
          );
          this.refreshAllCoreData();
          this.loadMarketTab();
          this.loadSignalsAndAi();
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi chạy Daily EOD Workflow'),
      });
  }

  syncRealMarketAndRunPipeline(): void {
    this.isLoading = true;
    this.showToast('Đang xóa dữ liệu [SAMPLE] và tải 220 phiên lịch sử thật của 10 mã VN30/HOSE từ thị trường...', 'info');
    this.api.syncRealMarketData(220).subscribe({
      next: (syncRes) => {
        this.showToast(
          `Đã đồng bộ ${syncRes.rows_inserted_or_updated} phiên dữ liệu thật (${syncRes.symbols_synced.join(', ')}) tới ngày ${syncRes.latest_trading_date}! Đang tính chỉ báo & quét tín hiệu...`,
          'success'
        );
        this.triggerDailyWorkflow();
      },
      error: (err) => this.handleApiError(err, 'Không thể đồng bộ dữ liệu thị trường thật'),
    });
  }

  // ------------------------------------------------------------------
  // 2. Market Data & SVG Chart
  // ------------------------------------------------------------------
  loadMarketTab(): void {
    this.api.getMarketOverview().subscribe({
      next: (res) => (this.marketOverview = res),
    });
    this.api.getStocks().subscribe({
      next: (res) => {
        this.stocks = res.items;
        if (this.stocks.length > 0 && !this.stocks.some((s) => s.symbol === this.selectedSymbol)) {
          this.selectedSymbol = this.stocks[0].symbol;
        }
        if (this.stocks.length > 0) {
          this.loadStockSeries(this.selectedSymbol);
        }
      },
    });
  }

  loadStockSeries(symbol: string): void {
    this.selectedSymbol = symbol;
    this.api.getStockHistory(symbol, 60).subscribe({
      next: (res) => (this.priceHistory = res.items),
      error: (err) => this.handleApiError(err, `Không tải được lịch sử giá mã ${symbol}`),
    });
    this.api.getStockIndicators(symbol, 60).subscribe({
      next: (res) => (this.indicatorHistory = res.items),
    });
  }

  submitCsvImport(): void {
    if (!this.csvImportContent.trim()) {
      this.showToast('Vui lòng dán nội dung CSV trước khi bấm Import.', 'error');
      return;
    }
    this.isLoading = true;
    this.api
      .importCsvContent({
        csv_content: this.csvImportContent,
        file_name: this.csvFileName || 'upload.csv',
        source_name: 'DASHBOARD_CSV_UPLOAD',
        is_sample: true,
      })
      .subscribe({
        next: (batch) => {
          this.isLoading = false;
          this.showToast(
            `Import CSV hoàn tất (${batch.status}): thêm mới ${batch.rows_inserted} dòng, từ chối ${batch.rows_rejected} dòng.`,
            batch.rows_rejected && batch.rows_rejected > 0 ? 'info' : 'success'
          );
          this.loadMarketTab();
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi import CSV'),
      });
  }

  recalculateIndicators(): void {
    this.isLoading = true;
    this.api.calculateIndicators().subscribe({
      next: () => {
        this.isLoading = false;
        this.showToast('Đã tính toán và lưu trữ xong bộ chỉ báo kỹ thuật (MA, EMA, RSI, MACD, ATR, VolAvg20).', 'success');
        if (this.selectedSymbol) {
          this.loadStockSeries(this.selectedSymbol);
        }
      },
      error: (err) => this.handleApiError(err, 'Lỗi khi tính toán chỉ báo kỹ thuật'),
    });
  }

  get closeChartPolyline(): string {
    if (this.priceHistory.length < 2) {
      return '';
    }
    const closes = this.priceHistory.map((p) => Number(p.close));
    return this.buildSvgPoints(closes);
  }

  get ma20ChartPolyline(): string {
    if (this.indicatorHistory.length < 2) {
      return '';
    }
    const closes = this.priceHistory.map((p) => Number(p.close));
    const minVal = Math.min(...closes);
    const maxVal = Math.max(...closes);
    const vals = this.indicatorHistory.map((i) => (i.ma20 ? Number(i.ma20) : null));
    return this.buildNullableSvgPoints(vals, minVal, maxVal);
  }

  private buildSvgPoints(values: number[]): string {
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = Math.max(1, maxVal - minVal);
    const width = 680;
    const height = 160;
    return values
      .map((v, idx) => {
        const x = (idx / Math.max(1, values.length - 1)) * width;
        const y = height - ((v - minVal) / range) * (height - 20) - 10;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  private buildNullableSvgPoints(
    values: (number | null)[],
    minVal: number,
    maxVal: number
  ): string {
    const range = Math.max(1, maxVal - minVal);
    const width = 680;
    const height = 160;
    const pts: string[] = [];
    values.forEach((v, idx) => {
      if (v !== null && !Number.isNaN(v)) {
        const x = (idx / Math.max(1, values.length - 1)) * width;
        const y = height - ((v - minVal) / range) * (height - 20) - 10;
        pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      }
    });
    return pts.join(' ');
  }

  // ------------------------------------------------------------------
  // 3. Stock Scanner & Backtesting
  // ------------------------------------------------------------------
  runStockScanner(): void {
    this.isLoading = true;
    this.api
      .runScanner({
        strategy_type: this.scannerStrategyType,
        only_actionable: this.onlyActionableSignals,
      })
      .subscribe({
        next: (res) => {
          this.isLoading = false;
          this.signals = res.signals;
          if (this.signals.length > 0) {
            this.selectedSignal = this.signals[0];
          }
          this.showToast(
            `Quét chiến lược ${res.strategy_type} hoàn tất: ${res.signals_generated} tín hiệu trên ${res.total_scanned} mã.`,
            'success'
          );
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi chạy Stock Scanner'),
      });
  }

  runBacktestSimulation(): void {
    this.isLoading = true;
    this.api
      .runBacktest({
        symbol: this.backtestSymbol,
        strategy_type: this.scannerStrategyType,
        start_date: this.backtestStartDate,
        end_date: this.backtestEndDate,
        initial_capital: '30000000.00',
      })
      .subscribe({
        next: (res) => {
          this.isLoading = false;
          this.backtestResult = res;
          this.showToast(`Chạy Backtest cho mã ${res.symbol} hoàn tất (${res.trades.length} giao dịch).`, 'success');
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi chạy Backtest'),
      });
  }

  // ------------------------------------------------------------------
  // 4. Signal Detail & AI Analysis
  // ------------------------------------------------------------------
  loadSignalsAndAi(): void {
    this.api.getSignals().subscribe({
      next: (res) => {
        this.signals = res.items;
        if (!this.selectedSignal && this.signals.length > 0) {
          this.selectedSignal = this.signals[0];
        }
      },
    });
    this.api.getAiReports().subscribe({
      next: (res) => {
        this.aiReports = res.items;
        if (this.selectedSignal) {
          this.currentAiReport =
            this.aiReports.find((r) => r.signal_id === this.selectedSignal?.id) ?? this.aiReports[0] ?? null;
        }
      },
    });
  }

  inspectSignal(sig: SignalContractItem): void {
    this.selectedSignal = sig;
    this.currentAiReport = this.aiReports.find((r) => r.signal_id === sig.id) ?? null;
    this.activeTab = 'signals';
  }

  generateAiReportForSelectedSignal(): void {
    if (!this.selectedSignal) {
      return;
    }
    this.isLoading = true;
    this.api.analyzeSignalWithAi(this.selectedSignal.id).subscribe({
      next: (rep) => {
        this.isLoading = false;
        this.currentAiReport = rep;
        this.loadSignalsAndAi();
        this.showToast(`Đã tạo báo cáo giải thích AI cho mã ${rep.symbol} (status=${rep.status}).`, 'success');
      },
      error: (err) => this.handleApiError(err, 'Không thể tạo báo cáo AI'),
    });
  }

  createProposalFromSignal(sig: SignalContractItem): void {
    this.isLoading = true;
    this.api.createProposal(sig.id, 240).subscribe({
      next: (prop) => {
        this.isLoading = false;
        this.showToast(
          `Đã tạo TradeProposal cho ${prop.symbol} (${prop.proposed_quantity} cp @ ${prop.limit_price}) ở trạng thái chờ duyệt!`,
          'success'
        );
        this.loadProposals();
        this.activeTab = 'proposals';
      },
      error: (err) => this.handleApiError(err, 'Risk Engine từ chối tạo Proposal'),
    });
  }

  // ------------------------------------------------------------------
  // 5. Trade Proposals & Human Approval
  // ------------------------------------------------------------------
  loadProposals(): void {
    this.api.getProposals(this.proposalFilterStatus || undefined).subscribe({
      next: (res) => (this.proposals = res.items),
    });
  }

  isProposalExpired(prop: TradeProposalItem): boolean {
    return new Date(prop.expires_at).getTime() <= Date.now();
  }

  approveProposalItem(prop: TradeProposalItem): void {
    if (!this.approverName.trim()) {
      this.showToast('Vui lòng nhập định danh người phê duyệt (Approved By).', 'error');
      return;
    }
    this.isLoading = true;
    this.api
      .approveProposal(prop.id, {
        approved_by: this.approverName.trim(),
        comment: this.approvalComment.trim() || 'Người dùng phê duyệt từ Angular Dashboard',
        expected_quantity: prop.proposed_quantity,
        expected_limit_price: prop.limit_price,
        expected_stop_loss: prop.stop_loss,
        auto_submit_and_fill_in_paper: this.autoFillOnApprove,
      })
      .subscribe({
        next: (updated) => {
          this.isLoading = false;
          if (updated.status === 'Blocked') {
            this.showToast(
              `Proposal ${updated.symbol} bị chặn ở bước Re-validate Risk (status = Blocked). Không có lệnh nào được tạo.`,
              'error'
            );
          } else {
            this.showToast(
              `Đã phê duyệt Proposal ${updated.symbol}! Lệnh Paper đã được tạo (order_id=${updated.order_id}).`,
              'success'
            );
          }
          this.loadProposals();
          this.loadOrders();
          this.refreshAllCoreData();
        },
        error: (err) => this.handleApiError(err, 'Không thể phê duyệt Proposal'),
      });
  }

  rejectProposalItem(prop: TradeProposalItem): void {
    this.isLoading = true;
    this.api
      .rejectProposal(prop.id, {
        rejected_by: this.approverName.trim() || 'trader_user',
        comment: this.approvalComment.trim() || 'Người dùng từ chối đề xuất giao dịch.',
      })
      .subscribe({
        next: () => {
          this.isLoading = false;
          this.showToast(`Đã từ chối Proposal ${prop.symbol}.`, 'info');
          this.loadProposals();
          this.loadRiskStatus();
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi từ chối Proposal'),
      });
  }

  // ------------------------------------------------------------------
  // 6. Paper Orders & Simulated Fills
  // ------------------------------------------------------------------
  loadOrders(): void {
    this.api.getOrders().subscribe({
      next: (res) => {
        this.orders = res.items;
        this.orders.forEach((o) => {
          const rem = Math.max(0, o.quantity - o.filled_quantity);
          if (!this.fillQuantityMap[o.id]) {
            this.fillQuantityMap[o.id] = rem > 0 ? rem : 100;
          }
          if (!this.fillPriceMap[o.id] && o.limit_price) {
            this.fillPriceMap[o.id] = o.limit_price;
          }
        });
      },
    });
  }

  simulateFill(order: OrderItem): void {
    const qty = Number(this.fillQuantityMap[order.id] || order.quantity - order.filled_quantity);
    const price = this.fillPriceMap[order.id] || order.limit_price;
    this.isLoading = true;
    this.api
      .simulateOrderFill(order.id, {
        fill_quantity: qty,
        fill_price: price,
      })
      .subscribe({
        next: (updated) => {
          this.isLoading = false;
          this.showToast(
            `Đã khớp ${qty} cổ phiếu ${updated.symbol} trên Paper Broker (Trạng thái lệnh: ${updated.status}).`,
            'success'
          );
          this.loadOrders();
          this.refreshAllCoreData();
          this.loadPortfolioDetails();
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi mô phỏng khớp lệnh Paper'),
      });
  }

  cancelPaperOrder(order: OrderItem): void {
    this.isLoading = true;
    this.api.cancelOrder(order.id, this.approverName || 'trader_user').subscribe({
      next: () => {
        this.isLoading = false;
        this.showToast(`Đã hủy lệnh Paper cho mã ${order.symbol}.`, 'info');
        this.loadOrders();
        this.loadRiskStatus();
      },
      error: (err) => this.handleApiError(err, 'Không thể hủy lệnh Paper'),
    });
  }

  // ------------------------------------------------------------------
  // 7. Portfolio, Daily Snapshots, Cash Ledger & Reconciliation
  // ------------------------------------------------------------------
  loadPortfolioDetails(): void {
    this.api.getPortfolio().subscribe({
      next: (res) => (this.portfolio = res),
    });
    this.api.getSnapshots().subscribe({
      next: (res) => (this.snapshots = res.items),
    });
    this.api.getCashLedger().subscribe({
      next: (res) => (this.cashLedger = res.items),
    });
  }

  takeDailySnapshot(): void {
    this.isLoading = true;
    this.api.createSnapshot().subscribe({
      next: (snap) => {
        this.isLoading = false;
        this.showToast(`Đã chốt bản chụp NAV ngày ${snap.snapshot_date}: ${snap.nav} VND.`, 'success');
        this.loadPortfolioDetails();
      },
      error: (err) => this.handleApiError(err, 'Lỗi khi chốt Daily Snapshot'),
    });
  }

  runPortfolioReconciliation(): void {
    this.isLoading = true;
    this.api.reconcilePortfolio(this.approverName || 'trader_user').subscribe({
      next: (rep) => {
        this.isLoading = false;
        this.lastReconcileReport = rep;
        this.showToast(
          rep.is_consistent_before_rebuild
            ? 'Đối soát sổ cái hoàn tất: Số dư tiền mặt và vị thế khớp 100% với lịch sử gốc!'
            : `Đã phát hiện ${rep.discrepancies.length} sai lệch và khôi phục lại chính xác từ sổ cái gốc!`,
          rep.is_consistent_before_rebuild ? 'success' : 'info'
        );
        this.loadPortfolioDetails();
      },
      error: (err) => this.handleApiError(err, 'Lỗi khi đối soát danh mục'),
    });
  }

  // ------------------------------------------------------------------
  // 8. Risk Settings, Kill Switch & Audit Logs
  // ------------------------------------------------------------------
  loadRiskStatus(): void {
    this.api.getRiskStatus().subscribe({
      next: (res) => {
        this.riskStatus = res;
        this.editableRiskConfig = { ...res.configuration };
      },
    });
  }

  saveRiskConfiguration(): void {
    if (!this.riskUpdateReason.trim()) {
      this.showToast('Vui lòng nhập lý do thay đổi cấu hình rủi ro để lưu vào Audit Log.', 'error');
      return;
    }
    this.isLoading = true;
    this.api
      .updateRiskConfig({
        actor: this.riskUpdateActor.trim() || 'risk_admin',
        reason: this.riskUpdateReason.trim(),
        configuration: this.editableRiskConfig,
      })
      .subscribe({
        next: (res) => {
          this.isLoading = false;
          this.riskStatus = res;
          this.editableRiskConfig = { ...res.configuration };
          this.showToast(
            res.kill_switch_active
              ? '⚠️ ĐÃ KÍCH HOẠT KILL SWITCH: Mọi đề xuất và lệnh mua/bán mới đều bị khóa!'
              : 'Đã cập nhật cấu hình hạn mức rủi ro và ghi nhận vào Audit Log.',
            res.kill_switch_active ? 'error' : 'success'
          );
        },
        error: (err) => this.handleApiError(err, 'Lỗi khi cập nhật cấu hình rủi ro'),
      });
  }

  toggleKillSwitchQuick(): void {
    this.editableRiskConfig.trading_enabled = !this.editableRiskConfig.trading_enabled;
    this.riskUpdateReason = this.editableRiskConfig.trading_enabled
      ? 'Mở lại giao dịch Paper sau khi kiểm tra an toàn'
      : 'Kích hoạt khẩn cấp Kill Switch từ Dashboard';
    this.saveRiskConfiguration();
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  showToast(message: string, type: 'success' | 'error' | 'info' = 'info'): void {
    this.toastMessage = message;
    this.toastType = type;
  }

  private handleApiError(err: unknown, fallbackMsg: string): void {
    this.isLoading = false;
    if (err instanceof HttpErrorResponse) {
      const apiMsg =
        err.error?.error?.message ||
        err.error?.detail ||
        err.message ||
        fallbackMsg;
      this.showToast(`${fallbackMsg}: ${apiMsg}`, 'error');
      return;
    }
    this.showToast(fallbackMsg, 'error');
  }
}
