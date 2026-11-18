# Ngày tạo: 2026-11-03
# Cập nhật: 2026-11-17 — chạy bằng user không phải root, exec uvicorn để nhận SIGTERM (tắt scheduler sạch),
#   bỏ curl (healthcheck dùng Python có sẵn trong image).
# Mục đích: Dockerfile cho Python FastAPI Backend (Modular Monolith). Build context là thư mục gốc repo.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src/backend \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# UID/GID cố định để dễ phân quyền volume nếu cần; user không có shell đăng nhập và không có home ghi được.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/src/backend

COPY src/backend/requirements.txt /app/src/backend/requirements.txt
RUN pip install -r requirements.txt

COPY src/backend /app/src/backend
COPY database /app/database

# Mã nguồn thuộc root (chỉ đọc với user app) để tiến trình bị chiếm quyền không sửa được code.
USER 10001:10001

EXPOSE 8000

# Migration + seed idempotent chạy trước khi nhận request; `exec` để uvicorn là PID 1 và nhận tín hiệu dừng từ Docker.
CMD ["sh", "-c", "alembic upgrade head && python /app/database/seeds/seed_initial.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-server-header"]
