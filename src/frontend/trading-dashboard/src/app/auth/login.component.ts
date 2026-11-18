// Ngày tạo: 2026-11-17
// Mục đích: Màn hình đăng nhập hiển thị trước dashboard.

import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { describeHttpError, extractServerMessage } from './api-error';
import { AuthService } from './auth.service';

export function describeLoginError(err: unknown): string {
  if (err instanceof HttpErrorResponse && (err.status === 401 || err.status === 423)) {
    return extractServerMessage(err) ?? 'Tên đăng nhập hoặc mật khẩu không đúng.';
  }
  return describeHttpError(err, 'Không thể đăng nhập');
}

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="auth-screen">
      <form class="card auth-card" (ngSubmit)="submit()" #loginForm="ngForm" novalidate>
        <h2>Đăng nhập VN Stock AI</h2>
        <span class="hint">Paper Trading MVP — cần đăng nhập để xem dashboard và thao tác.</span>

        @if (auth.notice(); as notice) {
          <div class="auth-alert" [class.info]="notice.kind === 'info'" [class.success]="notice.kind === 'success'" role="status">
            {{ notice.message }}
          </div>
        }
        @if (errorMessage) {
          <div class="auth-alert" role="alert">{{ errorMessage }}</div>
        }

        <div class="form-group">
          <label for="loginUsername">Tên đăng nhập</label>
          <input
            id="loginUsername"
            name="username"
            type="text"
            autocomplete="username"
            required
            [(ngModel)]="username"
            [disabled]="isSubmitting"
          />
        </div>
        <div class="form-group">
          <label for="loginPassword">Mật khẩu</label>
          <input
            id="loginPassword"
            name="password"
            type="password"
            autocomplete="current-password"
            required
            [(ngModel)]="password"
            [disabled]="isSubmitting"
          />
        </div>
        <button type="submit" class="btn btn-primary w-full" [disabled]="isSubmitting || !canSubmit">
          {{ isSubmitting ? 'Đang đăng nhập...' : 'Đăng nhập' }}
        </button>
      </form>
    </div>
  `,
})
export class LoginComponent {
  readonly auth = inject(AuthService);

  username = '';
  password = '';
  isSubmitting = false;
  errorMessage = '';

  get canSubmit(): boolean {
    return this.username.trim().length > 0 && this.password.length > 0;
  }

  submit(): void {
    if (!this.canSubmit || this.isSubmitting) {
      return;
    }
    this.isSubmitting = true;
    this.errorMessage = '';
    this.auth.login(this.username, this.password).subscribe({
      next: () => {
        this.isSubmitting = false;
        this.password = '';
      },
      error: (err: unknown) => {
        this.isSubmitting = false;
        this.password = '';
        this.errorMessage = describeLoginError(err);
      },
    });
  }
}
