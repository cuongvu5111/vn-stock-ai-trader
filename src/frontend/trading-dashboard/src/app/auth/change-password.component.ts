// Ngày tạo: 2026-11-17
// Mục đích: Form đổi mật khẩu bắt buộc khi `must_change_password = true` (chặn toàn bộ dashboard cho tới khi đổi xong).

import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { describeHttpError } from './api-error';
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from './auth.models';
import { AuthService } from './auth.service';

export function validateNewPassword(current: string, next: string, confirm: string): string | null {
  if (!current) {
    return 'Vui lòng nhập mật khẩu hiện tại.';
  }
  if (next.length < MIN_PASSWORD_LENGTH) {
    return `Mật khẩu mới phải có ít nhất ${MIN_PASSWORD_LENGTH} ký tự.`;
  }
  if (next.length > MAX_PASSWORD_LENGTH) {
    return `Mật khẩu mới tối đa ${MAX_PASSWORD_LENGTH} ký tự.`;
  }
  if (next === current) {
    return 'Mật khẩu mới phải khác mật khẩu hiện tại.';
  }
  if (next !== confirm) {
    return 'Xác nhận mật khẩu mới không khớp.';
  }
  return null;
}

@Component({
  selector: 'app-change-password',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="auth-screen">
      <form class="card auth-card" (ngSubmit)="submit()" novalidate>
        <h2>Đổi mật khẩu bắt buộc</h2>
        <span class="hint">
          Tài khoản <strong>{{ auth.user()?.username }}</strong> phải đổi mật khẩu trước khi sử dụng hệ thống.
          Sau khi đổi, mọi phiên cũ bị thu hồi và bạn cần đăng nhập lại.
        </span>

        @if (errorMessage) {
          <div class="auth-alert" role="alert">{{ errorMessage }}</div>
        }

        <div class="form-group">
          <label for="cpCurrent">Mật khẩu hiện tại</label>
          <input id="cpCurrent" name="current" type="password" autocomplete="current-password" [(ngModel)]="currentPassword" [disabled]="isSubmitting" />
        </div>
        <div class="form-group">
          <label for="cpNew">Mật khẩu mới (tối thiểu {{ minLength }} ký tự)</label>
          <input id="cpNew" name="next" type="password" autocomplete="new-password" [(ngModel)]="newPassword" [disabled]="isSubmitting" />
        </div>
        <div class="form-group">
          <label for="cpConfirm">Nhập lại mật khẩu mới</label>
          <input id="cpConfirm" name="confirm" type="password" autocomplete="new-password" [(ngModel)]="confirmPassword" [disabled]="isSubmitting" />
        </div>

        <div class="row-actions">
          <button type="submit" class="btn btn-primary" [disabled]="isSubmitting">
            {{ isSubmitting ? 'Đang đổi mật khẩu...' : 'Đổi mật khẩu' }}
          </button>
          <button type="button" class="btn" [disabled]="isSubmitting" (click)="auth.logout()">Đăng xuất</button>
        </div>
      </form>
    </div>
  `,
})
export class ChangePasswordComponent {
  readonly auth = inject(AuthService);
  readonly minLength = MIN_PASSWORD_LENGTH;

  currentPassword = '';
  newPassword = '';
  confirmPassword = '';
  isSubmitting = false;
  errorMessage = '';

  submit(): void {
    if (this.isSubmitting) {
      return;
    }
    const validationError = validateNewPassword(this.currentPassword, this.newPassword, this.confirmPassword);
    if (validationError) {
      this.errorMessage = validationError;
      return;
    }
    this.isSubmitting = true;
    this.errorMessage = '';
    this.auth.changePassword(this.currentPassword, this.newPassword).subscribe({
      next: () => {
        this.isSubmitting = false;
        this.clearFields();
      },
      error: (err: unknown) => {
        this.isSubmitting = false;
        this.clearFields();
        this.errorMessage = describeHttpError(err, 'Không thể đổi mật khẩu');
      },
    });
  }

  private clearFields(): void {
    this.currentPassword = '';
    this.newPassword = '';
    this.confirmPassword = '';
  }
}
