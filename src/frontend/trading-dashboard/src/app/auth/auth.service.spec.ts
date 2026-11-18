// Ngày tạo: 2026-11-17
// Mục đích: Unit test AuthService — lưu phiên ở sessionStorage, khôi phục, đăng xuất, đổi mật khẩu.

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { makeToken, makeUser } from '../testing/auth-fixtures';
import { AuthService, SESSION_STORAGE_KEY, isSessionExpired } from './auth.service';

describe('AuthService', () => {
  let http: HttpTestingController;

  function createService(): AuthService {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    return TestBed.inject(AuthService);
  }

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  afterEach(() => {
    http?.verify();
    sessionStorage.clear();
  });

  it('login lưu phiên vào sessionStorage và không dùng localStorage', () => {
    const auth = createService();
    let role: string | undefined;
    auth.login('  Trader01 ', 'secret-password-1').subscribe((u) => (role = u.role));

    const req = http.expectOne('/api/v1/auth/login');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ username: 'Trader01', password: 'secret-password-1' });
    req.flush(makeToken('trader'));

    expect(role).toBe('trader');
    expect(auth.status()).toBe('authenticated');
    expect(auth.accessToken).toBe('test-token-value');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toContain('test-token-value');
    expect(localStorage.length).toBe(0);
  });

  it('không ghi token ra console', () => {
    const spies = [spyOn(console, 'log'), spyOn(console, 'warn'), spyOn(console, 'error'), spyOn(console, 'info')];
    const auth = createService();
    auth.login('trader01', 'secret-password-1').subscribe();
    http.expectOne('/api/v1/auth/login').flush(makeToken());
    spies.forEach((spy) => expect(spy).not.toHaveBeenCalled());
  });

  it('login thất bại không tạo phiên', () => {
    const auth = createService();
    let failed = false;
    auth.login('trader01', 'wrong').subscribe({ error: () => (failed = true) });
    http
      .expectOne('/api/v1/auth/login')
      .flush({ error: { message: 'Sai thông tin' } }, { status: 401, statusText: 'Unauthorized' });

    expect(failed).toBeTrue();
    expect(auth.status()).toBe('anonymous');
    expect(auth.accessToken).toBeNull();
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('khôi phục phiên từ sessionStorage và đồng bộ hồ sơ qua /auth/me', () => {
    const token = makeToken('viewer');
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: token.access_token, expiresAt: token.expires_at, user: token.user })
    );
    const auth = createService();
    expect(auth.status()).toBe('restoring');

    auth.restoreSession().subscribe();
    http.expectOne('/api/v1/auth/me').flush(makeUser({ role: 'admin', username: 'boss' }));

    expect(auth.status()).toBe('authenticated');
    expect(auth.role()).toBe('admin');
    expect(auth.capabilities().canManageUsers).toBeTrue();
  });

  it('phiên đã hết hạn bị xóa mà không gọi API', () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        accessToken: 'old',
        expiresAt: new Date(Date.now() - 1000).toISOString(),
        user: makeUser(),
      })
    );
    const auth = createService();
    auth.restoreSession().subscribe();

    expect(auth.status()).toBe('anonymous');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(auth.notice()?.kind).toBe('info');
  });

  it('dữ liệu session hỏng bị bỏ qua và xóa', () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, '{not-json');
    const auth = createService();
    expect(auth.status()).toBe('anonymous');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('role không hợp lệ trong storage bị từ chối', () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: 'x', expiresAt: new Date(Date.now() + 5000).toISOString(), user: { username: 'a', role: 'root' } })
    );
    const auth = createService();
    expect(auth.accessToken).toBeNull();
  });

  it('khôi phục thất bại (401) đưa về anonymous', () => {
    const token = makeToken();
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: token.access_token, expiresAt: token.expires_at, user: token.user })
    );
    const auth = createService();
    auth.restoreSession().subscribe();
    http.expectOne('/api/v1/auth/me').flush({}, { status: 401, statusText: 'Unauthorized' });

    expect(auth.status()).toBe('anonymous');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(auth.notice()?.kind).toBe('error');
  });

  it('logout xóa phiên', () => {
    const auth = createService();
    auth.login('trader01', 'secret-password-1').subscribe();
    http.expectOne('/api/v1/auth/login').flush(makeToken());

    auth.logout();

    expect(auth.status()).toBe('anonymous');
    expect(auth.user()).toBeNull();
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('đổi mật khẩu thành công thì xóa phiên (token cũ bị thu hồi)', () => {
    const auth = createService();
    auth.login('trader01', 'secret-password-1').subscribe();
    http.expectOne('/api/v1/auth/login').flush(makeToken('trader', { user: makeUser({ must_change_password: true }) }));
    expect(auth.mustChangePassword()).toBeTrue();

    auth.changePassword('secret-password-1', 'another-secret-pass').subscribe();
    const req = http.expectOne('/api/v1/auth/change-password');
    expect(req.request.body).toEqual({
      current_password: 'secret-password-1',
      new_password: 'another-secret-pass',
    });
    req.flush({ message: 'ok' });

    expect(auth.status()).toBe('anonymous');
    expect(auth.notice()?.kind).toBe('success');
  });

  it('đổi mật khẩu thất bại giữ nguyên phiên', () => {
    const auth = createService();
    auth.login('trader01', 'secret-password-1').subscribe();
    http.expectOne('/api/v1/auth/login').flush(makeToken());

    auth.changePassword('bad', 'another-secret-pass').subscribe({ error: () => undefined });
    http.expectOne('/api/v1/auth/change-password').flush({ error: { message: 'sai' } }, { status: 400, statusText: 'Bad Request' });

    expect(auth.status()).toBe('authenticated');
  });

  it('yêu cầu đổi mật khẩu giữa phiên được lưu vào session hiện tại', () => {
    const auth = createService();
    auth.login('trader01', 'secret-password-1').subscribe();
    http.expectOne('/api/v1/auth/login').flush(makeToken());

    auth.handlePasswordChangeRequired('test-token-value');

    expect(auth.mustChangePassword()).toBeTrue();
    const stored = JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY) ?? '{}');
    expect(stored.user.must_change_password).toBeTrue();
  });

  it('isSessionExpired xử lý ngày không hợp lệ như đã hết hạn', () => {
    expect(isSessionExpired({ accessToken: 'a', expiresAt: 'invalid', user: makeUser() })).toBeTrue();
    expect(isSessionExpired({ accessToken: 'a', expiresAt: new Date(Date.now() + 60000).toISOString(), user: makeUser() })).toBeFalse();
  });
});
