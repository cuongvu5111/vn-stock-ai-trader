// Ngày tạo: 2026-11-03
// Mục đích: Điểm khởi chạy ứng dụng Angular Standalone Dashboard.
// Lý do: authInterceptor đăng ký ở provideHttpClient để mọi request /api đều gắn Bearer và xử lý 401 tập trung.

import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { AppComponent } from './app/app.component';
import { authInterceptor } from './app/auth/auth.interceptor';

bootstrapApplication(AppComponent, {
  providers: [provideHttpClient(withInterceptors([authInterceptor]))],
}).catch((err) => console.error(err));