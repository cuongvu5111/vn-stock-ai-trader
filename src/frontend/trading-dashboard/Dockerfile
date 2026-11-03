# Ngày tạo: 2026-11-03
# Mục đích: Multi-stage Dockerfile cho Angular Trading Dashboard.

FROM node:22-alpine AS build
WORKDIR /app

COPY src/frontend/trading-dashboard/package.json ./
RUN npm install --no-audit --no-fund

COPY src/frontend/trading-dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY src/frontend/trading-dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/trading-dashboard/browser /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
