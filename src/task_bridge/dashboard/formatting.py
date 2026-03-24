from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TimestampRenderData:
    raw_iso: str | None
    display: str


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


def canonical_timestamp_iso(value: str) -> str | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def format_timestamp_for_client(value: str, *, fallback: str) -> TimestampRenderData:
    if not value:
        return TimestampRenderData(raw_iso=None, display=fallback)
    raw_iso = canonical_timestamp_iso(value)
    if raw_iso is None:
        return TimestampRenderData(raw_iso=None, display=value)
    parsed = parse_timestamp(raw_iso)
    if parsed is None:
        return TimestampRenderData(raw_iso=raw_iso, display=fallback)
    return TimestampRenderData(raw_iso=raw_iso, display=parsed.strftime("%Y-%m-%d %H:%M"))


def format_timestamp(value: str, *, fallback: str) -> str:
    formatted = format_timestamp_for_client(value, fallback=fallback)
    if formatted.raw_iso is None:
        return formatted.display
    return f"{formatted.display} UTC"


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
