# Ngày tạo: 2026-11-17
# Mục đích: Kiểm thử RBAC toàn bộ endpoint, quyền Kill Switch của trader, và actor luôn lấy từ JWT.

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.schemas.trading import RiskConfigPayload
from app.system.models import AuditLog
from app.trading.models import Approval
from test_risk_paper_trading import _seed_stock_and_buy_signal

pytestmark = pytest.mark.real_auth

PUBLIC_ENDPOINTS = {
    ("GET", "/health"),
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
}
# Các endpoint chỉ cần đăng nhập (kể cả khi đang bị buộc đổi mật khẩu), không phân biệt vai trò
SELF_SERVICE_ENDPOINTS = {
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/change-password"),
}
ADMIN_ONLY_ENDPOINTS = [
    ("PUT", "/api/v1/risk"),
    ("POST", "/api/v1/risk/kill-switch/deactivate"),
    ("POST", "/api/v1/stocks"),
    ("PATCH", "/api/v1/stocks/FPT"),
    ("POST", "/api/v1/market/sync-real"),
    ("GET", "/api/v1/auth/users"),
    ("POST", "/api/v1/auth/users"),
    ("PATCH", f"/api/v1/auth/users/{uuid.uuid4()}"),
]
TRADER_ENDPOINTS = [
    ("POST", "/api/v1/indicators/calculate"),
    ("POST", "/api/v1/scanner/run"),
    ("POST", "/api/v1/signals/generate"),
    ("POST", "/api/v1/backtests"),
    ("POST", "/api/v1/ai/analyze"),
    ("POST", "/api/v1/market/imports"),
    ("POST", "/api/v1/proposals"),
    ("POST", f"/api/v1/proposals/{uuid.uuid4()}/approve"),
    ("POST", f"/api/v1/proposals/{uuid.uuid4()}/reject"),
    ("POST", f"/api/v1/orders/{uuid.uuid4()}/simulate-fill"),
    ("POST", f"/api/v1/orders/{uuid.uuid4()}/cancel"),
    ("POST", "/api/v1/portfolio/snapshots"),
    ("POST", "/api/v1/portfolio/reconcile"),
    ("POST", "/api/v1/risk/kill-switch/activate"),
]


def _concrete_path(template: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "FPT" if m.group(1) == "symbol" else str(uuid.uuid4()), template)


def _api_routes(app) -> list[tuple[str, str, APIRoute]]:
    return [
        (method, _concrete_path(route.path), route)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"})
    ]


def _depends_on_current_user(dependant) -> bool:
    return dependant.call is get_current_user or any(
        _depends_on_current_user(sub) for sub in dependant.dependencies
    )


def _audits(session, action: str) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.action == action)).all())


def test_every_non_public_route_requires_authentication(auth_app, auth_client) -> None:
    routes = _api_routes(auth_app)
    assert len(routes) > 30

    for method, path, route in routes:
        if (method, path) in PUBLIC_ENDPOINTS:
            continue
        assert _depends_on_current_user(route.dependant), f"{method} {route.path} thiếu xác thực"
        resp = auth_client.request(method, path, json={} if method != "GET" else None)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


