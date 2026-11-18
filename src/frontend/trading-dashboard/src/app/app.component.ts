// Ngày tạo: 2026-11-17
// Mục đích: Component gốc điều phối trạng thái xác thực: khôi phục phiên → đăng nhập → đổi mật khẩu bắt buộc → dashboard.
// Lý do: Dashboard chỉ được tạo (và gọi API) sau khi đã xác thực; đăng xuất sẽ hủy toàn bộ state cũ của dashboard.

import { Component, OnInit, inject } from '@angular/core';
import { ChangePasswordComponent } from './auth/change-password.component';
import { AuthService } from './auth/auth.service';
import { LoginComponent } from './auth/login.component';
import { DashboardComponent } from './dashboard/dashboard.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [LoginComponent, ChangePasswordComponent, DashboardComponent],
  template: `
    @switch (auth.status()) {
      @case ('restoring') {
        <div class="auth-screen"><p class="empty-state">Đang khôi phục phiên đăng nhập...</p></div>
      }
      @case ('authenticated') {
        @if (auth.mustChangePassword()) {
          <app-change-password />
        } @else {
          <app-dashboard />
        }
      }
      @default {
        <app-login />
      }
    }
  `,
})
export class AppComponent implements OnInit {
  readonly auth = inject(AuthService);

  ngOnInit(): void {
    this.auth.restoreSession().subscribe();
  }
}
