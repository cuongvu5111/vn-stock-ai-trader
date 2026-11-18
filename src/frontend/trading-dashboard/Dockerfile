# Ngày tạo: 2026-11-03
# Cập nhật: 2026-11-17 — nginx không root (nginx-unprivileged, cổng 8080), cấu hình/ header tách file, có healthcheck.
# Mục đích: Multi-stage Dockerfile cho Angular Trading Dashboard. Build context là thư mục gốc repo.

FROM node:22-alpine AS build
WORKDIR /app

COPY src/frontend/trading-dashboard/package.json src/frontend/trading-dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY src/frontend/trading-dashboard/ ./
RUN npm run build

# Image chính thức nginxinc/nginx-unprivileged chạy bằng user `nginx` (uid 101), pid/temp nằm trong /tmp; pin phiên bản cụ thể.
FROM nginxinc/nginx-unprivileged:1.27.5-alpine
COPY src/frontend/trading-dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY src/frontend/trading-dashboard/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY src/frontend/trading-dashboard/nginx/proxy-api.conf /etc/nginx/snippets/proxy-api.conf
COPY --from=build /app/dist/trading-dashboard/browser /usr/share/nginx/html

EXPOSE 8080

# wget (busybox) có sẵn trong image alpine; dùng 127.0.0.1 để không phụ thuộc phân giải IPv6 của localhost.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/health || exit 1
