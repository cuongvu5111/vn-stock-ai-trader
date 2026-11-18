# Ngày tạo: 2026-11-17
# Mục đích: FastAPI dependencies xác thực Bearer JWT và kiểm soát quyền theo vai trò (RBAC).
# Lý do: Mọi endpoint (trừ health/login) phải đi qua `require_*`; role luôn đọc từ DB nên đổi quyền có hiệu lực ngay.

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.models import ROLE_ADMIN, ROLE_TRADER, ROLE_VIEWER, User
from app.auth.service import AuthService, invalid_session_error
from app.core.database import get_db_session

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token lấy từ POST /api/v1/auth/login")

VIEWER_AND_ABOVE = (ROLE_VIEWER, ROLE_TRADER, ROLE_ADMIN)
TRADER_AND_ABOVE = (ROLE_TRADER, ROLE_ADMIN)
ADMIN_ONLY = (ROLE_ADMIN,)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> User:
    """Trả về user hợp lệ từ JWT (còn active, token_version khớp). Không kiểm tra vai trò."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise invalid_session_error()
    return AuthService(session=session).authenticate_token(credentials.credentials)


def require_roles(*allowed_roles: str):
    """Tạo dependency chỉ cho phép các vai trò chỉ định; user phải đổi mật khẩu thì bị chặn mọi endpoint nghiệp vụ."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PASSWORD_CHANGE_REQUIRED",
                    "message": (
                        "Bạn phải đổi mật khẩu (POST /api/v1/auth/change-password) "
                        "trước khi tiếp tục."
                    ),
                },
            )
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vai trò hiện tại không có quyền thực hiện thao tác này.",
            )
        return user

    return checker


require_viewer = require_roles(*VIEWER_AND_ABOVE)
require_trader = require_roles(*TRADER_AND_ABOVE)
require_admin = require_roles(*ADMIN_ONLY)
