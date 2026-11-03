# Ngày tạo: 2026-11-03
# Mục đích: Quản lý cấu hình rủi ro (`system.risk_configs`), Kill Switch và ghi nhận Nhật ký kiểm toán (`system.audit_logs`).

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_correlation_id
from app.schemas.trading import (
    AuditLogItemResponse,
    RiskConfigPayload,
    RiskConfigUpdateRequest,
    RiskStatusResponse,
)
from app.system.models import AuditLog, RiskConfig


def record_audit_log(
    session: Session,
    actor: str,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Hàm dùng chung để ghi nhận bất biến mọi thao tác quan trọng vào `system.audit_logs`."""
    audit = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        correlation_id=get_correlation_id(),
    )
    session.add(audit)
    session.flush()
    return audit


class RiskService:
    """Service quản lý hạn mức rủi ro và Kill Switch của hệ thống."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_active_config_row(self) -> RiskConfig:
        """Lấy bản ghi RiskConfig đang active hoặc khởi tạo cấu hình mặc định (Mục 9.1)."""
        row = self.session.scalar(
            select(RiskConfig)
            .where(RiskConfig.is_active.is_(True))
            .order_by(RiskConfig.created_at.desc())
        )
        if row is None:
            default_payload = RiskConfigPayload()
            row = RiskConfig(
                name="DEFAULT_PAPER_RISK_CONFIG",
                configuration=default_payload.model_dump(mode="json"),
                is_active=True,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def get_active_payload(self) -> RiskConfigPayload:
        """Trả về đối tượng RiskConfigPayload đã chuẩn hóa từ bản ghi active."""
        row = self.get_or_create_active_config_row()
        return RiskConfigPayload.model_validate(row.configuration)

    def get_risk_status(self) -> RiskStatusResponse:
        """Lấy trạng thái cấu hình rủi ro, trạng thái Kill Switch và 20 dòng audit log gần nhất."""
        row = self.get_or_create_active_config_row()
        payload = RiskConfigPayload.model_validate(row.configuration)

        audits = self.session.scalars(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(20)
        ).all()

        return RiskStatusResponse(
            config_id=row.id,
            config_name=row.name,
            configuration=payload,
            kill_switch_active=not payload.trading_enabled,
            recent_audit_logs=[AuditLogItemResponse.model_validate(a) for a in audits],
        )

    def update_risk_config(self, request: RiskConfigUpdateRequest) -> RiskStatusResponse:
        """Cập nhật cấu hình rủi ro / Kill Switch và ghi Audit Log."""
        row = self.get_or_create_active_config_row()
        before_json = dict(row.configuration)
        after_json = request.configuration.model_dump(mode="json")

        row.configuration = after_json
        action_name = (
            "KILL_SWITCH_ACTIVATED"
            if not request.configuration.trading_enabled and before_json.get("trading_enabled", True)
            else "RISK_CONFIG_UPDATED"
        )

        record_audit_log(
            session=self.session,
            actor=request.actor,
            action=action_name,
            entity_type="RiskConfig",
            entity_id=str(row.id),
            before_state=before_json,
            after_state={"reason": request.reason, "configuration": after_json},
        )

        self.session.commit()
        self.session.refresh(row)
        return self.get_risk_status()
