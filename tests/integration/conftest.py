"""Fixtures for the API integration tests.

These tests exercise the real FastAPI app through an in-memory SQLite database.
Every test gets a fresh schema, so nothing leaks between them.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio

# Point the app at a throwaway database before anything imports it.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_integration.db")
os.environ.setdefault("CELERY_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-integration-tests")
os.environ.setdefault("REDIS_URL", "")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.security import generate_api_key, get_password_hash  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import APIKey, User, UserTier  # noqa: E402
from app.utils.helpers import utcnow  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_integration.db"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()
    # The file is not deleted: the app keeps its own engine open on the same
    # path, and Windows refuses to remove a file that is still in use. The
    # next run drops and recreates the schema anyway.


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine, db_session) -> AsyncClient:
    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="test@docparser.ru",
        hashed_password=get_password_hash("testpassword123"),
        full_name="Test User",
        tier=UserTier.PRO,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "testpassword123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest_asyncio.fixture
async def test_api_key(db_session: AsyncSession, test_user: User) -> str:
    raw, prefix, key_hash = generate_api_key()
    db_session.add(
        APIKey(
            id=uuid.uuid4(),
            user_id=test_user.id,
            key_hash=key_hash,
            key_prefix=prefix,
            name="Test Key",
            is_active=True,
            expires_at=utcnow() + timedelta(days=30),
        )
    )
    await db_session.commit()
    return raw


@pytest.fixture
def api_key_headers(test_api_key: str) -> dict:
    return {"X-API-Key": test_api_key}


@pytest.fixture
def sample_receipt_bytes() -> bytes:
    """A tiny valid JPEG so upload validation passes."""
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (120, 200), (245, 243, 238)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_celery_task():
    """Parse inline and wait for it, so /parse can report a finished document.

    Celery is disabled in tests, so the queue is never reached; the point of
    this fixture is to make the background work deterministic.
    """
    with patch("app.services.dispatcher.celery_available", return_value=False):
        yield
