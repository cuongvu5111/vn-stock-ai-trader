// Ngày tạo: 2026-11-17
// Mục đích: Test luồng màn hình theo trạng thái xác thực và hiển thị theo vai trò (viewer/trader/admin).

import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { UserRole } from './auth/auth.models';
import { authInterceptor } from './auth/auth.interceptor';
import { SESSION_STORAGE_KEY } from './auth/auth.service';
import { DashboardComponent } from './dashboard/dashboard.component';
import { TradeProposalItem } from './models/trading.models';
import { makeToken, makeUser } from './testing/auth-fixtures';

describe('AppComponent (xác thực & vai trò)', () => {
  let controller: HttpTestingController;

  function seedSession(role: UserRole, mustChange = false): void {
    const token = makeToken(role, { user: makeUser({ role, must_change_password: mustChange, username: `${role}01` }) });
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: token.access_token, expiresAt: token.expires_at, user: token.user })
    );
  }

  function mount(): ComponentFixture<AppComponent> {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return fixture;
  }

  function flushMe(fixture: ComponentFixture<AppComponent>, role: UserRole, mustChange = false): void {
    controller
      .expectOne('/api/v1/auth/me')
      .flush(makeUser({ role, must_change_password: mustChange, username: `${role}01` }));
    fixture.detectChanges();
  }

  function flushRisk(fixture: ComponentFixture<AppComponent>, killSwitchActive: boolean): void {
    controller.match('/api/v1/portfolio').forEach((req: TestRequest) => req.flush({ positions: [] }));
    controller.match('/api/v1/risk').forEach((req: TestRequest) =>
      req.flush({
        config_id: 'c1',
        config_name: 'default',
        configuration: {},
        kill_switch_active: killSwitchActive,
        recent_audit_logs: [],
      })
    );
    fixture.detectChanges();
  }

  function el(fixture: ComponentFixture<AppComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function buttonByText(fixture: ComponentFixture<AppComponent>, text: string): HTMLButtonElement | undefined {
    return Array.from(el(fixture).querySelectorAll('button')).find((b) => b.textContent?.includes(text));
  }

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
    });
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => sessionStorage.clear());

  it('hiển thị màn hình đăng nhập trước dashboard khi chưa có phiên', () => {
    const fixture = mount();
    expect(el(fixture).querySelector('app-login')).not.toBeNull();
    expect(el(fixture).querySelector('app-dashboard')).toBeNull();
    expect(controller.match(() => true).length).toBe(0);
  });

  it('đăng nhập thành công chuyển sang dashboard', async () => {
    const fixture = mount();
    await fixture.whenStable();
    const username = el(fixture).querySelector<HTMLInputElement>('#loginUsername')!;
    const password = el(fixture).querySelector<HTMLInputElement>('#loginPassword')!;
    username.value = 'trader01';
    username.dispatchEvent(new Event('input'));
    password.value = 'secret-password-1';
    password.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    fixture.detectChanges();

    el(fixture).querySelector('form')!.dispatchEvent(new Event('submit'));
    controller.expectOne('/api/v1/auth/login').flush(makeToken('trader'));
    fixture.detectChanges();

    expect(el(fixture).querySelector('app-dashboard')).not.toBeNull();
    expect(el(fixture).querySelector('app-login')).toBeNull();
  });

  it('đăng nhập sai hiển thị lỗi và giữ ở màn hình login', () => {
    const fixture = mount();
    const component = fixture.debugElement.children[0].componentInstance as { username: string; password: string; submit(): void };
    component.username = 'trader01';
    component.password = 'wrong-password';
    component.submit();
    controller
      .expectOne('/api/v1/auth/login')
      .flush({ error: { message: 'Tên đăng nhập hoặc mật khẩu không đúng.' } }, { status: 401, statusText: 'Unauthorized' });
    fixture.detectChanges();

    expect(el(fixture).querySelector('[role="alert"]')?.textContent).toContain('không đúng');
    expect(el(fixture).querySelector('app-dashboard')).toBeNull();
  });

  it('must_change_password bắt buộc đổi mật khẩu và chặn dashboard', () => {
    seedSession('trader', true);
    const fixture = mount();
    flushMe(fixture, 'trader', true);

    expect(el(fixture).querySelector('app-change-password')).not.toBeNull();
    expect(el(fixture).querySelector('app-dashboard')).toBeNull();
    expect(controller.match(() => true).length).toBe(0);
  });

  it('phiên hết hạn (401 từ /auth/me) đưa UI về login', () => {
    seedSession('trader');
    const fixture = mount();
    controller.expectOne('/api/v1/auth/me').flush({}, { status: 401, statusText: 'Unauthorized' });
    fixture.detectChanges();

    expect(el(fixture).querySelector('app-login')).not.toBeNull();
  });

  it('401 trong lúc dùng dashboard hủy dashboard và quay về login', () => {
    seedSession('trader');
    const fixture = mount();
    flushMe(fixture, 'trader');
    controller.match('/api/v1/portfolio').forEach((r) => r.flush({}, { status: 401, statusText: 'Unauthorized' }));
    fixture.detectChanges();

    expect(el(fixture).querySelector('app-dashboard')).toBeNull();
    expect(el(fixture).querySelector('app-login')).not.toBeNull();
    expect(el(fixture).textContent).toContain('hết hạn');
  });

  it('viewer: thấy user/role, đủ 8 tab, mọi thao tác nghiệp vụ bị vô hiệu hóa', () => {
    seedSession('viewer');
    const fixture = mount();
    flushMe(fixture, 'viewer');
    flushRisk(fixture, false);

    expect(el(fixture).querySelector('[data-testid="user-chip"]')?.textContent).toContain('viewer01');
    expect(el(fixture).querySelector('[data-testid="user-chip"]')?.textContent).toContain('viewer');
    expect(el(fixture).querySelectorAll('nav .nav-item').length).toBe(8);
    expect(buttonByText(fixture, 'Chạy Daily EOD Pipeline')!.disabled).toBeTrue();
    expect(buttonByText(fixture, 'Đồng Bộ Giá Thật')!.disabled).toBeTrue();
    expect(buttonByText(fixture, 'Bật Kill Switch')!.disabled).toBeTrue();
    expect(buttonByText(fixture, 'Đăng xuất')).toBeDefined();
  });

  it('trader: được chạy pipeline và bật kill switch nhưng không sync dữ liệu thật; không thấy tab user', () => {
    seedSession('trader');
    const fixture = mount();
    flushMe(fixture, 'trader');
    flushRisk(fixture, false);

    expect(buttonByText(fixture, 'Chạy Daily EOD Pipeline')!.disabled).toBeFalse();
    expect(buttonByText(fixture, 'Bật Kill Switch')!.disabled).toBeFalse();
    expect(buttonByText(fixture, 'Đồng Bộ Giá Thật')!.disabled).toBeTrue();
    expect(el(fixture).querySelectorAll('nav .nav-item').length).toBe(8);
  });

  it('trader không được tắt kill switch đang bật', () => {
    seedSession('trader');
    const fixture = mount();
    flushMe(fixture, 'trader');
    flushRisk(fixture, true);

    expect(buttonByText(fixture, 'Mở lại Giao dịch')!.disabled).toBeTrue();
  });

  it('trader bật kill switch qua endpoint riêng, không gửi actor', () => {
    seedSession('trader');
    const fixture = mount();
    flushMe(fixture, 'trader');
    flushRisk(fixture, false);

    buttonByText(fixture, 'Bật Kill Switch')!.click();
    const req = controller.expectOne('/api/v1/risk/kill-switch/activate');
    expect(Object.keys(req.request.body as object)).toEqual(['reason']);
    req.flush({ config_id: 'c1', config_name: 'd', configuration: {}, kill_switch_active: true, recent_audit_logs: [] });
    fixture.detectChanges();

    expect(buttonByText(fixture, 'Mở lại Giao dịch')!.disabled).toBeTrue();
  });

  it('admin: có tab 9 User Admin, sync dữ liệu thật và tắt kill switch', () => {
    seedSession('admin');
    const fixture = mount();
    flushMe(fixture, 'admin');
    flushRisk(fixture, true);

    expect(el(fixture).querySelectorAll('nav .nav-item').length).toBe(9);
    expect(buttonByText(fixture, 'Đồng Bộ Giá Thật')!.disabled).toBeFalse();
    expect(buttonByText(fixture, 'Mở lại Giao dịch')!.disabled).toBeFalse();

    buttonByText(fixture, '9. User Admin')!.click();
    fixture.detectChanges();
    controller.expectOne('/api/v1/auth/users').flush({ total: 1, items: [makeUser({ id: 'u2', username: 'viewer02', role: 'viewer' })] });
    fixture.detectChanges();
    expect(el(fixture).querySelector('app-user-admin')?.textContent).toContain('viewer02');
  });

  it('màn hình phê duyệt không còn ô nhập approver và request không chứa actor client-supplied', () => {
    seedSession('trader');
    const fixture = mount();
    flushMe(fixture, 'trader');
    buttonByText(fixture, '5. Trade Approval')!.click();
    fixture.detectChanges();

    expect(el(fixture).querySelector('#appBy')).toBeNull();

    const dashboard = fixture.debugElement.query((d) => d.componentInstance instanceof DashboardComponent)
      .componentInstance as DashboardComponent;
    const proposal = {
      id: 'p1',
      symbol: 'HPG',
      proposed_quantity: 100,
      limit_price: '25000',
      stop_loss: '24000',
    } as TradeProposalItem;

    dashboard.approveProposalItem(proposal);
    const approve = controller.expectOne('/api/v1/proposals/p1/approve');
    expect(Object.keys(approve.request.body as object)).not.toContain('approved_by');
    approve.flush({}, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();

    expect(dashboard.isLoading).toBeFalse();
    expect(dashboard.toastMessage).toContain('Không thể phê duyệt Proposal');

    dashboard.rejectProposalItem(proposal);
    const reject = controller.expectOne('/api/v1/proposals/p1/reject');
    expect(Object.keys(reject.request.body as object)).not.toContain('rejected_by');
    reject.flush({}, { status: 500, statusText: 'Server Error' });

    dashboard.cancelPaperOrder({ id: 'o1', symbol: 'HPG' } as never);
    const cancel = controller.expectOne((r) => r.url === '/api/v1/orders/o1/cancel');
    expect(cancel.request.params.keys().length).toBe(0);
    cancel.flush({}, { status: 500, statusText: 'Server Error' });

    dashboard.runPortfolioReconciliation();
    const reconcile = controller.expectOne((r) => r.url === '/api/v1/portfolio/reconcile');
    expect(reconcile.request.params.keys().length).toBe(0);
    reconcile.flush({}, { status: 500, statusText: 'Server Error' });
    expect(dashboard.isLoading).toBeFalse();
  });

  it('403 hiển thị thông báo rõ ràng và không treo loading', () => {
    seedSession('viewer');
    const fixture = mount();
    flushMe(fixture, 'viewer');
    const dashboard = fixture.debugElement.query((d) => d.componentInstance instanceof DashboardComponent)
      .componentInstance as DashboardComponent;

    dashboard.triggerDailyWorkflow();
    controller
      .expectOne('/api/v1/system/daily-workflow')
      .flush({ error: { message: 'Vai trò hiện tại không có quyền thực hiện thao tác này.' } }, { status: 403, statusText: 'Forbidden' });

    expect(dashboard.isLoading).toBeFalse();
    expect(dashboard.toastMessage).toContain('không có quyền');
  });
});
