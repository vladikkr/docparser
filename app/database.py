"""Database engine setup.

Providers hand out PostgreSQL URLs in several shapes (`postgresql://`,
`postgres://`, `postgresql+psycopg://`, ...). SQLAlchemy picks the driver from
that scheme, so a bare `postgresql://` would demand `psycopg`, which we do not
ship. We always use asyncpg, so normalise the URL before creating the engine.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

DRIVER = "postgresql+asyncpg"

_SCHEME_REWRITES = (
    ("postgresql+psycopg://", f"{DRIVER}://"),
    ("postgresql+psycopg2://", f"{DRIVER}://"),
    ("postgresql+pg8000://", f"{DRIVER}://"),
    ("postgres://", f"{DRIVER}://"),
    ("postgresql://", f"{DRIVER}://"),
)


def normalize_database_url(url: str) -> str:
    """Force the asyncpg driver for any PostgreSQL-style URL."""
    text = str(url)
    for prefix, replacement in _SCHEME_REWRITES:
        if text.startswith(prefix):
            return replacement + text[len(prefix) :]
    return text


DATABASE_URL = normalize_database_url(settings.DATABASE_URL)

# SQLite ignores pool sizing
_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
