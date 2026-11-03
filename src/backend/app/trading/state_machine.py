# Ngày tạo: 2026-11-03
# Mục đích: Định nghĩa State Machine hợp lệ trong Domain cho TradeProposal và Order (Mục 10.1).
# Lý do: Ngăn chặn controller hoặc bất kỳ tác nhân nào cập nhật trạng thái nhảy cóc trái quy trình an toàn.

from typing import Dict, Set

PROPOSAL_VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "PendingApproval": {"Rejected", "Expired", "Approved"},
    "Approved": {"RiskValidation", "Blocked", "Submitted"},
    "RiskValidation": {"Blocked", "Submitted"},
    "Rejected": set(),
    "Expired": set(),
    "Blocked": set(),
    "Submitted": set(),
}

ORDER_VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "Submitted": {"PartiallyFilled", "Filled", "Cancelled", "Failed"},
    "PartiallyFilled": {"PartiallyFilled", "Filled", "Cancelled"},
    "Filled": set(),
    "Cancelled": set(),
    "Failed": set(),
}


class InvalidStateTransitionError(ValueError):
    """Ngoại lệ khi chuyển đổi trạng thái Proposal hoặc Order không hợp lệ."""


def assert_proposal_transition(current_status: str, target_status: str) -> None:
    """Kiểm tra chuyển đổi trạng thái hợp lệ của TradeProposal."""
    allowed = PROPOSAL_VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise InvalidStateTransitionError(
            f"Không thể chuyển trạng thái Proposal từ '{current_status}' sang '{target_status}'. "
            f"Các trạng thái đích hợp lệ: {sorted(allowed)}"
        )


def assert_order_transition(current_status: str, target_status: str) -> None:
    """Kiểm tra chuyển đổi trạng thái hợp lệ của Order."""
    allowed = ORDER_VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise InvalidStateTransitionError(
            f"Không thể chuyển trạng thái Order từ '{current_status}' sang '{target_status}'. "
            f"Các trạng thái đích hợp lệ: {sorted(allowed)}"
        )