def test_public_endpoints_do_not_require_token(auth_client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database_connection", lambda: (True, "ok"))
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/api/v1/health").status_code == 200
    login = auth_client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert login.status_code == 401  # tới được handler login (không bị chặn bởi middleware xác thực)


def test_viewer_can_only_read(auth_app, auth_client, create_user, login_headers) -> None:
    create_user("viewer1", "viewer")
    headers = login_headers("viewer1")

    for method, path, _route in _api_routes(auth_app):
        if (method, path) in PUBLIC_ENDPOINTS | SELF_SERVICE_ENDPOINTS:
            continue
        resp = auth_client.request(method, path, headers=headers, json={} if method != "GET" else None)
        if method == "GET" and not path.startswith("/api/v1/auth/users"):
            assert resp.status_code not in (401, 403), f"viewer bị chặn đọc {path}"
        else:
            assert resp.status_code == 403, f"viewer không được {method} {path} (nhận {resp.status_code})"


def test_trader_permissions_and_admin_only_endpoints(auth_client, create_user, login_headers) -> None:
    create_user("trader1", "trader")
    headers = login_headers("trader1")

    for method, path in ADMIN_ONLY_ENDPOINTS:
        resp = auth_client.request(method, path, headers=headers, json={})
        assert resp.status_code == 403, f"trader không được {method} {path} (nhận {resp.status_code})"

    for method, path in TRADER_ENDPOINTS:
        resp = auth_client.request(method, path, headers=headers, json={})
        assert resp.status_code not in (401, 403), f"trader phải được {method} {path} (nhận {resp.status_code})"


def test_admin_has_access_to_admin_endpoints(auth_client, create_user, login_headers) -> None:
    create_user("boss", "admin")
    headers = login_headers("boss")
    assert auth_client.get("/api/v1/auth/users", headers=headers).status_code == 200
    put = auth_client.put(
        "/api/v1/risk",
        json={"reason": "Điều chỉnh hạn mức", "configuration": RiskConfigPayload().model_dump(mode="json")},
        headers=headers,
    )
    assert put.status_code == 200


def test_trader_can_enable_but_not_disable_kill_switch(
    auth_client, auth_session, create_user, login_headers
) -> None:
    create_user("trader1", "trader")
    create_user("boss", "admin")
    trader = login_headers("trader1")
    admin = login_headers("boss")

    activate = auth_client.post(
        "/api/v1/risk/kill-switch/activate", json={"reason": "Thị trường biến động mạnh"}, headers=trader
    )
    assert activate.status_code == 200
    assert activate.json()["kill_switch_active"] is True
    logs = _audits(auth_session, "KILL_SWITCH_ACTIVATED")
    assert len(logs) == 1 and logs[0].actor == "trader1"

    # Idempotent: bật lại khi đã bật không tạo thêm audit
    again = auth_client.post(
        "/api/v1/risk/kill-switch/activate", json={"reason": "Bật lần hai"}, headers=trader
    )
    assert again.status_code == 200
    assert len(_audits(auth_session, "KILL_SWITCH_ACTIVATED")) == 1

    # Trader không thể tắt bằng endpoint riêng hay bằng PUT /risk
    assert auth_client.post(
        "/api/v1/risk/kill-switch/deactivate", json={"reason": "Tắt thử"}, headers=trader
    ).status_code == 403
    reopen_payload = RiskConfigPayload(trading_enabled=True).model_dump(mode="json")
    assert auth_client.put(
        "/api/v1/risk", json={"reason": "Tắt thử qua PUT", "configuration": reopen_payload}, headers=trader
    ).status_code == 403
    assert auth_client.get("/api/v1/risk", headers=trader).json()["kill_switch_active"] is True

    deactivate = auth_client.post(
        "/api/v1/risk/kill-switch/deactivate", json={"reason": "Đã kiểm tra an toàn"}, headers=admin
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["kill_switch_active"] is False
    off = _audits(auth_session, "KILL_SWITCH_DEACTIVATED")
    assert len(off) == 1 and off[0].actor == "boss"


def test_kill_switch_enabled_by_trader_blocks_new_proposals(
    auth_client, auth_session, create_user, login_headers
) -> None:
    create_user("trader1", "trader")
    headers = login_headers("trader1")
    _, signal = _seed_stock_and_buy_signal(auth_session, symbol="ACB")

    auth_client.post("/api/v1/risk/kill-switch/activate", json={"reason": "Khẩn cấp"}, headers=headers)
    blocked = auth_client.post("/api/v1/proposals", json={"signal_id": str(signal.id)}, headers=headers)
    assert blocked.status_code == 400
    assert "KILL_SWITCH" in blocked.json()["error"]["message"]


def test_require_human_approval_cannot_be_disabled(auth_client, create_user, login_headers) -> None:
    with pytest.raises(ValueError):
        RiskConfigPayload(require_human_approval=False)

    create_user("boss", "admin")
    headers = login_headers("boss")
    body = RiskConfigPayload().model_dump(mode="json")
    body["require_human_approval"] = False
    resp = auth_client.put(
        "/api/v1/risk", json={"reason": "Thử tắt Human Approval", "configuration": body}, headers=headers
    )
    assert resp.status_code == 422
    assert auth_client.get("/api/v1/risk", headers=headers).json()["configuration"]["require_human_approval"] is True


def test_risk_update_actor_comes_from_token(auth_client, auth_session, create_user, login_headers) -> None:
    create_user("boss", "admin")
    headers = login_headers("boss")
    resp = auth_client.put(
        "/api/v1/risk",
        json={
            "actor": "mallory",
            "reason": "Giảm hạn mức vị thế",
            "configuration": RiskConfigPayload(max_position_percent=15).model_dump(mode="json"),
        },
        headers=headers,
    )
    assert resp.status_code == 200
    logs = _audits(auth_session, "RISK_CONFIG_UPDATED")
    assert [a.actor for a in logs] == ["boss"]


def test_trading_actor_is_always_taken_from_jwt(auth_client, auth_session, create_user, login_headers) -> None:
    create_user("alice", "trader")
    headers = login_headers("alice")
    _, sig_fill = _seed_stock_and_buy_signal(auth_session, symbol="FPT")
    _, sig_cancel = _seed_stock_and_buy_signal(auth_session, symbol="VCB")
    _, sig_reject = _seed_stock_and_buy_signal(auth_session, symbol="HPG")

    def new_proposal(signal) -> str:
        resp = auth_client.post("/api/v1/proposals", json={"signal_id": str(signal.id)}, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    # Approve: approved_by giả mạo trong body bị bỏ qua; approved_by thiếu vẫn hợp lệ
    fill_prop = new_proposal(sig_fill)
    approved = auth_client.post(
        f"/api/v1/proposals/{fill_prop}/approve", json={"approved_by": "mallory"}, headers=headers
    )
    assert approved.status_code == 200 and approved.json()["status"] == "Submitted"
    order_id = approved.json()["order_id"]
    filled = auth_client.post(
        f"/api/v1/orders/{order_id}/simulate-fill", json={"fill_quantity": 100, "fill_price": "25000"},
        headers=headers,
    )
    assert filled.status_code == 200

    cancel_prop = new_proposal(sig_cancel)
    approved_2 = auth_client.post(f"/api/v1/proposals/{cancel_prop}/approve", json={}, headers=headers)
    assert approved_2.status_code == 200
    cancelled = auth_client.post(
        f"/api/v1/orders/{approved_2.json()['order_id']}/cancel?actor=mallory", headers=headers
    )
    assert cancelled.status_code == 200

    reject_prop = new_proposal(sig_reject)
    rejected = auth_client.post(
        f"/api/v1/proposals/{reject_prop}/reject", json={"rejected_by": "mallory"}, headers=headers
    )
    assert rejected.status_code == 200

    reconciled = auth_client.post("/api/v1/portfolio/reconcile?actor=mallory", headers=headers)
    assert reconciled.status_code == 200

    approvals = auth_session.scalars(select(Approval)).all()
    assert {a.approved_by for a in approvals} == {"alice"}
    assert {a.decision for a in approvals} == {"APPROVED", "REJECTED"}

    for action in (
        "PROPOSAL_CREATED",
        "PROPOSAL_APPROVED_AND_ORDER_CREATED",
        "PAPER_ORDER_SUBMITTED",
        "ORDER_PARTIALLYFILLED",
        "PAPER_ORDER_CANCELLED",
        "PROPOSAL_REJECTED",
        "PORTFOLIO_RECONCILIATION",
    ):
        logs = _audits(auth_session, action)
        assert logs, f"thiếu audit {action}"
        assert {a.actor for a in logs} == {"alice"}, action
    assert not [a for a in auth_session.scalars(select(AuditLog)).all() if a.actor == "mallory"]


def test_daily_workflow_audit_actor_is_authenticated_user(
    auth_client, auth_session, create_user, login_headers
) -> None:
    create_user("alice", "trader")
    headers = login_headers("alice")

    resp = auth_client.post(
        "/api/v1/system/daily-workflow", json={"run_ai_analysis": False}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    done = _audits(auth_session, "DAILY_EOD_WORKFLOW_COMPLETED")
    assert [a.actor for a in done] == ["alice"]
    assert {a.actor for a in _audits(auth_session, "PROPOSAL_CREATED")} <= {"alice"}
