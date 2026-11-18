# Ngày tạo: 2026-11-17
# Mục đích: Băm mật khẩu Argon2id, phát hành/giải mã JWT access token và chuẩn hóa username.
# Lý do: Tách riêng các primitive bảo mật để service/dependency không phụ thuộc trực tiếp vào thư viện bên ngoài.

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()


class InvalidTokenError(Exception):
    """Token không hợp lệ, sai chữ ký hoặc đã hết hạn (không tiết lộ chi tiết cho client)."""


def normalize_username(raw: str) -> str:
    """Username được lưu dạng chữ thường, bỏ khoảng trắng hai đầu để tra cứu không phân biệt hoa/thường."""
    return raw.strip().lower()


def is_valid_username(normalized: str) -> bool:
    return USERNAME_PATTERN.fullmatch(normalized) is not None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("dummy-password-for-constant-time-check")


def burn_password_check(password: str) -> None:
    """Chạy một lần verify giả khi không có user để thời gian phản hồi không lộ username tồn tại hay không."""
    verify_password(_dummy_hash(), password)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_version: int


def create_access_token(
    settings: Settings,
    user_id: uuid.UUID,
    token_version: int,
    now: Optional[datetime] = None,
) -> tuple[str, datetime]:
    """Phát hành JWT HS256; chỉ mang id + token_version, role luôn được đọc lại từ DB khi xác thực."""
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": issued_at,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> TokenClaims:
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "ver"]},
        )
        return TokenClaims(user_id=uuid.UUID(claims["sub"]), token_version=int(claims["ver"]))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError from exc
