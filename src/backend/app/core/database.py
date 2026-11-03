# Ngày tạo: 2026-11-03
# Mục đích: Thiết lập SQLAlchemy 2.0 Engine, SessionLocal, DeclarativeBase và danh sách 6 PostgreSQL schemas.

from typing import Generator

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# Danh sách 6 schemas logic bắt buộc theo thiết kế Mục 6
POSTGRES_SCHEMAS = (
    "market",
    "analysis",
    "strategy",
    "trading",
    "portfolio",
    "system",
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Lớp cơ sở cho toàn bộ các bảng SQLAlchemy 2.0 trong 6 schemas."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_database_uri,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db_session() -> Generator[Session, None, None]:
    """Dependency cung cấp database session cho FastAPI endpoints."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> tuple[bool, str]:
    """Kiểm tra kết nối thực tế tới PostgreSQL phục vụ health check."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        return False, f"disconnected ({type(exc).__name__})"
