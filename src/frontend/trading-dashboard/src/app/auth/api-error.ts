// Ngày tạo: 2026-11-17
// Mục đích: Chuyển HttpErrorResponse thành thông điệp tiếng Việt rõ ràng (đặc biệt 401/403/423/0).
// Lý do: Backend trả `{error: {message}}` (handler chuẩn) hoặc `{detail}`; 422 có thêm `details` cần rút gọn.

import { HttpErrorResponse } from '@angular/common/http';

export function extractServerCode(err: HttpErrorResponse): string | null {
  const body: unknown = err.error;
  if (!body || typeof body !== 'object') {
    return null;
  }
  const nested = (body as Record<string, unknown>)['error'];
  if (!nested || typeof nested !== 'object') {
    return null;
  }
  const code = (nested as Record<string, unknown>)['code'];
  return typeof code === 'string' && code ? code : null;
}

export function extractServerMessage(err: HttpErrorResponse): string | null {
  const body: unknown = err.error;
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    const nested = record['error'];
    if (nested && typeof nested === 'object') {
      const message = (nested as Record<string, unknown>)['message'];
      if (typeof message === 'string' && message) {
        return message;
      }
    }
    const detail = record['detail'];
    if (typeof detail === 'string' && detail) {
      return detail;
    }
  }
  return null;
}

export function describeHttpError(err: unknown, fallback: string): string {
  if (!(err instanceof HttpErrorResponse)) {
    return fallback;
  }
  const serverMessage = extractServerMessage(err);
  switch (err.status) {
    case 0:
      return `${fallback}: không kết nối được tới máy chủ.`;
    case 401:
      return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.';
    case 403:
      return `${fallback}: ${serverMessage ?? 'Vai trò hiện tại không có quyền thực hiện thao tác này.'}`;
    case 423:
      return serverMessage ?? 'Tài khoản đang bị khóa tạm thời. Vui lòng thử lại sau.';
    default:
      return `${fallback}: ${serverMessage ?? err.message}`;
  }
}
