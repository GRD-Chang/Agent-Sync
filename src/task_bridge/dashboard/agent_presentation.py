from __future__ import annotations

from dataclasses import dataclass

from task_bridge.worker_registry import dashboard_agent_theme_names

from .formatting import optional_text as _optional_text


@dataclass(frozen=True, slots=True)
class AgentPresentation:
    raw_key: str | None
    display_label: str
    fallback_kind: str


def resolve_agent_presentation(value: object, *, empty_label: str) -> AgentPresentation:
    raw_key = _optional_text(value)
    if raw_key is None:
        return AgentPresentation(
            raw_key=None,
            display_label=empty_label,
            fallback_kind="unassigned",
        )
    fallback_kind = "explicit-theme" if raw_key in dashboard_agent_theme_names() else "default-theme"
    return AgentPresentation(
        raw_key=raw_key,
        display_label=raw_key,
        fallback_kind=fallback_kind,
    )
