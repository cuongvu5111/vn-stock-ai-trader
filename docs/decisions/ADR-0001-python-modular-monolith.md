# ADR-0001: Chuyển sang Python Modular Monolith trong Monorepo

- **Ngày:** 2026-11-03
- **Trạng thái:** Đã phê duyệt (Approved)

## Bối cảnh
Bản kế hoạch ban đầu sử dụng kết hợp ASP.NET Core 8 + Python 3.12 FastAPI + Angular. Với quy mô Personal MVP do 1 người vận hành local qua Docker Compose, việc duy trì 2 ngôn ngữ Backend làm tăng độ phức tạp khi đồng bộ DTO, ORM migration và giao tiếp HTTP nội bộ.

## Quyết định
Sử dụng **Python 3.12 + FastAPI theo kiến trúc Modular Monolith** cho toàn bộ Backend (gồm cả Core Trading, Risk Management, Paper Broker và Analysis Engine), kết hợp **SQLAlchemy 2.0 + Alembic + PostgreSQL 16** và **Angular Dashboard** trong cùng một **Monorepo**.

## Hệ quả & Biện pháp bảo vệ
- Bắt buộc dùng `decimal.Decimal` (Python) và `NUMERIC` (PostgreSQL) cho mọi phép tính tiền/giá.
- Cô lập hoàn toàn module `app.ai` khỏi `app.trading` và `app.portfolio`.
- Giữ nguyên 100% quy tắc Risk Management, Human Approval và Paper Broker.
