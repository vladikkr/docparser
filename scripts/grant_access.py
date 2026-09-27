"""Issue API access by hand after a client paid by card transfer.

There is no payment gateway: money arrives as a transfer, and this script is
what converts that into a working account. It creates the user if needed, sets
the tier that was paid for, and prints a key that is shown exactly once.

    python scripts/grant_access.py client@example.com --tier pro
    python scripts/grant_access.py client@example.com --tier pro --name "ООО Ромашка"
    python scripts/grant_access.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# The operator wants the key, not the SQL behind it. This has to happen before
# the app is imported, because the engine picks up echo at import time.
os.environ.setdefault("DEBUG", "false")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

import secrets  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.security import generate_api_key, get_password_hash  # noqa: E402
from app.database import async_session_maker, init_db  # noqa: E402
from app.models import APIKey, User, UserTier  # noqa: E402

TIER_LIMITS = {
    UserTier.FREE: 50,
    UserTier.STARTER: 1_000,
    UserTier.PRO: 10_000,
    UserTier.BUSINESS: 50_000,
}


async def list_users() -> None:
    await init_db()
    async with async_session_maker() as session:
        rows = (
            await session.execute(select(User).order_by(User.created_at))
        ).scalars().all()
    if not rows:
        print("Пользователей пока нет.")
        return
    print(f"{'email':<34}{'tier':<10}{'keys':<7}{'created'}")
    print("-" * 62)
    async with async_session_maker() as session:
        for user in rows:
            keys = (
                await session.execute(
                    select(APIKey).where(APIKey.user_id == user.id, APIKey.is_active.is_(True))
                )
            ).scalars().all()
            created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "-"
            tier = user.tier.value if user.tier else "free"
            print(f"{user.email:<34}{tier:<10}{len(keys):<7}{created}")


async def grant(email: str, tier_name: str, name: str | None) -> None:
    tier = UserTier(tier_name.lower())
    password = secrets.token_urlsafe(12)

    # A fresh database has no schema yet.
    await init_db()

    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if user is None:
            user = User(
                email=email,
                hashed_password=get_password_hash(password),
                full_name=name,
                tier=tier,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            created = True
        else:
            user.tier = tier
            if name:
                user.full_name = name
            user.hashed_password = get_password_hash(password)
            created = False

        raw_key, prefix, key_hash = generate_api_key()
        key = APIKey(user_id=user.id, key_hash=key_hash, key_prefix=prefix, name="issued manually")
        session.add(key)
        await session.commit()

    print()
    print("=" * 62)
    print(f"  Тариф      : {tier.value}  ({TIER_LIMITS[tier]} документов/мес)")
    print(f"  Email      : {email}")
    print(f"  Пароль     : {password}")
    print(f"  API-ключ   : {raw_key}")
    print("=" * 62)
    print()
    if created:
        print("Новый пользователь. Отправьте ему пароль и ключ.")
    else:
        print("Пользователь уже существовал: тариф обновлён, пароль сброшен.")
    print("Ключ показывается один раз и не восстанавливается — сохраните его сейчас.")
    print()
    print("Проверка ключа:")
    print(f'  curl -H "X-API-Key: {raw_key}" http://localhost:8000/api/v1/auth/me')


async def revoke(email: str) -> None:
    await init_db()
    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            print("Пользователь не найден.")
            return
        keys = (
            await session.execute(
                select(APIKey).where(APIKey.user_id == user.id, APIKey.is_active.is_(True))
            )
        ).scalars().all()
        for key in keys:
            key.is_active = False
        user.is_active = False
        await session.commit()
    print(f"Отозвано ключей: {len(keys)}. Пользователь {email} заблокирован.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Выдать доступ после оплаты переводом")
    parser.add_argument("email", nargs="?", help="email клиента")
    parser.add_argument("--tier", default="pro", choices=[t.value for t in UserTier])
    parser.add_argument("--name", default=None, help="название компании или имя")
    parser.add_argument("--list", action="store_true", help="показать всех клиентов")
    parser.add_argument("--revoke", action="store_true", help="отозвать доступ")
    args = parser.parse_args()

    if args.list:
        return asyncio.run(list_users())
    if not args.email:
        parser.error("нужен email или --list")
    if args.revoke:
        return asyncio.run(revoke(args.email))

    asyncio.run(grant(args.email, args.tier, args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
