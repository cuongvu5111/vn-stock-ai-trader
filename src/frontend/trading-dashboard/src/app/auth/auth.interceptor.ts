// Ngày tạo: 2026-11-17
// Mục đích: Functional HTTP interceptor gắn `Authorization: Bearer` cho request `/api/*` và xử lý 401 tập trung.
// Lý do: Không gắn token cho URL ngoài `/api` (tránh rò rỉ sang origin khác) và không gắn cho endpoint login.

import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { extractServerCode } from './api-error';
import { AUTH_API_BASE, AuthService } from './auth.service';

export function isApiRequestUrl(url: string): boolean {
  return url === '/api' || url.startsWith('/api/');
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isApiRequestUrl(req.url) || req.url === `${AUTH_API_BASE}/login`) {
    return next(req);
  }

  const auth = inject(AuthService);
  const token = auth.accessToken;
  if (!token) {
    return next(req);
  }

  const authorizedReq = req.headers.has('Authorization')
    ? req
    : req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });

  return next(authorizedReq).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401) {
        auth.handleUnauthorized(token);
      } else if (
        err instanceof HttpErrorResponse &&
        err.status === 403 &&
        extractServerCode(err) === 'PASSWORD_CHANGE_REQUIRED'
      ) {
        auth.handlePasswordChangeRequired(token);
      }
      return throwError(() => err);
    })
  );
};
