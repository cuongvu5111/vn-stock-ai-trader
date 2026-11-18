// Ngày tạo: 2026-11-17
// Mục đích: Unit test authInterceptor — gắn Bearer cho /api, bỏ qua login/URL ngoài, xử lý 401 tập trung.

import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { makeToken } from '../testing/auth-fixtures';
import { authInterceptor, isApiRequestUrl } from './auth.interceptor';
import { AuthService, SESSION_STORAGE_KEY } from './auth.service';

describe('authInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let auth: AuthService;

  function loginAs(role: 'admin' | 'trader' | 'viewer' = 'trader'): void {
    auth.login('trader01', 'secret-password-1').subscribe();
    controller.expectOne('/api/v1/auth/login').flush(makeToken(role));
  }

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => {
    controller.verify();
    sessionStorage.clear();
  });

  it('isApiRequestUrl chỉ nhận đường dẫn /api tương đối', () => {
    expect(isApiRequestUrl('/api/v1/stocks')).toBeTrue();
    expect(isApiRequestUrl('/apiary')).toBeFalse();
    expect(isApiRequestUrl('https://evil.example/api/v1')).toBeFalse();
  });

  it('gắn Authorization Bearer cho request /api khi đã đăng nhập', () => {
    loginAs();
    http.get('/api/v1/stocks').subscribe();
    const req = controller.expectOne('/api/v1/stocks');
    expect(req.request.headers.get('Authorization')).toBe('Bearer test-token-value');
    req.flush({});
  });

  it('không gắn token khi chưa đăng nhập', () => {
    http.get('/api/v1/health').subscribe();
    const req = controller.expectOne('/api/v1/health');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({});
  });

  it('không gắn token cho endpoint login và URL ngoài /api', () => {
    loginAs();
    http.post('/api/v1/auth/login', { username: 'a', password: 'b' }).subscribe();
    const login = controller.expectOne('/api/v1/auth/login');
    expect(login.request.headers.has('Authorization')).toBeFalse();
    login.flush(makeToken());

    http.get('https://example.com/data').subscribe();
    const external = controller.expectOne('https://example.com/data');
    expect(external.request.headers.has('Authorization')).toBeFalse();
    external.flush({});
  });

  it('401 xóa phiên, đặt thông báo và vẫn trả lỗi cho caller', () => {
    loginAs();
    let status = 0;
    http.get('/api/v1/orders').subscribe({ error: (e) => (status = e.status) });
    controller.expectOne('/api/v1/orders').flush({ error: { message: 'x' } }, { status: 401, statusText: 'Unauthorized' });

    expect(status).toBe(401);
    expect(auth.status()).toBe('anonymous');
    expect(auth.accessToken).toBeNull();
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(auth.notice()?.kind).toBe('error');
  });

  it('403 không xóa phiên', () => {
    loginAs('viewer');
    http.post('/api/v1/proposals', {}).subscribe({ error: () => undefined });
    controller.expectOne('/api/v1/proposals').flush({ error: { message: 'cấm' } }, { status: 403, statusText: 'Forbidden' });

    expect(auth.status()).toBe('authenticated');
    expect(auth.mustChangePassword()).toBeFalse();
  });

  it('403 PASSWORD_CHANGE_REQUIRED chuyển sang luồng đổi mật khẩu', () => {
    loginAs('trader');
    http.post('/api/v1/proposals', {}).subscribe({ error: () => undefined });
    controller.expectOne('/api/v1/proposals').flush(
      {
        error: {
          code: 'PASSWORD_CHANGE_REQUIRED',
          message: 'Bạn phải đổi mật khẩu trước khi tiếp tục.',
        },
      },
      { status: 403, statusText: 'Forbidden' }
    );

    expect(auth.status()).toBe('authenticated');
    expect(auth.mustChangePassword()).toBeTrue();
    expect(auth.accessToken).toBe('test-token-value');
  });

  it('401 của login sai mật khẩu không ảnh hưởng phiên khác', () => {
    http.post('/api/v1/auth/login', {}).subscribe({ error: () => undefined });
    controller.expectOne('/api/v1/auth/login').flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(auth.notice()).toBeNull();
  });

  it('401 của token cũ không đăng xuất phiên mới', () => {
    loginAs();
    http.get('/api/v1/orders').subscribe({ error: () => undefined });
    const stale = controller.expectOne('/api/v1/orders');

    auth.logout(null);
    auth.login('trader01', 'secret-password-1').subscribe();
    controller.expectOne('/api/v1/auth/login').flush(makeToken('trader', { access_token: 'new-token' }));

    stale.flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(auth.accessToken).toBe('new-token');
  });
});
