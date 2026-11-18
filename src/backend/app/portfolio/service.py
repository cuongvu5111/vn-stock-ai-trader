# Ngày tạo: 2026-11-03
# Mục đích: Quản lý Tài khoản Paper, Vị thế, Sổ cái tiền mặt (`portfolio.cash_transactions`) và Đối soát (`Reconciliation`).
# Lý do:
#   - Đảm bảo quy tắc kế toán (Accounting rule): executions và cash_transactions là nguồn sự thật gốc duy nhất.
#   - Hỗ trợ tái dựng (rebuild) lại toàn bộ positions và cash_balance từ ledger & executions.

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.market_data.models import DailyPrice, Stock
from app.portfolio.models import Account, CashTransaction, DailySnapshot, Position
from app.risk.service import record_audit_log
from app.schemas.trading import (
    CashLedgerListResponse,
    CashTransactionItemResponse,
    DailySnapshotItemResponse,
    PortfolioOverviewResponse,
    PortfolioSnapshotsResponse,
    PositionItemResponse,
    ReconciliationReportResponse,
)
from app.trading.models import Execution, Order
from app.trading.settlement import LedgerFill, settled_available_quantity

Q_MONEY_2 = Decimal("0.01")
Q_PRICE_4 = Decimal("0.0001")
HUNDRED = Decimal("100")
DEFAULT_PAPER_ACCOUNT_NAME = "DEFAULT_PAPER_ACCOUNT"
ZERO = Decimal("0.00")


def _q2(val: Decimal) -> Decimal:
    return val.quantize(Q_MONEY_2, rounding=ROUND_HALF_UP)


def _q4(val: Decimal) -> Decimal:
    return val.quantize(Q_PRICE_4, rounding=ROUND_HALF_UP)


