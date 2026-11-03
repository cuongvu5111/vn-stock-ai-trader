# Ngày tạo: 2026-11-03
# Mục đích: Bộ mô phỏng Backtest lịch sử chống Look-Ahead Bias, tính đủ phí/thuế/slippage/lô giao dịch và Walk-Forward metrics.
# Lý do:
#   - Tín hiệu tạo sau phiên T chỉ được khớp sớm nhất vào giá mở cửa (Open) của phiên T+1 (Quy tắc 8 - Implementation Plan).
#   - Áp dụng đầy đủ phí mua, phí bán, thuế bán 0.1%, trượt giá (slippage_bps) và lô giao dịch 100 cổ phiếu.
#   - Chia khoảng thời gian Walk-Forward (Train / Validation / Out-of-Sample Test) và tính đầy đủ các chỉ số tại Mục 8.2.

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence

from app.indicators.calculator import IndicatorPoint, OhlcvBar, calculate_indicator_series
from app.strategies.engine import BaseTradingStrategy, EvaluatedSignal

Q_MONEY_2 = Decimal("0.01")
Q_PRICE_4 = Decimal("0.0001")
Q_PCT_2 = Decimal("0.01")
TEN_THOUSAND = Decimal("10000")
HUNDRED = Decimal("100")
ZERO = Decimal("0")


def _q2(val: Decimal) -> Decimal:
    return val.quantize(Q_MONEY_2, rounding=ROUND_HALF_UP)


def _q4(val: Decimal) -> Decimal:
    return val.quantize(Q_PRICE_4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SimulatedTrade:
    """Bản ghi một giao dịch giả lập hoàn chỉnh từ lúc khớp mua (T+1) tới lúc đóng vị thế."""

    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    fees: Decimal
    taxes: Decimal
    pnl: Decimal
    exit_reason: str


@dataclass(frozen=True)
class BacktestSimulationResult:
    """Kết quả toàn diện của một lần chạy mô phỏng Backtest."""

    symbol: str
    start_date: date
    end_date: date
    initial_capital: Decimal
    final_nav: Decimal
    assumptions: Dict[str, Any]
    metrics: Dict[str, Any]
    trades: List[SimulatedTrade]


def _compute_period_metrics(
    bars_slice: Sequence[OhlcvBar],
    nav_series: Sequence[Decimal],
    trades_in_slice: Sequence[SimulatedTrade],
    initial_nav: Decimal,
    total_fees: Decimal,
    total_taxes: Decimal,
    total_slippage_cost: Decimal,
    days_in_market: int,
    total_turnover_value: Decimal,
    unfilled_orders_count: int,
    benchmark_return_pct: Decimal,
) -> Dict[str, Any]:
    """Tính đầy đủ bộ chỉ số đánh giá hiệu quả chiến lược theo Mục 8.2."""
    total_bars = len(bars_slice)
    final_nav = nav_series[-1] if nav_series else initial_nav

    total_return_pct = (
        _q2(((final_nav - initial_nav) / initial_nav) * HUNDRED)
        if initial_nav > ZERO
        else ZERO
    )

    # Tính CAGR nếu khoảng thời gian >= 30 ngày lịch
    cagr_pct: Optional[str] = None
    if total_bars >= 2:
        calendar_days = (bars_slice[-1].trading_date - bars_slice[0].trading_date).days
        if calendar_days >= 30 and initial_nav > ZERO and final_nav > ZERO:
            ratio = float(final_nav / initial_nav)
            years = calendar_days / 365.25
            cagr_val = (pow(ratio, 1.0 / years) - 1.0) * 100.0
            cagr_pct = str(_q2(Decimal(str(cagr_val))))

    # Tính Maximum Drawdown từ đường cong NAV
    peak = initial_nav
    max_dd_pct = ZERO
    for nav in nav_series:
        if nav > peak:
            peak = nav
        if peak > ZERO:
            dd = ((peak - nav) / peak) * HUNDRED
            if dd > max_dd_pct:
                max_dd_pct = dd
    max_dd_pct = _q2(max_dd_pct)

    num_trades = len(trades_in_slice)
    wins = [t.pnl for t in trades_in_slice if t.pnl > ZERO]
    losses = [t.pnl for t in trades_in_slice if t.pnl <= ZERO]

    win_rate_pct = (
        _q2((Decimal(len(wins)) / Decimal(num_trades)) * HUNDRED)
        if num_trades > 0
        else ZERO
    )

    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))

    if gross_loss > ZERO:
        profit_factor = str(_q2(gross_profit / gross_loss))
    elif gross_profit > ZERO:
        profit_factor = "INF"
    else:
        profit_factor = "0.00"

    expectancy = (
        _q2(sum((t.pnl for t in trades_in_slice), ZERO) / Decimal(num_trades))
        if num_trades > 0
        else ZERO
    )
    avg_win = _q2(gross_profit / Decimal(len(wins))) if wins else ZERO
    avg_loss = _q2(-gross_loss / Decimal(len(losses))) if losses else ZERO

    exposure_pct = (
        _q2((Decimal(days_in_market) / Decimal(total_bars)) * HUNDRED)
        if total_bars > 0
        else ZERO
    )

    avg_nav = (
        sum(nav_series, ZERO) / Decimal(len(nav_series))
        if nav_series
        else initial_nav
    )
    turnover_ratio = (
        _q2((total_turnover_value / avg_nav) * HUNDRED)
        if avg_nav > ZERO
        else ZERO
    )

    return {
        "initial_capital": str(_q2(initial_nav)),
        "final_nav": str(_q2(final_nav)),
        "total_return_pct": str(total_return_pct),
        "cagr_pct": cagr_pct,
        "max_drawdown_pct": str(max_dd_pct),
        "win_rate_pct": str(win_rate_pct),
        "profit_factor": profit_factor,
        "expectancy_per_trade": str(expectancy),
        "average_win": str(avg_win),
        "average_loss": str(avg_loss),
        "number_of_trades": num_trades,
        "unfilled_orders_count": unfilled_orders_count,
        "exposure_time_in_market_pct": str(exposure_pct),
        "turnover_pct": str(turnover_ratio),
        "total_fees": str(_q2(total_fees)),
        "total_taxes": str(_q2(total_taxes)),
        "total_slippage_cost": str(_q2(total_slippage_cost)),
        "benchmark_buy_and_hold_return_pct": str(benchmark_return_pct),
        "excess_return_vs_benchmark_pct": str(_q2(total_return_pct - benchmark_return_pct)),
    }


