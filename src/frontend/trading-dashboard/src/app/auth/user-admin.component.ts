// Ngày tạo: 2026-11-17
// Mục đích: Panel quản lý người dùng tối thiểu cho admin: danh sách, tạo mới, đổi vai trò/kích hoạt/ép đổi mật khẩu/reset mật khẩu/mở khóa.
// Lý do: Chỉ hiển thị với admin nhưng backend (`require_admin`) vẫn là nơi quyết định quyền; mật khẩu không bao giờ được hiển thị lại sau khi gửi.

import { DatePipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { describeHttpError } from './api-error';
import {
  AuthUser,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  USER_ROLES,
  UserCreateRequest,
  UserRole,
} from './auth.models';
import { ROLE_LABELS } from './auth.permissions';
import { AuthService } from './auth.service';
import { UserAdminApiService } from './user-admin-api.service';

const USERNAME_PATTERN = /^[a-z0-9][a-z0-9._-]{2,49}$/;

export function normalizeUsername(raw: string): string {
  return raw.trim().toLowerCase();
}

export function validateNewUser(username: string, password: string): string | null {
  if (!USERNAME_PATTERN.test(normalizeUsername(username))) {
    return "Username gồm chữ thường, số, '.', '_', '-' (3-50 ký tự, bắt đầu bằng chữ hoặc số).";
  }
  return validatePasswordLength(password);
}

export function validatePasswordLength(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH || password.length > MAX_PASSWORD_LENGTH) {
    return `Mật khẩu phải dài ${MIN_PASSWORD_LENGTH}-${MAX_PASSWORD_LENGTH} ký tự.`;
  }
  return null;
}

export function isUserLocked(user: AuthUser, nowMs = Date.now()): boolean {
  return !!user.locked_until && Date.parse(user.locked_until) > nowMs;
}

@Component({
  selector: 'app-user-admin',
  standalone: true,
  imports: [FormsModule, DatePipe],
  template: `
    <section class="card mb-2">
      <h3>Tạo Người Dùng Mới (admin)</h3>
      <form class="form-row" (ngSubmit)="createUser()" novalidate>
        <div>
          <label for="nuName">Username</label>
          <input id="nuName" name="username" type="text" autocomplete="off" [(ngModel)]="newUsername" />
        </div>
        <div>
          <label for="nuPass">Mật khẩu tạm (≥ {{ minLength }} ký tự)</label>
          <input id="nuPass" name="password" type="password" autocomplete="new-password" [(ngModel)]="newPassword" />
        </div>
        <div>
          <label for="nuRole">Vai trò</label>
          <select id="nuRole" name="role" [(ngModel)]="newRole">
            @for (role of roles; track role) {
              <option [value]="role">{{ roleLabels[role] }}</option>
            }
          </select>
        </div>
        <div>
          <label class="checkbox-label">
            <input type="checkbox" name="mustChange" [(ngModel)]="newMustChange" />
            Bắt đổi mật khẩu lần đầu
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="active" [(ngModel)]="newIsActive" />
            Kích hoạt
          </label>
        </div>
        <div>
          <button type="submit" class="btn btn-primary" [disabled]="isCreating">
            {{ isCreating ? 'Đang tạo...' : 'Tạo người dùng' }}
          </button>
        </div>
      </form>
    </section>

    @if (message; as msg) {
      <div class="auth-alert" [class.info]="msg.kind === 'info'" [class.success]="msg.kind === 'success'" role="status">
        {{ msg.text }}
      </div>
    }

    <section class="card">
      <div class="row-between">
        <h3>Danh Sách Người Dùng ({{ users.length }})</h3>
        <button type="button" class="btn btn-sm" [disabled]="isLoading" (click)="load()">Tải lại</button>
      </div>
      @if (isLoading) {
        <p class="empty-state">Đang tải danh sách người dùng...</p>
      } @else if (users.length === 0) {
        <p class="empty-state">Chưa có dữ liệu người dùng.</p>
      } @else {
        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Vai trò</th>
                <th>Trạng thái</th>
                <th>Đăng nhập gần nhất</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              @for (u of users; track u.id) {
                <tr>
                  <td>
                    <strong>{{ u.username }}</strong>
                    @if (isSelf(u)) {
                      <span class="pill"> bạn</span>
                    }
                  </td>
                  <td>
                    <select
                      [attr.aria-label]="'Vai trò của ' + u.username"
                      [ngModel]="u.role"
                      (ngModelChange)="changeRole(u, $event)"
                      [disabled]="busyUserId === u.id || isSelf(u)"
                    >
                      @for (role of roles; track role) {
                        <option [value]="role">{{ role }}</option>
                      }
                    </select>
                  </td>
                  <td>
                    <span class="pill" [class.ok]="u.is_active" [class.danger]="!u.is_active">
                      {{ u.is_active ? 'active' : 'disabled' }}
                    </span>
                    @if (u.must_change_password) {
                      <span class="pill warn-text">phải đổi MK</span>
                    }
                    @if (isLocked(u)) {
                      <span class="pill danger">bị khóa</span>
                    }
                  </td>
                  <td class="tabular-nums">{{ u.last_login_at ? (u.last_login_at | date: 'dd/MM/yyyy HH:mm') : '—' }}</td>
                  <td>
                    <div class="fill-controls">
                      <button type="button" class="btn btn-sm" [disabled]="busyUserId === u.id || isSelf(u)" (click)="toggleActive(u)">
                        {{ u.is_active ? 'Vô hiệu hóa' : 'Kích hoạt' }}
                      </button>
                      <button type="button" class="btn btn-sm" [disabled]="busyUserId === u.id" (click)="toggleMustChange(u)">
                        {{ u.must_change_password ? 'Bỏ ép đổi MK' : 'Ép đổi MK' }}
                      </button>
                      @if (isLocked(u) || u.failed_login_count > 0) {
                        <button type="button" class="btn btn-sm" [disabled]="busyUserId === u.id" (click)="unlock(u)">Mở khóa</button>
                      }
                      @if (!isSelf(u)) {
                        <input
                          type="password"
                          class="input-sm"
                          autocomplete="new-password"
                          placeholder="Mật khẩu mới"
                          [attr.aria-label]="'Mật khẩu mới cho ' + u.username"
                          [(ngModel)]="resetPasswords[u.id]"
                        />
                        <button type="button" class="btn btn-sm btn-danger" [disabled]="busyUserId === u.id" (click)="resetPassword(u)">
                          Reset MK
                        </button>
                      }
                    </div>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </section>
  `,
})
export class UserAdminComponent implements OnInit {
  private readonly api = inject(UserAdminApiService);
  private readonly auth = inject(AuthService);

