# Ngày tạo: 2026-11-17
# Mục đích: Nghiệp vụ xác thực: login có khóa tài khoản, đổi mật khẩu, quản lý user và seed bootstrap admin.
# Lý do: Mọi sự kiện đăng nhập/quản lý user đều ghi `system.audit_logs`; tuyệt đối không ghi password/token/hash.

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ROLE_ADMIN, User, utc_now
from app.auth.security import (
    MIN_PASSWORD_LENGTH,
    InvalidTokenError,
    burn_password_check,
    create_access_token,
    decode_access_token,
    hash_password,
    is_valid_username,
    normalize_username,
    password_needs_rehash,
    verify_password,
)
from app.core.config import Settings, get_settings
from app.risk.service import record_audit_log
from app.schemas.auth import TokenResponse, UserCreateRequest, UserResponse, UserUpdateRequest

logger = structlog.get_logger(__name__)

ANONYMOUS_ACTOR = "anonymous"
BOOTSTRAP_ACTOR = "system_bootstrap"
GENERIC_LOGIN_ERROR = "Tên đăng nhập hoặc mật khẩu không đúng."
INVALID_SESSION_ERROR = "Phiên đăng nhập không hợp lệ hoặc đã hết hạn."


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite (dùng khi test) trả datetime naive; coi giá trị naive là UTC để so sánh an toàn."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _login_failed() -> HTTPException:
    # Mọi lý do thất bại (sai mật khẩu, không tồn tại, bị khóa, bị vô hiệu hóa) dùng chung một thông điệp để chống dò username
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=GENERIC_LOGIN_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


def invalid_session_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=INVALID_SESSION_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_state(user: User) -> Dict[str, Any]:
    return {
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "failed_login_count": user.failed_login_count,
        "locked_until": as_utc(user.locked_until).isoformat() if user.locked_until else None,
    }


