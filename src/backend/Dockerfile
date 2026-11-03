# Ngày tạo: 2026-11-03
# Mục đích: Dockerfile cho Python FastAPI Backend (Modular Monolith).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src/backend

WORKDIR /app/src/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY src/backend/requirements.txt /app/src/backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/backend /app/src/backend
COPY database /app/database

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python /app/database/seeds/seed_initial.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