  readonly roles = USER_ROLES;
  readonly roleLabels = ROLE_LABELS;
  readonly minLength = MIN_PASSWORD_LENGTH;

  users: AuthUser[] = [];
  isLoading = false;
  isCreating = false;
  busyUserId: string | null = null;
  message: { kind: 'info' | 'error' | 'success'; text: string } | null = null;

  newUsername = '';
  newPassword = '';
  newRole: UserRole = 'viewer';
  newMustChange = true;
  newIsActive = true;
  resetPasswords: Record<string, string> = {};

  ngOnInit(): void {
    this.load();
  }

  isSelf(user: AuthUser): boolean {
    return user.id === this.auth.user()?.id;
  }

  isLocked(user: AuthUser): boolean {
    return isUserLocked(user);
  }

  load(): void {
    this.isLoading = true;
    this.api.listUsers().subscribe({
      next: (res) => {
        this.users = res.items;
        this.isLoading = false;
      },
      error: (err: unknown) => {
        this.isLoading = false;
        this.fail(err, 'Không tải được danh sách người dùng');
      },
    });
  }

  createUser(): void {
    const validationError = validateNewUser(this.newUsername, this.newPassword);
    if (validationError) {
      this.message = { kind: 'error', text: validationError };
      return;
    }
    const payload: UserCreateRequest = {
      username: normalizeUsername(this.newUsername),
      password: this.newPassword,
      role: this.newRole,
      is_active: this.newIsActive,
      must_change_password: this.newMustChange,
    };
    this.isCreating = true;
    this.api.createUser(payload).subscribe({
      next: (created) => {
        this.isCreating = false;
        this.newUsername = '';
        this.newPassword = '';
        this.users = [...this.users, created];
        this.message = { kind: 'success', text: `Đã tạo người dùng ${created.username} (${created.role}).` };
      },
      error: (err: unknown) => {
        this.isCreating = false;
        this.newPassword = '';
        this.fail(err, 'Không thể tạo người dùng');
      },
    });
  }

  changeRole(user: AuthUser, role: UserRole): void {
    if (role === user.role) {
      return;
    }
    this.patch(user, { role }, `Đã đổi vai trò của ${user.username} thành ${role}.`);
  }

  toggleActive(user: AuthUser): void {
    this.patch(
      user,
      { is_active: !user.is_active },
      user.is_active ? `Đã vô hiệu hóa ${user.username}.` : `Đã kích hoạt ${user.username}.`
    );
  }

  toggleMustChange(user: AuthUser): void {
    this.patch(user, { must_change_password: !user.must_change_password }, `Đã cập nhật yêu cầu đổi mật khẩu của ${user.username}.`);
  }

  unlock(user: AuthUser): void {
    this.patch(user, { unlock: true }, `Đã mở khóa đăng nhập cho ${user.username}.`);
  }

  resetPassword(user: AuthUser): void {
    const newPassword = this.resetPasswords[user.id] ?? '';
    const validationError = validatePasswordLength(newPassword);
    if (validationError) {
      this.message = { kind: 'error', text: validationError };
      return;
    }
    this.resetPasswords[user.id] = '';
    this.patch(user, { new_password: newPassword }, `Đã reset mật khẩu của ${user.username}; người dùng phải đổi mật khẩu khi đăng nhập lại.`);
  }

  private patch(user: AuthUser, body: Parameters<UserAdminApiService['updateUser']>[1], successText: string): void {
    this.busyUserId = user.id;
    this.api.updateUser(user.id, body).subscribe({
      next: (updated) => {
        this.busyUserId = null;
        this.users = this.users.map((u) => (u.id === updated.id ? updated : u));
        this.message = { kind: 'success', text: successText };
      },
      error: (err: unknown) => {
        this.busyUserId = null;
        this.load();
        this.fail(err, 'Không thể cập nhật người dùng');
      },
    });
  }

  private fail(err: unknown, fallback: string): void {
    this.message = { kind: 'error', text: describeHttpError(err, fallback) };
  }
}