class AuthService:
    """Service xác thực/quản lý người dùng; không bao giờ trả hoặc log password/password_hash."""

    def __init__(self, session: Session, settings: Optional[Settings] = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def _get_by_username(self, normalized: str, for_update: bool = False) -> Optional[User]:
        stmt = select(User).where(User.username == normalized)
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.scalar(stmt)

    def _register_failure(self, user: User, now: datetime) -> bool:
        """Tăng bộ đếm đăng nhập sai và khóa tài khoản khi chạm ngưỡng; trả về True nếu vừa bị khóa."""
        user.failed_login_count += 1
        if user.failed_login_count >= self.settings.AUTH_MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=self.settings.AUTH_LOCKOUT_MINUTES)
            return True
        return False

    def _audit_login_failure(
        self, user: Optional[User], reason: str, client_ip: Optional[str], locked_now: bool = False
    ) -> None:
        # Không lưu username đã gõ khi user không tồn tại vì có thể là password gõ nhầm vào ô username
        record_audit_log(
            session=self.session,
            actor=user.username if user else ANONYMOUS_ACTOR,
            action="AUTH_LOGIN_FAILED",
            entity_type="User",
            entity_id=str(user.id) if user else None,
            before_state=None,
            after_state={"reason": reason, "client_ip": client_ip, "locked_now": locked_now},
        )
        self.session.commit()

    def login(self, username: str, password: str, client_ip: Optional[str] = None) -> TokenResponse:
        now = utc_now()
        user = self._get_by_username(normalize_username(username), for_update=True)

        if user is None:
            burn_password_check(password)
            self._audit_login_failure(None, "unknown_user", client_ip)
            raise _login_failed()

        locked_until = as_utc(user.locked_until)
        if locked_until is not None and locked_until > now:
            burn_password_check(password)
            self._audit_login_failure(user, "account_locked", client_ip)
            raise _login_failed()
        if locked_until is not None:
            user.locked_until = None
            user.failed_login_count = 0

        if not verify_password(user.password_hash, password):
            locked_now = self._register_failure(user, now)
            self._audit_login_failure(user, "invalid_credentials", client_ip, locked_now=locked_now)
            raise _login_failed()

        if not user.is_active:
            self._audit_login_failure(user, "account_inactive", client_ip)
            raise _login_failed()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        token, expires_at = create_access_token(self.settings, user.id, user.token_version, now=now)
        record_audit_log(
            session=self.session,
            actor=user.username,
            action="AUTH_LOGIN_SUCCESS",
            entity_type="User",
            entity_id=str(user.id),
            after_state={"client_ip": client_ip},
        )
        self.session.commit()
        return TokenResponse(
            access_token=token,
            expires_in=self.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            expires_at=expires_at,
            user=UserResponse.model_validate(user),
        )

    def authenticate_token(self, token: str) -> User:
        """Xác thực JWT và đối chiếu DB: user phải còn active và token_version phải khớp (thu hồi token)."""
        try:
            claims = decode_access_token(self.settings, token)
        except InvalidTokenError as exc:
            raise invalid_session_error() from exc
        user = self.session.get(User, claims.user_id)
        if user is None or not user.is_active or user.token_version != claims.token_version:
            raise invalid_session_error()
        return user

    def change_password(
        self, user: User, current_password: str, new_password: str, client_ip: Optional[str] = None
    ) -> None:
        now = utc_now()
        locked_until = as_utc(user.locked_until)
        if locked_until is not None and locked_until > now:
            # JWT hợp lệ không được dùng làm oracle dò mật khẩu hiện tại khi tài khoản đang bị khóa;
            # không verify và không đụng bộ đếm (giống login) nên cũng không gia hạn/bypass khóa.
            burn_password_check(current_password)
            record_audit_log(
                session=self.session,
                actor=user.username,
                action="AUTH_PASSWORD_CHANGE_FAILED",
                entity_type="User",
                entity_id=str(user.id),
                after_state={"reason": "account_locked", "client_ip": client_ip, "locked_now": False},
            )
            self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Tài khoản đang bị khóa tạm thời do nhập sai nhiều lần. Vui lòng thử lại sau.",
            )
        if locked_until is not None:
            user.locked_until = None
            user.failed_login_count = 0

        if not verify_password(user.password_hash, current_password):
            # Tính vào bộ đếm khóa để kẻ cầm token bị đánh cắp không dò được mật khẩu hiện tại
            locked_now = self._register_failure(user, now)
            record_audit_log(
                session=self.session,
                actor=user.username,
                action="AUTH_PASSWORD_CHANGE_FAILED",
                entity_type="User",
                entity_id=str(user.id),
                after_state={
                    "reason": "invalid_current_password",
                    "client_ip": client_ip,
                    "locked_now": locked_now,
                },
            )
            self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu hiện tại không đúng."
            )

        if verify_password(user.password_hash, new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu mới phải khác mật khẩu hiện tại.",
            )

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.failed_login_count = 0
        user.locked_until = None
        user.token_version += 1
        record_audit_log(
            session=self.session,
            actor=user.username,
            action="AUTH_PASSWORD_CHANGED",
            entity_type="User",
            entity_id=str(user.id),
            after_state={"client_ip": client_ip, "tokens_revoked": True},
        )
        self.session.commit()

    def list_users(self) -> list[User]:
        return list(self.session.scalars(select(User).order_by(User.username)).all())

    def create_user(self, request: UserCreateRequest, admin: User) -> User:
        if self._get_by_username(request.username) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username đã tồn tại.")

        user = User(
            username=request.username,
            password_hash=hash_password(request.password),
            role=request.role,
            is_active=request.is_active,
            must_change_password=request.must_change_password,
        )
        self.session.add(user)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Username đã tồn tại."
            ) from exc

        record_audit_log(
            session=self.session,
            actor=admin.username,
            action="AUTH_USER_CREATED",
            entity_type="User",
            entity_id=str(user.id),
            after_state=_user_state(user),
        )
        self.session.commit()
        return user

    def update_user(self, user_id: uuid.UUID, request: UserUpdateRequest, admin: User) -> User:
        target = self.session.scalar(select(User).where(User.id == user_id).with_for_update())
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng.")

        is_self = target.id == admin.id
        if is_self and (
            (request.role is not None and request.role != target.role) or request.is_active is False
        ):
            # Chặn admin tự hạ quyền/vô hiệu hóa chính mình để hệ thống không mất tài khoản quản trị cuối cùng
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự đổi vai trò hoặc vô hiệu hóa tài khoản của chính mình.",
            )

        before = _user_state(target)
        revoke_tokens = False

        if request.role is not None and request.role != target.role:
            target.role = request.role
            revoke_tokens = True
        if request.is_active is not None and request.is_active != target.is_active:
            target.is_active = request.is_active
            revoke_tokens = revoke_tokens or not request.is_active
        if request.new_password is not None:
            target.password_hash = hash_password(request.new_password)
            target.must_change_password = (
                True if request.must_change_password is None else request.must_change_password
            )
            revoke_tokens = True
        elif request.must_change_password is not None:
            target.must_change_password = request.must_change_password
        if request.unlock:
            target.failed_login_count = 0
            target.locked_until = None
        if revoke_tokens:
            target.token_version += 1

        after = _user_state(target)
        after["password_reset"] = request.new_password is not None
        after["tokens_revoked"] = revoke_tokens
        record_audit_log(
            session=self.session,
            actor=admin.username,
            action="AUTH_USER_UPDATED",
            entity_type="User",
            entity_id=str(target.id),
            before_state=before,
            after_state=after,
        )
        self.session.commit()
        return target


def ensure_bootstrap_admin(session: Session, settings: Optional[Settings] = None) -> Optional[User]:
    """
    Seed admin đầu tiên từ biến môi trường một cách idempotent:
    - Thiếu username/password -> bỏ qua; user đã tồn tại -> giữ nguyên (không bao giờ ghi đè mật khẩu).
    """
    cfg = settings or get_settings()
    username = normalize_username(cfg.BOOTSTRAP_ADMIN_USERNAME)
    password = cfg.BOOTSTRAP_ADMIN_PASSWORD
    if not username or not password:
        return None
    if not is_valid_username(username) or len(password) < MIN_PASSWORD_LENGTH:
        logger.warning("bootstrap_admin_skipped_invalid_credentials_format")
        return None

    existing = session.scalar(select(User).where(User.username == username))
    if existing is not None:
        return existing

    admin = User(
        username=username,
        password_hash=hash_password(password),
        role=ROLE_ADMIN,
        is_active=True,
        must_change_password=False,
    )
    session.add(admin)
    session.flush()
    record_audit_log(
        session=session,
        actor=BOOTSTRAP_ACTOR,
        action="AUTH_BOOTSTRAP_ADMIN_CREATED",
        entity_type="User",
        entity_id=str(admin.id),
        after_state={"username": admin.username, "role": admin.role},
    )
    session.commit()
    logger.info("bootstrap_admin_created", username=username)
    return admin
