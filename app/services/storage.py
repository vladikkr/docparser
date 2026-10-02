"""Local disk storage for uploaded documents.

The API used to record a `storage_path` on the document and then never write the
bytes anywhere, so the parse task was handed an empty buffer and could not do
its job. Files now live on local disk under `UPLOAD_DIR`, which is enough for a
single-instance deployment. Swapping in object storage later means changing
only this module.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings

logger = logging.getLogger(__name__)

_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".pdf"}


class StorageError(RuntimeError):
    """Raised when a document cannot be written or read back."""


def _root() -> Path:
    return Path(settings.UPLOAD_DIR).expanduser()


def _resolve(storage_path: str) -> Path:
    """Turn a stored relative path into an absolute one, refusing escapes."""
    root = _root().resolve()
    target = (root / storage_path).resolve()
    if not str(target).startswith(str(root)):
        raise StorageError(f"Refusing to access outside the upload directory: {storage_path}")
    return target


def _suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in _ALLOWED_SUFFIXES else ".bin"


def build_path(user_id: str, filename: str) -> str:
    """A collision-free, date-sharded relative path."""
    day = datetime.now(UTC).strftime("%Y/%m/%d")
    unique = uuid4().hex[:8]
    safe_name = Path(filename).name
    return f"users/{user_id}/{day}/{unique}{_suffix(safe_name)}"


def save(file_bytes: bytes, user_id: str, filename: str) -> str:
    """Write the upload and return the path to store on the document."""
    relative = build_path(user_id, filename)
    target = _resolve(relative)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
    except OSError as exc:
        raise StorageError(f"Could not store the upload: {exc}") from exc
    return relative


def read(storage_path: str) -> bytes:
    """Read a stored document back for parsing."""
    target = _resolve(storage_path)
    if not target.is_file():
        raise StorageError(f"Document file is missing: {storage_path}")
    try:
        return target.read_bytes()
    except OSError as exc:
        raise StorageError(f"Could not read the stored document: {exc}") from exc


def delete(storage_path: str) -> None:
    """Remove a stored document, ignoring an already absent file."""
    try:
        target = _resolve(storage_path)
    except StorageError:
        logger.warning("refusing_delete_outside_upload_dir", path=storage_path)
        return
    if target.is_file():
        try:
            target.unlink()
        except OSError as exc:
            logger.warning("document_delete_failed", path=storage_path, error=str(exc))


def delete_user_prefix(user_id: str) -> None:
    """Remove every document belonging to a user."""
    root = _root().resolve()
    target = (root / "users" / str(user_id)).resolve()
    if target.is_dir() and str(target).startswith(str(root)):
        shutil.rmtree(target, ignore_errors=True)


def total_bytes() -> int:
    """Disk usage of the upload directory, reported by the health endpoint."""
    root = _root()
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
