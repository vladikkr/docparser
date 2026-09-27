#!/usr/bin/env python3
"""Seed database with initial data"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.security import get_password_hash
from app.models import User, UserTier


async def seed():
    engine = create_async_engine(str(settings.DATABASE_URL))
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Check if test user exists
        result = await db.execute(select(User).where(User.email == "test@docparser.ru"))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email="test@docparser.ru",
                hashed_password=get_password_hash("testpassword123"),
                full_name="Test User",
                company_name="DocParser Test",
                tier=UserTier.PRO,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"✅ Created test user: {user.email} (id: {user.id})")
        else:
            print(f"ℹ️ Test user already exists: {user.email}")

        # Create API key for test user
        from app.core.security import generate_api_key
        from app.models import APIKey

        result = await db.execute(select(APIKey).where(APIKey.user_id == user.id))
        existing_key = result.scalar_one_or_none()

        if not existing_key:
            full_key, prefix, key_hash = generate_api_key()
            api_key = APIKey(
                user_id=user.id,
                key_hash=key_hash,
                key_prefix=prefix,
                name="Test API Key",
                is_active=True,
            )
            db.add(api_key)
            await db.commit()
            print(f"✅ Created API key: {full_key}")
            print("   Save this key - it won't be shown again!")
        else:
            print("ℹ️ API key already exists for user")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
