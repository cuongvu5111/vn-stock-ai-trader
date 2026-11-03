# Ngày tạo: 2026-11-03
# Mục đích: Cổng kiểm soát rủi ro bắt buộc (Risk Engine) và tính khối lượng vị thế (Position Sizing).
# Lý do:
#   - Tuân thủ Mục 9 trong Implementation Plan: tính khối lượng theo rủi ro/cổ phiếu, trần vị thế, trần tổng phân bổ, tiền mặt khả dụng và làm tròn xuống theo lô 100 cổ phiếu.
#   - Được gọi cả khi tạo TradeProposal lẫn khi người dùng nhấn Approve (Re-validation).

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from app.schemas.trading import RiskConfigPayload

Q_MONEY_2 = Decimal("0.01")
Q_PRICE_4 = Decimal("0.0001")
HUNDRED = Decimal("100")
TEN_THOUSAND = Decimal("10000")
ZERO = Decimal("0")


def _q2(val: Decimal) -> Decimal:
    return val.quantize(Q_MONEY_2, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RiskEvaluationResult:
    """Kết quả đánh giá rủi ro và tính toán khối lượng đặt lệnh."""

    passed: bool
    proposed_quantity: int
    estimated_cost: Decimal
    risk_amount: Decimal
    reasons: List[str]
    details: Dict[str, Any]


def evaluate_trade_risk_and_sizing(
    side: str,
    entry_price: Decimal,
    stop_loss: Optional[Decimal],
    nav: Decimal,
    available_cash: Decimal,
    current_symbol_market_value: Decimal,
    total_portfolio_market_value: Decimal,
    open_positions_count: int,
    is_new_symbol_position: bool,
    available_position_qty_for_sell: int,
    daily_loss_amount: Decimal,
    has_conflicting_order_or_proposal: bool,
    config: RiskConfigPayload,
    requested_quantity: Optional[int] = None,
) -> RiskEvaluationResult:
    """
    Thực hiện toàn bộ các bước kiểm tra hạn mức rủi ro (Mục 9.2 & 9.3).
    Nếu `requested_quantity` được truyền vào (khi Re-validate tại bước Approve),
    kiểm tra xem `requested_quantity` có còn nằm trong giới hạn cho phép hay không.
    """
    reasons: List[str] = []
    norm_side = side.strip().upper()

    # 1. Kiểm tra Kill Switch
    if not config.trading_enabled:
        reasons.append("KILL_SWITCH_ACTIVE: Giao dịch đang bị khóa bởi Kill Switch (trading_enabled=false).")

    # 2. Kiểm tra lệnh/đề xuất xung đột
    if has_conflicting_order_or_proposal:
        reasons.append("CONFLICTING_ORDER_OR_PROPOSAL: Đã tồn tại đề xuất hoặc lệnh đang chờ xử lý cho mã này.")

    # 3. Kiểm tra giới hạn lỗ trong ngày (Daily Loss Limit)
    max_daily_loss_val = _q2(nav * (config.max_daily_loss_percent / HUNDRED))
    if daily_loss_amount > max_daily_loss_val:
        reasons.append(
            f"DAILY_LOSS_LIMIT_EXCEEDED: Mức lỗ trong ngày ({daily_loss_amount}) vượt giới hạn cho phép ({max_daily_loss_val})."
        )

    if entry_price <= ZERO:
        reasons.append("INVALID_ENTRY_PRICE: Giá đặt lệnh phải lớn hơn 0.")

    slippage_rate = config.slippage_bps / TEN_THOUSAND

    # ------------------------------------------------------------------
    # TRƯỜNG HỢP LỆNH BÁN (SELL)
    # ------------------------------------------------------------------
    if norm_side == "SELL":
        if available_position_qty_for_sell <= 0:
            reasons.append("INSUFFICIENT_POSITION_FOR_SELL: Không có cổ phiếu khả dụng để bán.")
            return RiskEvaluationResult(
                passed=False,
                proposed_quantity=0,
                estimated_cost=ZERO,
                risk_amount=ZERO,
                reasons=reasons,
                details={"side": "SELL", "available_quantity": available_position_qty_for_sell},
            )

        sell_qty = requested_quantity if requested_quantity is not None else available_position_qty_for_sell
        if sell_qty > available_position_qty_for_sell:
            reasons.append(
                f"SELL_QTY_EXCEEDS_AVAILABLE: Khối lượng bán ({sell_qty}) vượt số dư khả dụng ({available_position_qty_for_sell})."
            )

        gross_val = _q2(Decimal(sell_qty) * entry_price)
        passed = len(reasons) == 0 and sell_qty > 0
        return RiskEvaluationResult(
            passed=passed,
            proposed_quantity=sell_qty if passed else 0,
            estimated_cost=gross_val,
            risk_amount=ZERO,
            reasons=reasons,
            details={
                "side": "SELL",
                "available_quantity": available_position_qty_for_sell,
                "final_quantity": sell_qty,
            },
        )

    # ------------------------------------------------------------------
    # TRƯỜNG HỢP LỆNH MUA (BUY)
    # ------------------------------------------------------------------
    if is_new_symbol_position and open_positions_count >= config.max_open_positions:
        reasons.append(
            f"MAX_OPEN_POSITIONS_REACHED: Số vị thế đang mở ({open_positions_count}) đã chạm trần ({config.max_open_positions})."
        )

    if stop_loss is None or stop_loss <= ZERO or stop_loss >= entry_price:
        reasons.append(
            f"INVALID_STOP_LOSS: Với lệnh BUY, stop_loss ({stop_loss}) phải dương và nhỏ hơn giá mua ({entry_price})."
        )
        return RiskEvaluationResult(
            passed=False,
            proposed_quantity=0,
            estimated_cost=ZERO,
            risk_amount=ZERO,
            reasons=reasons,
            details={"entry_price": str(entry_price), "stop_loss": str(stop_loss)},
        )

    # Công thức Position Sizing (Mục 9.2)
    max_risk_budget = _q2(nav * (config.max_risk_per_trade_percent / HUNDRED))
    risk_per_share = entry_price - stop_loss
    qty_by_risk = int((max_risk_budget / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))

    max_position_value = _q2(nav * (config.max_position_percent / HUNDRED))
    remaining_position_cap = max(ZERO, max_position_value - current_symbol_market_value)
    qty_by_position_cap = int((remaining_position_cap / entry_price).to_integral_value(rounding=ROUND_FLOOR))

    max_portfolio_alloc_value = _q2(nav * (config.max_portfolio_allocation_percent / HUNDRED))
    remaining_alloc_cap = max(ZERO, max_portfolio_alloc_value - total_portfolio_market_value)
    qty_by_alloc_cap = int((remaining_alloc_cap / entry_price).to_integral_value(rounding=ROUND_FLOOR))

    effective_buy_price = entry_price * (Decimal("1") + slippage_rate)
    unit_total_cost = effective_buy_price * (Decimal("1") + config.fee_rate)
    qty_by_cash = int((available_cash / unit_total_cost).to_integral_value(rounding=ROUND_FLOOR))

    raw_min_qty = max(0, min(qty_by_risk, qty_by_position_cap, qty_by_alloc_cap, qty_by_cash))
    lot_size = max(1, config.lot_size)
    max_allowed_lot_qty = (raw_min_qty // lot_size) * lot_size

    if requested_quantity is not None:
        final_qty = requested_quantity
        if final_qty % lot_size != 0:
            reasons.append(f"INVALID_LOT_SIZE: Khối lượng ({final_qty}) không phải bội số của lô ({lot_size}).")
        if final_qty > max_allowed_lot_qty:
            reasons.append(
                f"QUANTITY_EXCEEDS_RISK_LIMITS: Khối lượng yêu cầu ({final_qty}) vượt mức tối đa cho phép theo hạn mức rủi ro hiện tại ({max_allowed_lot_qty})."
            )
    else:
        final_qty = max_allowed_lot_qty

    if final_qty < lot_size:
        if qty_by_cash < lot_size:
            reasons.append("INSUFFICIENT_CASH_FOR_MIN_LOT: Không đủ tiền mặt khả dụng để mua tối thiểu 1 lô.")
        if qty_by_position_cap < lot_size:
            reasons.append("MAX_POSITION_PERCENT_EXCEEDED: Vượt giới hạn tỷ trọng tối đa trên một mã cổ phiếu.")
        if qty_by_alloc_cap < lot_size:
            reasons.append("MAX_PORTFOLIO_ALLOCATION_EXCEEDED: Vượt giới hạn tổng tỷ trọng phân bổ cổ phiếu toàn danh mục.")
        if qty_by_risk < lot_size:
            reasons.append("MAX_RISK_PER_TRADE_EXCEEDED: Rủi ro trên 1 lô tối thiểu vượt hạn mức rủi ro cho phép mỗi lệnh.")

    estimated_cost = _q2(Decimal(final_qty) * unit_total_cost)
    actual_risk_amount = _q2(Decimal(final_qty) * risk_per_share)
    passed = len(reasons) == 0 and final_qty >= lot_size

    details = {
        "nav": str(nav),
        "available_cash": str(available_cash),
        "max_risk_budget": str(max_risk_budget),
        "risk_per_share": str(risk_per_share),
        "qty_by_risk": qty_by_risk,
        "qty_by_position_cap": qty_by_position_cap,
        "qty_by_alloc_cap": qty_by_alloc_cap,
        "qty_by_cash": qty_by_cash,
        "max_allowed_lot_qty": max_allowed_lot_qty,
        "final_quantity": final_qty if passed else 0,
        "lot_size": lot_size,
        "estimated_cost_including_fee_slippage": str(estimated_cost),
    }

    return RiskEvaluationResult(
        passed=passed,
        proposed_quantity=final_qty if passed else 0,
        estimated_cost=estimated_cost if passed else ZERO,
        risk_amount=actual_risk_amount if passed else ZERO,
        reasons=reasons,
        details=details,
    )
