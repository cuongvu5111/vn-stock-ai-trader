# Ngày tạo: 2026-11-17
# Mục đích: REST API xác thực và quản lý người dùng (/api/v1/auth/...).

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User
from app.auth.service import AuthService
from app.core.database import get_db_session
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication & User Management"])


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse, summary="Đăng nhập (public) và nhận JWT access token")
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    return AuthService(session=session).login(
        username=payload.username, password=payload.password, client_ip=_client_ip(request)
    )


@router.get("/me", response_model=UserResponse, summary="Thông tin người dùng hiện tại")
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Đổi mật khẩu (thu hồi toàn bộ token cũ, cần đăng nhập lại)",
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MessageResponse:
    AuthService(session=session).change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        client_ip=_client_ip(request),
    )
    return MessageResponse(message="Đổi mật khẩu thành công. Vui lòng đăng nhập lại.")


@router.get("/users", response_model=UserListResponse, summary="Danh sách người dùng (admin)")
def list_users(
    _: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserListResponse:
    users = AuthService(session=session).list_users()
    return UserListResponse(total=len(users), items=[UserResponse.model_validate(u) for u in users])


@router.post("/users", response_model=UserResponse, status_code=201, summary="Tạo người dùng (admin)")
def create_user(
    payload: UserCreateRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserResponse:
    user = AuthService(session=session).create_user(request=payload, admin=admin)
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Cập nhật vai trò/trạng thái/mật khẩu/khóa của người dùng (admin)",
)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserResponse:
    user = AuthService(session=session).update_user(user_id=user_id, request=payload, admin=admin)
    return UserResponse.model_validate(user)
