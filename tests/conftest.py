import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import generate_api_key, get_password_hash
from app.database import Base, get_db
from app.main import create_app
from app.models import APIKey, User, UserTier

# Test database URL (SQLite in memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestAsyncSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_session():
    """Create test database session with tables"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with overridden DB"""
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create test user"""
    user = User(
        email="test@docparser.ru",
        hashed_password=get_password_hash("testpassword123"),
        full_name="Test User",
        company_name="Test Company",
        tier=UserTier.PRO,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_api_key(db_session: AsyncSession, test_user: User) -> tuple[APIKey, str]:
    """Create test API key and return (key_obj, full_key)"""
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        user_id=test_user.id,
        key_hash=key_hash,
        key_prefix=prefix,
        name="Test API Key",
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key, full_key


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    """Headers with JWT token for test user"""
    from app.core.security import create_access_token
    token = create_access_token({"sub": str(test_user.id), "email": test_user.email})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_key_headers(test_api_key: tuple) -> dict:
    """Headers with API key"""
    _, full_key = test_api_key
    return {"X-API-Key": full_key}


@pytest.fixture
def sample_receipt_bytes() -> bytes:
    """Sample receipt image bytes (1x1 pixel PNG)"""
    # Minimal valid PNG
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c4944415408d763f8ffffffff3f0005fe02fedc1a0000000049454e44ae426082"
    )


@pytest.fixture
def mock_celery_task():
    """Mock Celery task to avoid Redis dependency in tests"""
    with patch("app.tasks.parse_tasks.parse_document_task.delay", new_callable=AsyncMock) as mock:
        mock.return_value = AsyncMock()
        yield mock