def run_backtest_simulation(
    symbol: str,
    bars: Sequence[OhlcvBar],
    strategy: BaseTradingStrategy,
    start_date: date,
    end_date: date,
    initial_capital: Decimal = Decimal("30000000.00"),
    fee_rate: Decimal = Decimal("0.0015"),
    tax_rate: Decimal = Decimal("0.0010"),
    slippage_bps: Decimal = Decimal("10.0000"),
    lot_size: int = 100,
    calculation_version: str = "v1.0",
) -> BacktestSimulationResult:
    """
    Chạy mô phỏng Backtest lịch sử cho một mã cổ phiếu:
    - Tính chỉ báo trên chuỗi lịch sử (bao gồm các phiên trước start_date để làm warm-up).
    - Trong khoảng [start_date, end_date]:
      + Tín hiệu sinh ra sau khi kết thúc phiên T (`bar[t]`) được đưa vào `pending_signal`.
      + `pending_signal` chỉ được khớp sớm nhất vào giá `Open` của phiên `T+1` (`bar[t+1].open` +/- slippage).
      + Tuyệt đối không khớp tại giá `Close` của phiên `T`.
    """
    sorted_all_bars = sorted(bars, key=lambda b: b.trading_date)
    all_indicators: List[IndicatorPoint] = calculate_indicator_series(
        sorted_all_bars, calculation_version=calculation_version
    )

    active_indices = [
        idx
        for idx, b in enumerate(sorted_all_bars)
        if start_date <= b.trading_date <= end_date
    ]

    if not active_indices:
        empty_assumptions = {
            "execution_model": "NEXT_BAR_OPEN_WITH_SLIPPAGE (T+1 Open)",
            "no_look_ahead_enforced": True,
            "fee_rate": str(fee_rate),
            "tax_rate": str(tax_rate),
            "slippage_bps": str(slippage_bps),
            "lot_size": lot_size,
            "overfitting_disclaimer": (
                "Kết quả Backtest lịch sử không đảm bảo lợi nhuận tương lai. "
                "Cần kiểm tra hiệu quả trên tập Out-of-Sample trong walk_forward_splits."
            ),
        }
        return BacktestSimulationResult(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_nav=initial_capital,
            assumptions=empty_assumptions,
            metrics=_compute_period_metrics(
                bars_slice=[],
                nav_series=[initial_capital],
                trades_in_slice=[],
                initial_nav=initial_capital,
                total_fees=ZERO,
                total_taxes=ZERO,
                total_slippage_cost=ZERO,
                days_in_market=0,
                total_turnover_value=ZERO,
                unfilled_orders_count=0,
                benchmark_return_pct=ZERO,
            ),
            trades=[],
        )

    slippage_rate = slippage_bps / TEN_THOUSAND
    cash = _q2(initial_capital)

    # Trạng thái vị thế đang mở (nếu có)
    open_pos_qty: int = 0
    open_pos_signal_date: Optional[date] = None
    open_pos_entry_date: Optional[date] = None
    open_pos_entry_price: Decimal = ZERO
    open_pos_buy_fee: Decimal = ZERO
    open_pos_stop_loss: Optional[Decimal] = None

    # Tín hiệu sinh ra từ cuối phiên trước (chờ khớp vào đầu phiên kế tiếp T+1)
    pending_signal: Optional[EvaluatedSignal] = None

    trades: List[SimulatedTrade] = []
    nav_series: List[Decimal] = []
    active_bars: List[OhlcvBar] = []

    total_fees = ZERO
    total_taxes = ZERO
    total_slippage_cost = ZERO
    total_turnover_value = ZERO
    days_in_market = 0
    unfilled_orders_count = 0

    for pos_in_window, global_idx in enumerate(active_indices):
        bar = sorted_all_bars[global_idx]
        ind = all_indicators[global_idx]
        active_bars.append(bar)
        is_last_bar = pos_in_window == len(active_indices) - 1

        # ------------------------------------------------------------------
        # BƯỚC 1: Thực thi lệnh chờ (Pending Signal từ phiên T-1) tại giá OPEN của phiên hiện tại (T)
        # ------------------------------------------------------------------
        if pending_signal is not None:
            if pending_signal.action == "BUY" and open_pos_qty == 0:
                exec_buy_price = _q4(bar.open * (Decimal("1") + slippage_rate))
                unit_cost_with_fee = exec_buy_price * (Decimal("1") + fee_rate)
                lot_cost = unit_cost_with_fee * Decimal(lot_size)

                if lot_cost > ZERO and cash >= lot_cost:
                    lots = int(cash // lot_cost)
                    qty = lots * lot_size
                    gross_buy_val = _q2(Decimal(qty) * exec_buy_price)
                    buy_fee = _q2(gross_buy_val * fee_rate)
                    slip_cost = _q2(Decimal(qty) * abs(exec_buy_price - bar.open))

                    cash = _q2(cash - gross_buy_val - buy_fee)
                    open_pos_qty = qty
                    open_pos_signal_date = pending_signal.signal_date
                    open_pos_entry_date = bar.trading_date
                    open_pos_entry_price = exec_buy_price
                    open_pos_buy_fee = buy_fee
                    open_pos_stop_loss = pending_signal.stop_loss

                    total_fees += buy_fee
                    total_slippage_cost += slip_cost
                    total_turnover_value += gross_buy_val
                else:
                    unfilled_orders_count += 1

            elif pending_signal.action == "SELL" and open_pos_qty > 0:
                exec_sell_price = _q4(bar.open * (Decimal("1") - slippage_rate))
                gross_sell_val = _q2(Decimal(open_pos_qty) * exec_sell_price)
                sell_fee = _q2(gross_sell_val * fee_rate)
                sell_tax = _q2(gross_sell_val * tax_rate)
                slip_cost = _q2(Decimal(open_pos_qty) * abs(bar.open - exec_sell_price))

                cash = _q2(cash + gross_sell_val - sell_fee - sell_tax)
                buy_cost_total = _q2(Decimal(open_pos_qty) * open_pos_entry_price) + open_pos_buy_fee
                net_sell_proceeds = gross_sell_val - sell_fee - sell_tax
                trade_pnl = _q2(net_sell_proceeds - buy_cost_total)

                total_fees += sell_fee
                total_taxes += sell_tax
                total_slippage_cost += slip_cost
                total_turnover_value += gross_sell_val

                trades.append(
                    SimulatedTrade(
                        symbol=symbol,
                        signal_date=open_pos_signal_date or bar.trading_date,
                        entry_date=open_pos_entry_date or bar.trading_date,
                        exit_date=bar.trading_date,
                        entry_price=open_pos_entry_price,
                        exit_price=exec_sell_price,
                        quantity=open_pos_qty,
                        fees=_q2(open_pos_buy_fee + sell_fee),
                        taxes=sell_tax,
                        pnl=trade_pnl,
                        exit_reason="STRATEGY_SIGNAL_NEXT_OPEN",
                    )
                )
                open_pos_qty = 0
                open_pos_signal_date = None
                open_pos_entry_date = None
                open_pos_entry_price = ZERO
                open_pos_buy_fee = ZERO
                open_pos_stop_loss = None

            pending_signal = None

        # ------------------------------------------------------------------
        # BƯỚC 2: Kiểm tra chạm Stop Loss nội phiên đối với vị thế đang mở
        # ------------------------------------------------------------------
        if open_pos_qty > 0 and open_pos_stop_loss is not None and bar.low <= open_pos_stop_loss:
            trigger_price = min(bar.open, open_pos_stop_loss)
            exec_stop_price = _q4(trigger_price * (Decimal("1") - slippage_rate))
            gross_sell_val = _q2(Decimal(open_pos_qty) * exec_stop_price)
            sell_fee = _q2(gross_sell_val * fee_rate)
            sell_tax = _q2(gross_sell_val * tax_rate)
            slip_cost = _q2(Decimal(open_pos_qty) * abs(trigger_price - exec_stop_price))

            cash = _q2(cash + gross_sell_val - sell_fee - sell_tax)
            buy_cost_total = _q2(Decimal(open_pos_qty) * open_pos_entry_price) + open_pos_buy_fee
            net_sell_proceeds = gross_sell_val - sell_fee - sell_tax
            trade_pnl = _q2(net_sell_proceeds - buy_cost_total)

            total_fees += sell_fee
            total_taxes += sell_tax
            total_slippage_cost += slip_cost
            total_turnover_value += gross_sell_val

            trades.append(
                SimulatedTrade(
                    symbol=symbol,
                    signal_date=open_pos_signal_date or bar.trading_date,
                    entry_date=open_pos_entry_date or bar.trading_date,
                    exit_date=bar.trading_date,
                    entry_price=open_pos_entry_price,
                    exit_price=exec_stop_price,
                    quantity=open_pos_qty,
                    fees=_q2(open_pos_buy_fee + sell_fee),
                    taxes=sell_tax,
                    pnl=trade_pnl,
                    exit_reason="STOP_LOSS_INTRADAY",
                )
            )
            open_pos_qty = 0
            open_pos_signal_date = None
            open_pos_entry_date = None
            open_pos_entry_price = ZERO
            open_pos_buy_fee = ZERO
            open_pos_stop_loss = None

        # ------------------------------------------------------------------
        # BƯỚC 3: Nếu là phiên cuối cùng của kỳ Backtest và vẫn còn vị thế mở -> đóng vị thế cuối kỳ
        # ------------------------------------------------------------------
        if is_last_bar and open_pos_qty > 0:
            exec_close_price = _q4(bar.close * (Decimal("1") - slippage_rate))
            gross_sell_val = _q2(Decimal(open_pos_qty) * exec_close_price)
            sell_fee = _q2(gross_sell_val * fee_rate)
            sell_tax = _q2(gross_sell_val * tax_rate)
            slip_cost = _q2(Decimal(open_pos_qty) * abs(bar.close - exec_close_price))

            cash = _q2(cash + gross_sell_val - sell_fee - sell_tax)
            buy_cost_total = _q2(Decimal(open_pos_qty) * open_pos_entry_price) + open_pos_buy_fee
            net_sell_proceeds = gross_sell_val - sell_fee - sell_tax
            trade_pnl = _q2(net_sell_proceeds - buy_cost_total)

            total_fees += sell_fee
            total_taxes += sell_tax
            total_slippage_cost += slip_cost
            total_turnover_value += gross_sell_val

            trades.append(
                SimulatedTrade(
                    symbol=symbol,
                    signal_date=open_pos_signal_date or bar.trading_date,
                    entry_date=open_pos_entry_date or bar.trading_date,
                    exit_date=bar.trading_date,
                    entry_price=open_pos_entry_price,
                    exit_price=exec_close_price,
                    quantity=open_pos_qty,
                    fees=_q2(open_pos_buy_fee + sell_fee),
                    taxes=sell_tax,
                    pnl=trade_pnl,
                    exit_reason="END_OF_BACKTEST_MARK_TO_MARKET",
                )
            )
            open_pos_qty = 0

        # ------------------------------------------------------------------
        # BƯỚC 4: Ghi nhận NAV cuối ngày T và đánh giá tín hiệu EOD (chỉ khớp từ phiên T+1)
        # ------------------------------------------------------------------
        if open_pos_qty > 0:
            days_in_market += 1
        eod_nav = _q2(cash + Decimal(open_pos_qty) * bar.close)
        nav_series.append(eod_nav)

        if not is_last_bar:
            evaluated = strategy.evaluate_bar(symbol=symbol, bar=bar, indicator=ind)
            if evaluated.action in {"BUY", "SELL"}:
                pending_signal = evaluated

    # Tính tỷ suất sinh lời Benchmark (Buy & Hold từ Open ngày đầu tới Close ngày cuối)
    first_open = active_bars[0].open
    last_close = active_bars[-1].close
    benchmark_ret_pct = (
        _q2(((last_close - first_open) / first_open) * HUNDRED)
        if first_open > ZERO
        else ZERO
    )

    overall_metrics = _compute_period_metrics(
        bars_slice=active_bars,
        nav_series=nav_series,
        trades_in_slice=trades,
        initial_nav=initial_capital,
        total_fees=total_fees,
        total_taxes=total_taxes,
        total_slippage_cost=total_slippage_cost,
        days_in_market=days_in_market,
        total_turnover_value=total_turnover_value,
        unfilled_orders_count=unfilled_orders_count,
        benchmark_return_pct=benchmark_ret_pct,
    )

    # Chia khoảng thời gian Walk-Forward (60% Train / 20% Validation / 20% Out-of-Sample Test)
    n_active = len(active_bars)
    idx_train_end = max(1, int(n_active * 0.6))
    idx_val_end = max(idx_train_end + 1, int(n_active * 0.8)) if n_active >= 3 else n_active

    def _split_summary(start_i: int, end_i: int) -> Dict[str, Any]:
        sub_bars = active_bars[start_i:end_i]
        sub_navs = nav_series[start_i:end_i]
        if not sub_bars or not sub_navs:
            return {"bars_count": 0, "return_pct": "0.00", "trades_count": 0}
        start_d = sub_bars[0].trading_date
        end_d = sub_bars[-1].trading_date
        base_nav = nav_series[start_i - 1] if start_i > 0 else initial_capital
        end_nav = sub_navs[-1]
        ret = _q2(((end_nav - base_nav) / base_nav) * HUNDRED) if base_nav > ZERO else ZERO
        sub_trades = [t for t in trades if start_d <= t.entry_date <= end_d]
        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "bars_count": len(sub_bars),
            "return_pct": str(ret),
            "trades_count": len(sub_trades),
        }

    overall_metrics["walk_forward_splits"] = {
        "train_60pct": _split_summary(0, idx_train_end),
        "validation_20pct": _split_summary(idx_train_end, idx_val_end),
        "out_of_sample_test_20pct": _split_summary(idx_val_end, n_active),
    }

    assumptions = {
        "execution_model": "NEXT_BAR_OPEN_WITH_SLIPPAGE (T+1 Open)",
        "no_look_ahead_enforced": True,
        "signal_t_cannot_fill_at_close_t": True,
        "fee_rate": str(fee_rate),
        "tax_rate": str(tax_rate),
        "slippage_bps": str(slippage_bps),
        "lot_size": lot_size,
        "calculation_version": calculation_version,
        "universe_limitation": "Backtest thực hiện trên dữ liệu lịch sử CSV của mã được chọn; có thể tồn tại survivorship bias nếu danh mục mã chỉ gồm các cổ phiếu còn niêm yết.",
        "overfitting_disclaimer": "Kết quả quá khứ không cam kết lợi nhuận tương lai. Bắt buộc đối chiếu tập out_of_sample_test_20pct trước khi đưa vào Paper Trading.",
    }

    return BacktestSimulationResult(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_nav=nav_series[-1] if nav_series else initial_capital,
        assumptions=assumptions,
        metrics=overall_metrics,
        trades=trades,
    )
