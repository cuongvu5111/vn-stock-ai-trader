// Ngày tạo: 2026-11-17
// Mục đích: TypeScript interfaces khớp Pydantic DTOs của backend `/api/v1/auth/*` (app/schemas/auth.py).
// Lý do: Chỉ UserResponse/TokenResponse mới chứa dữ liệu trả về; không DTO nào chứa password hay hash.

export type UserRole = 'admin' | 'trader' | 'viewer';

export const USER_ROLES: readonly UserRole[] = ['admin', 'trader', 'viewer'];

export interface AuthUser {
  id: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  must_change_password: boolean;
  failed_login_count: number;
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  expires_at: string;
  user: AuthUser;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface MessageResponse {
  message: string;
}

export interface UserCreateRequest {
  username: string;
  password: string;
  role: UserRole;
  is_active: boolean;
  must_change_password: boolean;
}

export interface UserUpdateRequest {
  role?: UserRole;
  is_active?: boolean;
  must_change_password?: boolean;
  new_password?: string;
  unlock?: boolean;
}

export interface UserListResponse {
  total: number;
  items: AuthUser[];
}

export interface StoredSession {
  accessToken: string;
  expiresAt: string;
  user: AuthUser;
}

export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 128;
