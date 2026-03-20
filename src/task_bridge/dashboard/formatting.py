from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def normalize_display_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" not in normalized and "\\r" not in normalized:
        return normalized
    return normalized.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


def optional_display_text(value: object) -> str | None:
    text = optional_text(value)
    return normalize_display_text(text) if text is not None else None


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def format_timestamp(value: str, *, fallback: str) -> str:
    if not value:
        return fallback
    parsed = parse_timestamp(value)
    if parsed is None:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def file_timestamp_iso(path: Path) -> str | None:
    try:
        timestamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def is_overdue(value: str | None, now_value: datetime | None) -> bool:
    if not value or now_value is None:
        return False
    due_at = parse_timestamp(value)
    return bool(due_at and due_at <= now_value)
