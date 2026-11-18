// Ngày tạo: 2026-11-17
// Mục đích: API client cho quản lý người dùng (chỉ admin, backend vẫn kiểm tra quyền).

import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthUser, UserCreateRequest, UserListResponse, UserUpdateRequest } from './auth.models';
import { AUTH_API_BASE } from './auth.service';

@Injectable({ providedIn: 'root' })
export class UserAdminApiService {
  private readonly http = inject(HttpClient);

  listUsers(): Observable<UserListResponse> {
    return this.http.get<UserListResponse>(`${AUTH_API_BASE}/users`);
  }

  createUser(payload: UserCreateRequest): Observable<AuthUser> {
    return this.http.post<AuthUser>(`${AUTH_API_BASE}/users`, payload);
  }

  updateUser(userId: string, payload: UserUpdateRequest): Observable<AuthUser> {
    return this.http.patch<AuthUser>(`${AUTH_API_BASE}/users/${encodeURIComponent(userId)}`, payload);
  }
}
