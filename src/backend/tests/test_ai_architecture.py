# Ngày tạo: 2026-11-17
# Mục đích: AST guard bảo vệ ranh giới kiến trúc: module `app/ai` không được import/gọi trading, risk, portfolio.
# Lý do: AI chỉ giải thích dữ liệu có nguồn; tuyệt đối không có đường đi tới đặt/duyệt lệnh, hạn mức rủi ro hay số dư.

import ast
from pathlib import Path
from typing import List

import pytest

import app.ai

AI_PACKAGE_DIR = Path(app.ai.__file__).resolve().parent
FORBIDDEN_PREFIXES = ("app.trading", "app.risk", "app.portfolio")
DYNAMIC_IMPORT_FUNCS = {"import_module", "__import__"}


def _is_forbidden(module_name: str) -> bool:
    return any(module_name == p or module_name.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def find_forbidden_imports(source: str, module_name: str) -> List[str]:
    """Phát hiện import tĩnh (tuyệt đối/tương đối) và import động tới các module bị cấm."""
    tree = ast.parse(source)
    package_parts = module_name.split(".")[:-1]
    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations += [a.name for a in node.names if _is_forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if _is_forbidden(target):
                violations.append(target)
            # `from app import trading` cũng là vi phạm
            violations += [f"{target}.{a.name}" for a in node.names if _is_forbidden(f"{target}.{a.name}")]
        elif isinstance(node, ast.Call):
            func = node.func
            func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if func_name in DYNAMIC_IMPORT_FUNCS and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_forbidden(arg.value):
                    violations.append(arg.value)
    return violations


def test_ai_package_has_python_modules() -> None:
    assert len(list(AI_PACKAGE_DIR.glob("*.py"))) >= 3


@pytest.mark.parametrize("path", sorted(AI_PACKAGE_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_ai_modules_do_not_import_trading_risk_or_portfolio(path: Path) -> None:
    relative = path.relative_to(AI_PACKAGE_DIR.parent.parent).with_suffix("")
    module_name = ".".join(relative.parts)
    violations = find_forbidden_imports(path.read_text(encoding="utf-8"), module_name)
    assert not violations, f"{module_name} vi phạm cô lập AI: {violations}"


@pytest.mark.parametrize(
    "source",
    [
        "import app.trading.service",
        "from app.risk.service import record_audit_log",
        "from app import portfolio",
        "from app.portfolio.service import PortfolioService",
        "from ..trading.paper_broker import PaperBrokerAdapter",
        "from .. import trading",
        "from ..risk import engine",
        "import importlib\nimportlib.import_module('app.trading.service')",
        "__import__('app.risk.engine')",
    ],
)
def test_ast_guard_detects_forbidden_imports(source: str) -> None:
    assert find_forbidden_imports(source, "app.ai.service")


def test_ast_guard_allows_legitimate_ai_imports() -> None:
    source = "from app.schemas.ai import AiAnalyzeRequest\nfrom app.indicators.models import StockSignal"
    assert find_forbidden_imports(source, "app.ai.service") == []
