// Ngày tạo: 2026-11-17
// Mục đích: AuthService — đăng nhập, đăng xuất, khôi phục phiên và đổi mật khẩu.
// Lý do:
//   - Access token chỉ lưu ở sessionStorage (MVP chạy LAN): đóng tab là mất phiên, không dùng localStorage.
//   - Tuyệt đối không log token; backend là nơi quyết định cuối cùng về hiệu lực của token.

import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, tap, timeout } from 'rxjs';
import {
  AuthUser,
  ChangePasswordRequest,
  LoginRequest,
  MessageResponse,
  StoredSession,
  TokenResponse,
  USER_ROLES,
  UserRole,
} from './auth.models';
import { capabilitiesFor } from './auth.permissions';

export const SESSION_STORAGE_KEY = 'vsat.auth.session';
export const AUTH_API_BASE = '/api/v1/auth';
const RESTORE_TIMEOUT_MS = 10000;

export type AuthStatus = 'restoring' | 'anonymous' | 'authenticated';

export interface AuthNotice {
  kind: 'info' | 'error' | 'success';
  message: string;
}

function resolveStorage(): Storage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage;
  } catch {
    return null;
  }
}

function isStoredSession(value: unknown): value is StoredSession {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const user = candidate['user'] as Record<string, unknown> | undefined;
  return (
    typeof candidate['accessToken'] === 'string' &&
    candidate['accessToken'].length > 0 &&
    typeof candidate['expiresAt'] === 'string' &&
    !!user &&
    typeof user['username'] === 'string' &&
    typeof user['role'] === 'string' &&
    USER_ROLES.includes(user['role'] as UserRole)
  );
}

export function isSessionExpired(session: StoredSession, nowMs = Date.now()): boolean {
  const expiresMs = Date.parse(session.expiresAt);
  return Number.isNaN(expiresMs) || expiresMs <= nowMs;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly storage = resolveStorage();
  private readonly sessionSignal = signal<StoredSession | null>(null);
  private readonly statusSignal = signal<AuthStatus>('anonymous');
  private readonly noticeSignal = signal<AuthNotice | null>(null);

  readonly status = this.statusSignal.asReadonly();
  readonly notice = this.noticeSignal.asReadonly();
  readonly user = computed<AuthUser | null>(() => this.sessionSignal()?.user ?? null);
  readonly role = computed<UserRole | null>(() => this.user()?.role ?? null);
  readonly capabilities = computed(() => capabilitiesFor(this.role()));
  readonly mustChangePassword = computed(() => this.user()?.must_change_password === true);

  constructor() {
    const stored = this.readStoredSession();
    if (stored) {
      this.sessionSignal.set(stored);
      this.statusSignal.set('restoring');
    }
  }

  get accessToken(): string | null {
    return this.sessionSignal()?.accessToken ?? null;
  }

  login(username: string, password: string): Observable<AuthUser> {
    const body: LoginRequest = { username: username.trim(), password };
    return this.http.post<TokenResponse>(`${AUTH_API_BASE}/login`, body).pipe(
      tap((res) => this.startSession(res)),
      map((res) => res.user)
    );
  }

  logout(notice: AuthNotice | null = { kind: 'info', message: 'Bạn đã đăng xuất.' }): void {
    this.clearSession(notice);
  }

  // Gọi từ interceptor khi backend trả 401; bỏ qua nếu token đã bị thay (đăng nhập lại) hoặc đã đăng xuất
  handleUnauthorized(usedToken: string): void {
    if (this.accessToken !== usedToken) {
      return;
    }
    this.clearSession({
      kind: 'error',
      message: 'Phiên đăng nhập đã hết hạn hoặc bị thu hồi. Vui lòng đăng nhập lại.',
    });
  }

  handlePasswordChangeRequired(usedToken: string): void {
    const current = this.sessionSignal();
    if (!current || current.accessToken !== usedToken) {
      return;
    }
    this.persist({
      ...current,
      user: { ...current.user, must_change_password: true },
    });
    this.noticeSignal.set({
      kind: 'info',
      message: 'Tài khoản được yêu cầu đổi mật khẩu trước khi tiếp tục.',
    });
  }

  restoreSession(): Observable<void> {
    const session = this.sessionSignal();
    if (!session) {
      this.statusSignal.set('anonymous');
      return of(void 0);
    }
    if (isSessionExpired(session)) {
      this.clearSession({ kind: 'info', message: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.' });
      return of(void 0);
    }
    // /auth/me không bị chặn bởi must_change_password nên luôn đồng bộ được hồ sơ mới nhất
    return this.http.get<AuthUser>(`${AUTH_API_BASE}/me`).pipe(
      timeout(RESTORE_TIMEOUT_MS),
      tap((user) => {
        const current = this.sessionSignal();
        if (current) {
          this.persist({ ...current, user });
          this.statusSignal.set('authenticated');
        }
      }),
      map(() => void 0),
      catchError(() => {
        if (this.statusSignal() === 'restoring') {
          this.clearSession({
            kind: 'error',
            message: 'Không khôi phục được phiên đăng nhập. Vui lòng đăng nhập lại.',
          });
        }
        return of(void 0);
      })
    );
  }

  // Backend thu hồi mọi token cũ sau khi đổi mật khẩu nên bắt buộc đăng nhập lại
  changePassword(currentPassword: string, newPassword: string): Observable<MessageResponse> {
    const body: ChangePasswordRequest = {
      current_password: currentPassword,
      new_password: newPassword,
    };
    return this.http.post<MessageResponse>(`${AUTH_API_BASE}/change-password`, body).pipe(
      tap(() =>
        this.clearSession({
          kind: 'success',
          message: 'Đổi mật khẩu thành công. Vui lòng đăng nhập lại bằng mật khẩu mới.',
        })
      )
    );
  }

  dismissNotice(): void {
    this.noticeSignal.set(null);
  }

  private startSession(res: TokenResponse): void {
    this.noticeSignal.set(null);
    this.persist({ accessToken: res.access_token, expiresAt: res.expires_at, user: res.user });
    this.statusSignal.set('authenticated');
  }

  private persist(session: StoredSession): void {
    this.sessionSignal.set(session);
    try {
      this.storage?.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } catch {
      // Storage đầy/bị chặn: vẫn giữ phiên trong bộ nhớ, chỉ không khôi phục được sau khi tải lại trang
    }
  }

  private clearSession(notice: AuthNotice | null): void {
    this.sessionSignal.set(null);
    this.statusSignal.set('anonymous');
    this.noticeSignal.set(notice);
    try {
      this.storage?.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // Bỏ qua lỗi storage
    }
  }

  private readStoredSession(): StoredSession | null {
    try {
      const raw = this.storage?.getItem(SESSION_STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const parsed: unknown = JSON.parse(raw);
      if (isStoredSession(parsed)) {
        return parsed;
      }
    } catch {
      // JSON hỏng: coi như không có phiên
    }
    try {
      this.storage?.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // Bỏ qua lỗi storage
    }
    return null;
  }
}
