"""File helpers. `python-magic` and Pillow are optional."""

import io
import os
import uuid
from datetime import datetime

ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/tiff": [".tiff", ".tif"],
    "image/webp": [".webp"],
}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def _sniff_mime(file_bytes: bytes) -> str | None:
    """Best-effort content sniffing. Returns None when python-magic is absent."""
    try:
        import magic

        return magic.from_buffer(file_bytes, mime=True)
    except Exception:
        return None


def validate_file_type(file_bytes: bytes, filename: str) -> str | None:
    """Validate the uploaded file. Returns an error message, or None when valid."""
    sniffed = _sniff_mime(file_bytes)
    if sniffed is not None and sniffed not in ALLOWED_MIME_TYPES:
        return f"Unsupported file type: {sniffed}"

    allowed_exts = {ext for exts in ALLOWED_MIME_TYPES.values() for ext in exts}
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext and ext not in allowed_exts:
        return f"Unsupported file extension: {ext}"
    return None


def validate_file_size(file_bytes: bytes, max_size: int = MAX_FILE_SIZE) -> str | None:
    """Validate file size"""
    if len(file_bytes) > max_size:
        return f"File too large: {len(file_bytes)} bytes (max {max_size})"
    return None


def get_image_info(file_bytes: bytes) -> dict:
    """Get image dimensions and format"""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(file_bytes))
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
        }
    except Exception:
        return {}


def save_upload_file(file_bytes: bytes, path: str) -> None:
    """Save uploaded file to local path"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(file_bytes)


def generate_storage_path(user_id: str, filename: str) -> str:
    """Generate storage path for uploaded file"""
    date_path = datetime.utcnow().strftime("%Y/%m/%d")
    unique_id = uuid.uuid4().hex[:8]
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    return f"users/{user_id}/{date_path}/{unique_id}.{ext}"
