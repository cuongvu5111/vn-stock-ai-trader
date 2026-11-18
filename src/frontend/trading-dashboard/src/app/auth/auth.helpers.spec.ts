// Ngày tạo: 2026-11-17
// Mục đích: Unit test ma trận quyền UI và helper thông báo lỗi.

import { HttpErrorResponse } from '@angular/common/http';
import { describeHttpError } from './api-error';
import { capabilitiesFor } from './auth.permissions';
import { validateNewPassword } from './change-password.component';
import { isUserLocked, normalizeUsername, validateNewUser } from './user-admin.component';
import { makeUser } from '../testing/auth-fixtures';

describe('capabilitiesFor', () => {
  it('viewer chỉ xem', () => {
    const caps = capabilitiesFor('viewer');
    expect(Object.values(caps).every((v) => v === false)).toBeTrue();
  });

  it('trader thao tác nghiệp vụ và bật (không tắt) kill switch', () => {
    const caps = capabilitiesFor('trader');
    expect(caps.canOperate).toBeTrue();
    expect(caps.canActivateKillSwitch).toBeTrue();
    expect(caps.canDeactivateKillSwitch).toBeFalse();
    expect(caps.canEditRiskConfig).toBeFalse();
    expect(caps.canSyncRealData).toBeFalse();
    expect(caps.canCreateStock).toBeFalse();
    expect(caps.canManageUsers).toBeFalse();
  });

  it('admin có toàn quyền', () => {
    expect(Object.values(capabilitiesFor('admin')).every((v) => v === true)).toBeTrue();
  });

  it('chưa đăng nhập không có quyền nào', () => {
    expect(Object.values(capabilitiesFor(null)).every((v) => v === false)).toBeTrue();
  });
});

describe('describeHttpError', () => {
  it('401 yêu cầu đăng nhập lại', () => {
    const err = new HttpErrorResponse({ status: 401 });
    expect(describeHttpError(err, 'Lỗi')).toContain('đăng nhập lại');
  });

  it('403 dùng thông điệp của backend', () => {
    const err = new HttpErrorResponse({ status: 403, error: { error: { message: 'Không đủ quyền' } } });
    expect(describeHttpError(err, 'Không thể duyệt')).toBe('Không thể duyệt: Không đủ quyền');
  });

  it('403 có thông điệp mặc định khi thiếu body', () => {
    const err = new HttpErrorResponse({ status: 403 });
    expect(describeHttpError(err, 'Lỗi')).toContain('không có quyền');
  });

  it('đọc được dạng {detail}', () => {
    const err = new HttpErrorResponse({ status: 400, error: { detail: 'chi tiết' } });
    expect(describeHttpError(err, 'Lỗi')).toBe('Lỗi: chi tiết');
  });

  it('status 0 báo mất kết nối và lỗi không phải HTTP dùng fallback', () => {
    expect(describeHttpError(new HttpErrorResponse({ status: 0 }), 'Lỗi')).toContain('kết nối');
    expect(describeHttpError(new Error('x'), 'Fallback')).toBe('Fallback');
  });
});

describe('validateNewPassword', () => {
  it('từ chối mật khẩu ngắn, trùng mật khẩu cũ hoặc xác nhận lệch', () => {
    expect(validateNewPassword('old-password-12', 'short', 'short')).toContain('ít nhất');
    expect(validateNewPassword('old-password-12', 'old-password-12', 'old-password-12')).toContain('khác');
    expect(validateNewPassword('old-password-12', 'new-password-123', 'different-123456')).toContain('không khớp');
    expect(validateNewPassword('', 'new-password-123', 'new-password-123')).toContain('hiện tại');
  });

  it('chấp nhận mật khẩu hợp lệ', () => {
    expect(validateNewPassword('old-password-12', 'new-password-123', 'new-password-123')).toBeNull();
  });
});

describe('user admin helpers', () => {
  it('chuẩn hóa và kiểm tra username/password theo contract backend', () => {
    expect(normalizeUsername('  Trader.One ')).toBe('trader.one');
    expect(validateNewUser('Trader.One', 'long-enough-pass')).toBeNull();
    expect(validateNewUser('ab', 'long-enough-pass')).toContain('Username');
    expect(validateNewUser('bad name', 'long-enough-pass')).toContain('Username');
    expect(validateNewUser('good-user', 'short')).toContain('Mật khẩu');
  });

  it('isUserLocked chỉ đúng khi locked_until ở tương lai', () => {
    const now = Date.parse('2026-11-17T00:00:00Z');
    expect(isUserLocked(makeUser({ locked_until: '2026-11-17T00:10:00Z' }), now)).toBeTrue();
    expect(isUserLocked(makeUser({ locked_until: '2026-11-16T23:00:00Z' }), now)).toBeFalse();
    expect(isUserLocked(makeUser(), now)).toBeFalse();
  });
});
