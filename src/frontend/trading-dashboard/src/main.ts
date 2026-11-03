// Ngày tạo: 2026-11-03
// Mục đích: Điểm khởi chạy ứng dụng Angular Standalone Dashboard.

import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient } from '@angular/common/http';
import { AppComponent } from './app/app.component';

bootstrapApplication(AppComponent, {
  providers: [
    provideHttpClient()
  ]
}).catch((err) => console.error(err));
