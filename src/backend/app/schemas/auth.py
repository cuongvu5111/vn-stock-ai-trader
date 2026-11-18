# Ngày tạo: 2026-11-17
# Mục đích: Pydantic v2 DTOs cho xác thực (login, đổi mật khẩu) và quản lý người dùng.
# Lý do: Không DTO phản hồi nào chứa password/password_hash; token chỉ xuất hiện trong phản hồi login.

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    is_valid_username,
    normalize_username,
)

RoleLiteral = Literal["admin", "trader", "viewer"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: RoleLiteral
    is_active: bool
    must_change_password: bool
    failed_login_count: int = 0
    locked_until: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class MessageResponse(BaseModel):
    message: str


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    role: RoleLiteral = "viewer"
    is_active: bool = True
    must_change_password: bool = Field(
        default=True, description="Mặc định bắt người dùng đổi mật khẩu do admin cấp ở lần đăng nhập đầu"
    )

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, value: str) -> str:
        normalized = normalize_username(value)
        if not is_valid_username(normalized):
            raise ValueError(
                "Username chỉ gồm chữ thường, số, '.', '_', '-' (3-50 ký tự, bắt đầu bằng chữ hoặc số)."
            )
        return normalized


class UserUpdateRequest(BaseModel):
    role: Optional[RoleLiteral] = None
    is_active: Optional[bool] = None
    must_change_password: Optional[bool] = None
    new_password: Optional[str] = Field(
        default=None,
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description="Đặt lại mật khẩu (thu hồi mọi token cũ và bắt đổi mật khẩu ở lần đăng nhập kế tiếp)",
    )
    unlock: bool = Field(default=False, description="Gỡ khóa đăng nhập và xóa bộ đếm đăng nhập sai")


class UserListResponse(BaseModel):
    total: int
    items: List[UserResponse]