class PortfolioService:
    """Service quản lý tài khoản Paper, sổ cái tiền mặt, vị thế và đối soát sổ cái."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def get_or_create_default_paper_account(self, for_update: bool = False) -> Account:
        """
        Lấy hoặc khởi tạo tài khoản Paper mặc định kèm bút toán vốn ban đầu.

        `for_update=True` khóa dòng Account (`SELECT ... FOR UPDATE`) cho tới hết transaction hiện tại và đọc lại
        `cash_balance` mới nhất (`populate_existing`, kể cả khi Account đã nằm sẵn trong identity map): mọi đường
        đọc-kiểm tra-ghi số dư tiền phải gọi bằng cờ này để hai lần khớp song song không ghi đè (lost update) hay cùng
        tiêu một khoản tiền. Thứ tự khóa toàn hệ thống là Order -> Stock -> Account; không giữ khóa Account rồi mới
        xin khóa Order/Stock. Đường chỉ đọc (mặc định) không khóa.
        """
        stmt = select(Account).where(Account.account_name == DEFAULT_PAPER_ACCOUNT_NAME)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        account = self.session.scalar(stmt)
        if account is None:
            try:
                self._create_default_paper_account()
            except IntegrityError:
                # Thua worker khác (UNIQUE account_name): savepoint đã rollback, transaction ngoài vẫn dùng tiếp.
                # Nếu vẫn không thấy tài khoản thì lỗi không phải do tranh tạo nên phải ném lại.
                account = self.session.scalar(stmt)
                if account is None:
                    raise
                return account
            account = self.session.scalar(stmt)
        return account

    def _create_default_paper_account(self) -> None:
        """Tạo tài khoản mặc định cùng bút toán vốn ban đầu trong một savepoint (lỗi UNIQUE chỉ rollback savepoint)."""
        init_cap = _q2(Decimal(str(self.settings.INITIAL_PAPER_CAPITAL)))
        with self.session.begin_nested():
            account = Account(
                account_name=DEFAULT_PAPER_ACCOUNT_NAME,
                initial_capital=init_cap,
                cash_balance=init_cap,
                currency="VND",
                account_type="PAPER",
            )
            self.session.add(account)
            self.session.flush()

            self.session.add(
                CashTransaction(
                    account_id=account.id,
                    transaction_type="INITIAL_DEPOSIT",
                    amount=init_cap,
                    reference_type="ACCOUNT_INIT",
                    reference_id=account.id,
                    description="[SIMULATED] Vốn giả lập khởi tạo cho tài khoản Paper Trading MVP",
                )
            )
            self.session.flush()
    def get_latest_market_price(self, stock_id: uuid.UUID, fallback_price: Decimal) -> Decimal:
        """Lấy giá đóng cửa gần nhất của mã cổ phiếu từ `market.daily_prices`."""
        latest_close = self.session.scalar(
            select(DailyPrice.close)
            .where(DailyPrice.stock_id == stock_id)
            .order_by(DailyPrice.trading_date.desc())
            .limit(1)
        )
        return _q4(latest_close) if latest_close is not None else _q4(fallback_price)

    def _load_ledger_fills(self, symbol: Optional[str] = None) -> Dict[str, List[LedgerFill]]:
        """Đọc sổ khớp lệnh (`trading.executions`) gom theo mã; đây là nguồn sự thật cho số lượng khả dụng T+N."""
        stmt = select(
            Order.symbol, Order.side, Execution.quantity, Execution.settlement_date
        ).join(Order, Execution.order_id == Order.id)
        if symbol is not None:
            stmt = stmt.where(Order.symbol == symbol)
        fills: Dict[str, List[LedgerFill]] = {}
        for sym, side, quantity, settlement_date in self.session.execute(stmt).all():
            fills.setdefault(sym, []).append(
                LedgerFill(side=side, quantity=quantity, settlement_date=settlement_date)
            )
        return fills

    def get_settled_available_quantity(self, symbol: str, as_of: Optional[date] = None) -> int:
        """Số cổ phiếu `symbol` được phép bán tại ngày thị trường `as_of` (mặc định hôm nay): BUY đã thanh toán - SELL."""
        as_of_date = as_of or clock.market_today()
        fills = self._load_ledger_fills(symbol).get(symbol, [])
        return settled_available_quantity(fills, as_of_date)

    def refresh_available_quantities(self, as_of: Optional[date] = None) -> None:
        """
        Cập nhật cột cache `Position.available_quantity` từ sổ khớp lệnh theo ngày thị trường `as_of`.
        Chỉ ghi đè số suy dẫn trên bảng positions, tuyệt đối không sửa executions/cash_transactions.
        """
        as_of_date = as_of or clock.market_today()
        account = self.get_or_create_default_paper_account()
        fills_by_symbol = self._load_ledger_fills()
        rows = self.session.execute(
            select(Position, Stock)
            .join(Stock, Position.stock_id == Stock.id)
            .where(Position.account_id == account.id)
        ).all()
        for pos, stock in rows:
            ledger_available = settled_available_quantity(fills_by_symbol.get(stock.symbol, []), as_of_date)
            pos.available_quantity = min(pos.quantity, ledger_available)
        self.session.flush()

    def lock_symbol_for_update(self, symbol: str) -> None:
        """
        Khóa dòng `market.stocks` của mã (`SELECT ... FOR UPDATE`) cho tới hết transaction hiện tại để mọi lần khớp
        cùng một mã (kể cả từ nhiều worker/process) chạy tuần tự: khối lượng khả dụng T+N và vị thế chỉ được tính
        lại SAU khi giành được khóa, nên hai lệnh SELL song song không thể cùng bán số cổ phiếu đã thanh toán.
        Mã chưa có dòng Stock thì không có gì để khóa; khi đó chưa từng có lần khớp nào của mã (Stock được tạo
        cùng transaction với Execution đầu tiên) nên SELL luôn bị chặn vì khả dụng = 0, còn BUY lần đầu được
        UNIQUE(symbol) bảo vệ (bên thua nhận lỗi thay vì ghi sai sổ). SQLite (test) bỏ qua FOR UPDATE.
        """
        self.session.execute(
            select(Stock.id).where(Stock.symbol == symbol).with_for_update()
        ).first()

    def apply_execution_to_ledger_and_positions(
        self,
        order: Order,
        execution: Execution,
    ) -> None:
        """
        Cập nhật đồng bộ Sổ cái tiền mặt (`cash_transactions`), số dư `Account.cash_balance`
        và vị thế `Position` ngay trong cùng transaction khi phát sinh một `Execution`.
        BUY tăng `quantity` nhưng `available_quantity` chỉ tăng khi tới `execution.settlement_date` (T+N).
        Số dư tiền được đọc lại dưới khóa Account (`FOR UPDATE`, giữ tới commit) trước khi cộng/trừ, nên hai lần khớp
        song song (kể cả khác mã) không ghi đè nhau. Gọi sau khi đã khóa Order -> Stock để giữ đúng thứ tự khóa.
        """
        account = self.get_or_create_default_paper_account(for_update=True)
        stock = self.session.scalar(select(Stock).where(Stock.symbol == order.symbol))
        if stock is None:
            stock = Stock(
                symbol=order.symbol,
                exchange="HOSE",
                company_name=f"[SAMPLE] Cổ phiếu {order.symbol}",
                is_active=True,
            )
            self.session.add(stock)
            self.session.flush()

        position = self.session.scalar(
            select(Position).where(
                Position.account_id == account.id,
                Position.stock_id == stock.id,
            )
        )

        gross_amount = _q2(Decimal(execution.quantity) * execution.price)

        if order.side == "BUY":
            total_outflow = _q2(gross_amount + execution.fee)
            account.cash_balance = _q2(account.cash_balance - total_outflow)

            self.session.add(
                CashTransaction(
                    account_id=account.id,
                    transaction_type="BUY_EXECUTION",
                    amount=-total_outflow,
                    reference_type="EXECUTION",
                    reference_id=execution.id,
                    description=(
                        f"Khớp mua {execution.quantity} {order.symbol} @ {execution.price} "
                        f"(phí: {execution.fee})"
                    ),
                )
            )

            if position is None or position.quantity == 0:
                new_qty = execution.quantity
                new_avg_cost = _q4(total_outflow / Decimal(new_qty))
                if position is None:
                    position = Position(
                        account_id=account.id,
                        stock_id=stock.id,
                        quantity=new_qty,
                        available_quantity=0,
                        average_cost=new_avg_cost,
                    )
                    self.session.add(position)
                else:
                    position.quantity = new_qty
                    position.available_quantity = 0
                    position.average_cost = new_avg_cost
            else:
                old_total_cost = Decimal(position.quantity) * position.average_cost
                new_qty = position.quantity + execution.quantity
                position.average_cost = _q4((old_total_cost + total_outflow) / Decimal(new_qty))
                position.quantity = new_qty

        elif order.side == "SELL":
            net_inflow = _q2(gross_amount - execution.fee - execution.tax)
            account.cash_balance = _q2(account.cash_balance + net_inflow)

            self.session.add(
                CashTransaction(
                    account_id=account.id,
                    transaction_type="SELL_EXECUTION",
                    amount=net_inflow,
                    reference_type="EXECUTION",
                    reference_id=execution.id,
                    description=(
                        f"Khớp bán {execution.quantity} {order.symbol} @ {execution.price} "
                        f"(phí: {execution.fee}, thuế: {execution.tax})"
                    ),
                )
            )

            if position is not None:
                remaining_qty = max(0, position.quantity - execution.quantity)
                position.quantity = remaining_qty
                if remaining_qty == 0:
                    position.average_cost = Decimal("0.0000")

        self.session.flush()

        if position is not None:
            position.available_quantity = min(
                position.quantity,
                self.get_settled_available_quantity(order.symbol, as_of=execution.trade_date),
            )
            self.session.flush()

    def get_portfolio_overview(self, as_of: Optional[date] = None) -> PortfolioOverviewResponse:
        """
        Tính toán tổng quan danh mục (Cash, Market Value, NAV, P&L, tỷ trọng từng vị thế).
        `available_quantity` luôn được làm mới từ sổ khớp lệnh theo ngày thị trường `as_of` (mặc định hôm nay).
        """
        as_of_date = as_of or clock.market_today()
        account = self.get_or_create_default_paper_account()
        self.refresh_available_quantities(as_of=as_of_date)
        pos_rows = self.session.execute(
            select(Position, Stock)
            .join(Stock, Position.stock_id == Stock.id)
            .where(Position.account_id == account.id, Position.quantity > 0)
            .order_by(Stock.symbol.asc())
        ).all()

        total_market_value = ZERO
        total_unrealized_pnl = ZERO
        temp_items: List[tuple[Position, Stock, Decimal, Decimal, Decimal]] = []

        for pos, stock in pos_rows:
            mkt_price = self.get_latest_market_price(stock.id, fallback_price=pos.average_cost)
            mkt_val = _q2(Decimal(pos.quantity) * mkt_price)
            cost_basis = _q2(Decimal(pos.quantity) * pos.average_cost)
            unrealized = _q2(mkt_val - cost_basis)

            total_market_value = _q2(total_market_value + mkt_val)
            total_unrealized_pnl = _q2(total_unrealized_pnl + unrealized)
            temp_items.append((pos, stock, mkt_price, mkt_val, unrealized))

        nav = _q2(account.cash_balance + total_market_value)
        total_pnl = _q2(nav - account.initial_capital)
        realized_pnl = _q2(total_pnl - total_unrealized_pnl)
        allocation_pct = _q2((total_market_value / nav) * HUNDRED) if nav > ZERO else ZERO

        position_items: List[PositionItemResponse] = []
        for pos, stock, mkt_price, mkt_val, unrealized in temp_items:
            weight_pct = _q2((mkt_val / nav) * HUNDRED) if nav > ZERO else ZERO
            position_items.append(
                PositionItemResponse(
                    symbol=stock.symbol,
                    exchange=stock.exchange,
                    quantity=pos.quantity,
                    available_quantity=pos.available_quantity,
                    pending_settlement_quantity=pos.quantity - pos.available_quantity,
                    average_cost=pos.average_cost,
                    market_price=mkt_price,
                    market_value=mkt_val,
                    unrealized_pnl=unrealized,
                    weight_pct=weight_pct,
                )
            )

        return PortfolioOverviewResponse(
            as_of_date=as_of_date,
            account_id=account.id,
            account_name=account.account_name,
            account_type=account.account_type,
            currency=account.currency,
            initial_capital=account.initial_capital,
            cash_balance=account.cash_balance,
            market_value=total_market_value,
            nav=nav,
            unrealized_pnl=total_unrealized_pnl,
            realized_pnl=realized_pnl,
            allocation_pct=allocation_pct,
            open_positions_count=len(position_items),
            positions=position_items,
        )

    def create_or_update_daily_snapshot(self, snapshot_date: date | None = None) -> DailySnapshotItemResponse:
        """Chốt bản chụp NAV cuối ngày vào `portfolio.daily_snapshots`."""
        # Ngày chốt NAV theo lịch thị trường: 23:30 UTC đã là ngày hôm sau ở Việt Nam
        target_date = snapshot_date or clock.market_today()
        overview = self.get_portfolio_overview()

        snap = self.session.scalar(
            select(DailySnapshot).where(
                DailySnapshot.account_id == overview.account_id,
                DailySnapshot.snapshot_date == target_date,
            )
        )
        if snap is None:
            snap = DailySnapshot(
                account_id=overview.account_id,
                snapshot_date=target_date,
                cash_balance=overview.cash_balance,
                market_value=overview.market_value,
                nav=overview.nav,
                unrealized_pnl=overview.unrealized_pnl,
                realized_pnl=overview.realized_pnl,
            )
            self.session.add(snap)
        else:
            snap.cash_balance = overview.cash_balance
            snap.market_value = overview.market_value
            snap.nav = overview.nav
            snap.unrealized_pnl = overview.unrealized_pnl
            snap.realized_pnl = overview.realized_pnl

        self.session.commit()
        self.session.refresh(snap)
        return DailySnapshotItemResponse.model_validate(snap)

    def list_snapshots(self, limit: int = 90) -> PortfolioSnapshotsResponse:
        account = self.get_or_create_default_paper_account()
        rows = self.session.scalars(
            select(DailySnapshot)
            .where(DailySnapshot.account_id == account.id)
            .order_by(DailySnapshot.snapshot_date.desc())
            .limit(limit)
        ).all()
        return PortfolioSnapshotsResponse(
            total=len(rows),
            items=[DailySnapshotItemResponse.model_validate(r) for r in rows],
        )

    def list_cash_transactions(self, limit: int = 100) -> CashLedgerListResponse:
        """Lấy lịch sử bút toán trong sổ cái tiền mặt (`portfolio.cash_transactions`)."""
        account = self.get_or_create_default_paper_account()
        rows = self.session.scalars(
            select(CashTransaction)
            .where(CashTransaction.account_id == account.id)
            .order_by(CashTransaction.created_at.desc())
            .limit(limit)
        ).all()
        return CashLedgerListResponse(
            total=len(rows),
            items=[CashTransactionItemResponse.model_validate(r) for r in rows],
        )

    def reconcile_and_rebuild_portfolio(
        self, actor: str = "system_reconciler", as_of: Optional[date] = None
    ) -> ReconciliationReportResponse:
        """
        Đối soát và tái dựng (rebuild) lại toàn bộ `cash_balance` và `positions` từ
        dữ liệu gốc bất biến (`portfolio.cash_transactions` và `trading.executions`).
        `available_quantity` được dựng lại theo T+N tại ngày thị trường `as_of` (BUY đã thanh toán - SELL),
        không mặc định bằng tổng số lượng.
        """
        as_of_date = as_of or clock.market_today()
        # Ghi lại cash_balance và xóa/dựng lại positions nên phải khóa Account để không đè lên lần khớp đang chạy
        account = self.get_or_create_default_paper_account(for_update=True)
        prev_cash = _q2(account.cash_balance)
        discrepancies: List[str] = []

        # 1. Tính lại tiền mặt từ toàn bộ bút toán trong portfolio.cash_transactions
        cash_txs = self.session.scalars(
            select(CashTransaction)
            .where(CashTransaction.account_id == account.id)
            .order_by(CashTransaction.created_at.asc())
        ).all()
        rebuilt_cash = _q2(sum((tx.amount for tx in cash_txs), ZERO))

        if prev_cash != rebuilt_cash:
            discrepancies.append(
                f"CASH_MISMATCH: cash_balance hiện tại ({prev_cash}) khác tổng sổ cái cash_transactions ({rebuilt_cash})."
            )
            account.cash_balance = rebuilt_cash

        # 2. Tính lại toàn bộ vị thế cổ phiếu từ lịch sử trading.executions
        exec_rows = self.session.execute(
            select(Execution, Order)
            .join(Order, Execution.order_id == Order.id)
            .order_by(Execution.executed_at.asc())
        ).all()

        # symbol -> (qty, avg_cost)
        rebuilt_positions: Dict[str, tuple[int, Decimal]] = {}
        fills_by_symbol: Dict[str, List[LedgerFill]] = {}
        for ex, ord_row in exec_rows:
            sym = ord_row.symbol
            fills_by_symbol.setdefault(sym, []).append(
                LedgerFill(side=ord_row.side, quantity=ex.quantity, settlement_date=ex.settlement_date)
            )
            cur_qty, cur_avg = rebuilt_positions.get(sym, (0, Decimal("0.0000")))
            gross = _q2(Decimal(ex.quantity) * ex.price)
            if ord_row.side == "BUY":
                cost_with_fee = _q2(gross + ex.fee)
                new_qty = cur_qty + ex.quantity
                new_avg = _q4((Decimal(cur_qty) * cur_avg + cost_with_fee) / Decimal(new_qty))
                rebuilt_positions[sym] = (new_qty, new_avg)
            elif ord_row.side == "SELL":
                new_qty = max(0, cur_qty - ex.quantity)
                new_avg = cur_avg if new_qty > 0 else Decimal("0.0000")
                rebuilt_positions[sym] = (new_qty, new_avg)

        existing_positions = {
            stock.symbol: pos
            for pos, stock in self.session.execute(
                select(Position, Stock)
                .join(Stock, Position.stock_id == Stock.id)
                .where(Position.account_id == account.id)
            ).all()
        }

        for sym, (expected_qty, expected_avg) in rebuilt_positions.items():
            pos_obj = existing_positions.get(sym)
            if pos_obj is None and expected_qty > 0:
                discrepancies.append(f"MISSING_POSITION_{sym}: Thiếu vị thế {expected_qty} cổ phiếu {sym}.")
            elif pos_obj is not None and (pos_obj.quantity != expected_qty or pos_obj.average_cost != expected_avg):
                discrepancies.append(
                    f"POSITION_MISMATCH_{sym}: DB ({pos_obj.quantity} @ {pos_obj.average_cost}) != Rebuilt ({expected_qty} @ {expected_avg})."
                )

        # Tái dựng lại bảng portfolio.positions theo kết quả chuẩn từ executions
        self.session.execute(delete(Position).where(Position.account_id == account.id))
        self.session.flush()

        rebuilt_count = 0
        for sym, (expected_qty, expected_avg) in rebuilt_positions.items():
            if expected_qty <= 0:
                continue
            stock = self.session.scalar(select(Stock).where(Stock.symbol == sym))
            if stock is None:
                continue
            self.session.add(
                Position(
                    account_id=account.id,
                    stock_id=stock.id,
                    quantity=expected_qty,
                    available_quantity=min(
                        expected_qty, settled_available_quantity(fills_by_symbol.get(sym, []), as_of_date)
                    ),
                    average_cost=expected_avg,
                )
            )
            rebuilt_count += 1

        is_consistent = len(discrepancies) == 0
        record_audit_log(
            session=self.session,
            actor=actor,
            action="PORTFOLIO_RECONCILIATION",
            entity_type="Account",
            entity_id=str(account.id),
            before_state={"cash_balance": str(prev_cash)},
            after_state={
                "rebuilt_cash_balance": str(rebuilt_cash),
                "settlement_as_of_date": as_of_date.isoformat(),
                "is_consistent_before_rebuild": is_consistent,
                "discrepancies": discrepancies,
            },
        )

        self.session.commit()
        return ReconciliationReportResponse(
            account_id=account.id,
            is_consistent_before_rebuild=is_consistent,
            previous_cash_balance=prev_cash,
            rebuilt_cash_balance=rebuilt_cash,
            discrepancies=discrepancies,
            positions_rebuilt_count=rebuilt_count,
            reconciled_at=clock.utc_now(),
            as_of_date=as_of_date,
        )
