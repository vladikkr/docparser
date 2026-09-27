"""End-to-end: POST a real receipt photo to the API and check the parsed data.

This is the path a hosted client uses. It failed silently before, because the
upload recorded a path but never wrote the bytes.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_e2e.db")
os.environ.setdefault("CELERY_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret")

import asyncio  # noqa: E402
import sqlite3  # noqa: E402

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.security import generate_api_key, get_password_hash  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import APIKey, User, UserTier  # noqa: E402
from app.services import storage  # noqa: E402

RECEIPT = pathlib.Path(r"C:\Users\vladk\Downloads\1.png.jpg")


async def main() -> int:
    if not RECEIPT.exists():
        print(f"receipt not found: {RECEIPT}")
        return 2

    storage_root = pathlib.Path("./storage")
    engine = create_async_engine("sqlite+aiosqlite:///./test_e2e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from uuid import uuid4

    async with maker() as session:
        user = User(
            id=uuid4(),
            email="e2e@docparser-test.com",
            hashed_password=get_password_hash("pw12345678"),
            tier=UserTier.PRO,
        )
        raw_key, prefix, key_hash = generate_api_key()
        session.add(user)
        session.add(
            APIKey(id=uuid4(), user_id=user.id, key_hash=key_hash, key_prefix=prefix, name="e2e", is_active=True)
        )
        await session.commit()

    async def override():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_db] = override
    payload = RECEIPT.read_bytes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://e2e") as client:
        # 1. Synchronous parse: the parsed data must come back in the response.
        response = await client.post(
            "/api/v1/documents/parse",
            headers={"X-API-Key": raw_key},
            files={"file": ("receipt.jpg", payload, "image/jpeg")},
            data={"document_type": "receipt_kkt"},
        )
        print(f"POST /parse -> {response.status_code}")
        if response.status_code != 200:
            print(response.text[:400])
            return 1
        body = response.json()
        print(f"  status        : {body['status']}")
        print(f"  processing_ms : {body['processing_time_ms']}")
        data = body.get("parsed_data") or {}
        print(f"  total_sum     : {data.get('total_sum')}")
        print(f"  unp           : {data.get('unp')}")
        print(f"  ui            : {data.get('ui')}")
        print(f"  trustworthy   : {data.get('trustworthy')}")

        # 2. Asynchronous upload uses a JWT, not an API key.
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "e2e@docparser-test.com", "password": "pw12345678"},
        )
        if login.status_code != 200:
            print(f"login -> {login.status_code}: {login.text[:300]}")
            return 1
        bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
        upload = await client.post(
            "/api/v1/documents/upload",
            headers=bearer,
            files={"file": ("receipt.jpg", payload, "image/jpeg")},
            data={"document_type": "receipt_kkt"},
        )
        print(f"POST /upload -> {upload.status_code}")
        if upload.status_code != 201:
            print(upload.text[:400])
            return 1
        document = upload.json()
        # OCR on a phone photo takes several seconds, so poll rather than guess.
        state: dict = {}
        for _ in range(20):
            await asyncio.sleep(2)
            detail = await client.get(f"/api/v1/documents/{document['id']}", headers=bearer)
            if detail.status_code == 200:
                state = detail.json()
                if state.get("status") in ("completed", "failed"):
                    break
        print(f"  final status  : {state.get('status')}")
        parsed = state.get("parsed_data") or {}
        print(f"  parsed total  : {parsed.get('total_sum')} unp={parsed.get('unp')}")
        print(f"  error         : {state.get('error_message')}")
        async_status = state.get("status")

    app.dependency_overrides.clear()

    # The response model hides storage_path, so confirm it straight from disk.
    with sqlite3.connect("test_e2e.db") as conn:
        rows = list(conn.execute("select storage_path, status from documents"))
    stored_paths = [r[0] for r in rows if r[0]]
    on_disk = all((storage_root / p).is_file() for p in stored_paths) and bool(stored_paths)
    sizes_ok = all((storage_root / p).stat().st_size == len(payload) for p in stored_paths)
    print(f"  stored files  : {len(stored_paths)}, all present={on_disk}, sizes match={sizes_ok}")

    await engine.dispose()

    ok = (
        data.get("total_sum") == 20.0
        and data.get("unp") == "790730816"
        and on_disk
        and sizes_ok
        and async_status == "completed"
    )
    print()
    print("E2E:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
