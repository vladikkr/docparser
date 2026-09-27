import io

import magic
from PIL import Image

ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/tiff": [".tiff", ".tif"],
    "image/webp": [".webp"],
}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def validate_file_type(file_bytes: bytes, filename: str) -> str | None:
    """Validate file type using python-magic"""
    try:
        mime = magic.from_buffer(file_bytes, mime=True)
        if mime not in ALLOWED_MIME_TYPES:
            return f"Unsupported file type: {mime}"

        # Check extension matches
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_MIME_TYPES[mime]:
            return f"File extension {ext} doesn't match content type {mime}"

        return None
    except Exception as e:
        return f"File type validation failed: {e}"


def validate_file_size(file_bytes: bytes, max_size: int = MAX_FILE_SIZE) -> str | None:
    """Validate file size"""
    if len(file_bytes) > max_size:
        return f"File too large: {len(file_bytes)} bytes (max {max_size})"
    return None


def get_image_info(file_bytes: bytes) -> dict:
    """Get image dimensions and format"""
    try:
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
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(file_bytes)


def generate_storage_path(user_id: str, filename: str) -> str:
    """Generate storage path for uploaded file"""
    import uuid
    from datetime import datetime
    date_path = datetime.utcnow().strftime("%Y/%m/%d")
    unique_id = uuid.uuid4().hex[:8]
    ext = filename.split(".")[-1] if "." in filename else "bin"
    return f"users/{user_id}/{date_path}/{unique_id}.{ext}"
