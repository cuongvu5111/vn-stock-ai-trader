# Ngày tạo: 2026-11-03
# Mục đích: Tập hợp toàn bộ SQLAlchemy 2.0 models từ 6 schemas để Alembic tự động nhận diện.

from app.core.database import POSTGRES_SCHEMAS, Base
from app.indicators.models import AiReport, AnalysisRun, StockSignal, TechnicalIndicator
from app.market_data.models import DailyPrice, DataSource, ImportBatch, Stock
from app.portfolio.models import Account, CashTransaction, DailySnapshot, Position
from app.strategies.models import BacktestRun, BacktestTrade, Strategy, StrategyVersion
from app.system.models import AppSetting, AuditLog, JobRun, RiskConfig
from app.trading.models import Approval, Execution, Order, TradeProposal

__all__ = [
    "POSTGRES_SCHEMAS",
    "Base",
    "Stock",
    "DataSource",
    "ImportBatch",
    "DailyPrice",
    "AnalysisRun",
    "TechnicalIndicator",
    "StockSignal",
    "AiReport",
    "Strategy",
    "StrategyVersion",
    "BacktestRun",
    "BacktestTrade",
    "TradeProposal",
    "Approval",
    "Order",
    "Execution",
    "Account",
    "Position",
    "CashTransaction",
    "DailySnapshot",
    "RiskConfig",
    "JobRun",
    "AuditLog",
    "AppSetting",
]
