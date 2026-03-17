from __future__ import annotations

import os
from pathlib import Path

CHAT_ID_KEYS = ("TASK_BRIDGE_USER_CHAT_ID",)


def resolve_user_chat_id(explicit: str | None = None, *, cwd: Path | None = None) -> str | None:
    if explicit is not None and explicit.strip():
        return explicit.strip()

    for key in CHAT_ID_KEYS:
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()

    for path in _dotenv_candidates(cwd):
        values = _read_dotenv(path)
        for key in CHAT_ID_KEYS:
            value = values.get(key)
            if value and value.strip():
                return value.strip()
    return None


def resolve_user_feishu_id(explicit: str | None = None, *, cwd: Path | None = None) -> str | None:
    return resolve_user_chat_id(explicit=explicit, cwd=cwd)


def _dotenv_candidates(cwd: Path | None) -> list[Path]:
    current = (cwd or Path.cwd()).resolve()
    return [
        current / ".env",
        Path.home() / ".openclaw" / ".env",
    ]


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values
