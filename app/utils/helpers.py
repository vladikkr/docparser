import hashlib
import secrets
from datetime import datetime, timedelta


def generate_idempotency_key(prefix: str = "") -> str:
    """Generate idempotency key for Stripe operations"""
    random_part = secrets.token_hex(16)
    return f"{prefix}{random_part}" if prefix else random_part


def hash_content(content: bytes) -> str:
    """Generate SHA256 hash of content"""
    return hashlib.sha256(content).hexdigest()


def format_currency(amount: int, currency: str = "RUB") -> str:
    """Format amount in cents to string"""
    if currency == "RUB":
        return f"{amount / 100:,.2f} ₽"
    return f"{amount / 100:,.2f} {currency}"


def parse_period(period_str: str) -> tuple[datetime, datetime]:
    """Parse period string like '2024-01' to start/end dates"""
    year, month = map(int, period_str.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(microseconds=1)
    return start, end


def truncate_string(s: str, max_length: int = 100) -> str:
    """Truncate string with ellipsis"""
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    import re
    # Remove path traversal attempts
    filename = re.sub(r"[\\/:*?\"<>|]", "_", filename)
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        if ext:
            max_name = 255 - len(ext) - 1  # -1 for the dot
        else:
            max_name = 255
        filename = name[:max_name] + ("." + ext if ext else "")
    return filename
