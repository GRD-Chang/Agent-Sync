from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerDefinition:
    name: str
    dashboard_accent: str = "#d6c9bc"
    dashboard_accent_rgb: tuple[int, int, int] = (214, 201, 188)


CANONICAL_WORKER_REGISTRY: tuple[WorkerDefinition, ...] = (
    WorkerDefinition(
        name="planning-agent",
        dashboard_accent="#8fcf78",
        dashboard_accent_rgb=(143, 207, 120),
    ),
    WorkerDefinition(
        name="code-agent",
        dashboard_accent="#7aa7ff",
        dashboard_accent_rgb=(122, 167, 255),
    ),
    WorkerDefinition(
        name="quality-agent",
        dashboard_accent="#5ed6b0",
        dashboard_accent_rgb=(94, 214, 176),
    ),
    WorkerDefinition(
        name="release-agent",
        dashboard_accent="#f27a63",
        dashboard_accent_rgb=(242, 122, 99),
    ),
)

_DASHBOARD_AGENT_OVERRIDES: tuple[WorkerDefinition, ...] = (
    WorkerDefinition(
        name="team-leader",
        dashboard_accent="#f5c451",
        dashboard_accent_rgb=(245, 196, 81),
    ),
    WorkerDefinition(
        name="review-agent",
        dashboard_accent="#ff8aa7",
        dashboard_accent_rgb=(255, 138, 167),
    ),
    WorkerDefinition(
        name="ops-agent",
        dashboard_accent="#ffb86b",
        dashboard_accent_rgb=(255, 184, 107),
    ),
)


def canonical_worker_registry() -> tuple[WorkerDefinition, ...]:
    return CANONICAL_WORKER_REGISTRY


def canonical_worker_names() -> tuple[str, ...]:
    return tuple(worker.name for worker in CANONICAL_WORKER_REGISTRY)


def roster_with_assigned_agents(assigned_agents: Iterable[str]) -> tuple[str, ...]:
    canonical = list(canonical_worker_names())
    known = set(canonical)
    extras = sorted({agent for agent in (item.strip() for item in assigned_agents) if agent and agent not in known})
    canonical.extend(extras)
    return tuple(canonical)


def dashboard_agent_theme_css() -> str:
    return _DASHBOARD_AGENT_THEME_CSS


def _rgb_css_value(value: tuple[int, int, int]) -> str:
    return ", ".join(str(channel) for channel in value)


def _escape_css_attr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _dashboard_agent_theme_definitions() -> tuple[WorkerDefinition, ...]:
    seen: set[str] = set()
    ordered: list[WorkerDefinition] = []
    for definition in (*_DASHBOARD_AGENT_OVERRIDES, *CANONICAL_WORKER_REGISTRY):
        if definition.name in seen:
            continue
        seen.add(definition.name)
        ordered.append(definition)
    return tuple(ordered)


def _build_dashboard_agent_theme_css() -> str:
    lines = [
        ":root {",
        '  --agent-default: #d6c9bc;',
        '  --agent-default-rgb: 214, 201, 188;',
    ]
    for definition in _dashboard_agent_theme_definitions():
        lines.append(f"  --agent-{definition.name}: {definition.dashboard_accent};")
        lines.append(
            f"  --agent-{definition.name}-rgb: {_rgb_css_value(definition.dashboard_accent_rgb)};"
        )
    lines.append("}")
    lines.append("")
    for definition in _dashboard_agent_theme_definitions():
        lines.append(
            '.dispatch-node-link[data-agent="{}"] {{ --agent-color: var(--agent-{}); '
            "--agent-color-rgb: var(--agent-{}-rgb); }}".format(
                _escape_css_attr_value(definition.name),
                definition.name,
                definition.name,
            )
        )
    return "\n".join(lines)


_DASHBOARD_AGENT_THEME_CSS = _build_dashboard_agent_theme_css()
