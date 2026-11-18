// Ngày tạo: 2026-11-17
// Mục đích: Fixture dùng chung cho unit test xác thực (không chứa secret thật).

import { AuthUser, TokenResponse, UserRole } from '../auth/auth.models';

export function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 'user-1',
    username: 'trader01',
    role: 'trader',
    is_active: true,
    must_change_password: false,
    failed_login_count: 0,
    locked_until: null,
    last_login_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

export function makeToken(role: UserRole = 'trader', overrides: Partial<TokenResponse> = {}): TokenResponse {
  return {
    access_token: 'test-token-value',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: new Date(Date.now() + 3600_000).toISOString(),
    user: makeUser({ role }),
    ...overrides,
  };
}
