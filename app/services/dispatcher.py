"""Task dispatch with graceful degradation.

When Celery is unavailable (e.g. free hosting without a worker), documents are
processed inline in a thread pool so the API stays fully functional.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import structlog

from app.config import settings

logger = structlog.get_logger()

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="inline-parse")


def celery_available() -> bool:
    if not settings.CELERY_ENABLED:
        return False
    try:
        from app.tasks.parse_tasks import parse_document_task

        return parse_document_task is not None
    except Exception:
        return False


def dispatch_parse(document_id: UUID) -> str:
    """Queue a parse job. Returns the mode used: 'celery' or 'inline'."""
    if celery_available():
        try:
            from app.tasks.parse_tasks import parse_document_task

            parse_document_task.delay(str(document_id))
            return "celery"
        except Exception as exc:
            logger.warning("celery_dispatch_failed", error=str(exc), falling_back="inline")

    _executor.submit(_run_parse_sync, str(document_id))
    return "inline"


def _run_parse_sync(document_id: str) -> None:
    """Run the Celery task body in a plain worker thread."""
    try:
        from app.tasks.parse_tasks import _parse_document_async

        asyncio.run(_parse_document_async(document_id))
    except Exception as exc:
        logger.error("inline_parse_failed", document_id=document_id, error=str(exc))


async def parse_now(document_id: UUID) -> dict[str, Any] | None:
    """Parse a document immediately in the current process."""
    from app.tasks.parse_tasks import _parse_document_async

    return await _parse_document_async(str(document_id))
