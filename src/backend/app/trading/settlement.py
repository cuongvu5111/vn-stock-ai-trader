# Ngày tạo: 2026-11-17
# Mục đích: Hàm thuần (pure) cho thanh toán T+N: tính ngày thanh toán và số lượng cổ phiếu khả dụng để bán từ sổ khớp lệnh.
# Lý do: Cổ phiếu mua ở ngày T chỉ về tài khoản (bán được) sau N ngày làm việc; `available_quantity` là số suy dẫn
#        từ `trading.executions` theo ngày thị trường, không phải số liệu tự do có thể sửa.
#        Chưa mô hình hóa ngày nghỉ lễ của sàn: chỉ bỏ thứ 7 và Chủ nhật.

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"


def is_trading_day(day: date) -> bool:
    """Thứ 2..thứ 6 là ngày làm việc (weekday() 0..4)."""
    return day.weekday() < 5


def add_trading_days(start: date, lag: int) -> date:
    """
    Cộng `lag` ngày làm việc vào `start`, bỏ qua thứ 7/Chủ nhật.
    Đếm từ ngày kế tiếp nên `start` rơi vào cuối tuần vẫn cho kết quả đúng (T7/CN + 2 = thứ 3).
    """
    if lag < 0:
        raise ValueError("lag phải >= 0.")
    current = start
    remaining = lag
    while remaining > 0:
        current += timedelta(days=1)
        if is_trading_day(current):
            remaining -= 1
    return current


@dataclass(frozen=True)
class LedgerFill:
    """Một lần khớp trong sổ khớp lệnh, chỉ giữ các trường cần cho tính thanh toán."""

    side: str
    quantity: int
    settlement_date: date


def settled_available_quantity(fills: Iterable[LedgerFill], as_of: date) -> int:
    """
    Số cổ phiếu được phép bán tại ngày `as_of` = tổng BUY đã đến hạn thanh toán (settlement_date <= as_of)
    trừ tổng SELL đã khớp, không âm. Lệnh bán luôn trừ ngay vì cổ phiếu đã rời tài khoản.
    Khớp từng phần (partial fill) được xử lý đúng vì mỗi lần khớp là một dòng có ngày thanh toán riêng.
    """
    settled_bought = 0
    sold = 0
    for fill in fills:
        if fill.side == SIDE_BUY:
            if fill.settlement_date <= as_of:
                settled_bought += fill.quantity
        elif fill.side == SIDE_SELL:
            sold += fill.quantity
    return max(0, settled_bought - sold)
