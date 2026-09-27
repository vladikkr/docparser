"""Startup bootstrap for containerised hosts (Hugging Face Spaces, Render, Docker).

Creates tables when they are missing and never blocks the process: a database
that is unreachable must not stop the API from booting and serving /health.
"""

import asyncio
import pathlib
import sys

# Running this file directly puts scripts/ on sys.path, not the repo root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import text


async def _main() -> int:
    try:
        from app.database import DATABASE_URL, engine, init_db

        driver = DATABASE_URL.split("://", 1)[0]
        print(f"[bootstrap] database driver: {driver}")

        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("[bootstrap] database reachable")

        await init_db()
        print("[bootstrap] schema ready")
        return 0
    except Exception as exc:
        print(f"[bootstrap] WARNING: {type(exc).__name__}: {exc}")
        print("[bootstrap] continuing - /health will report database status")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
