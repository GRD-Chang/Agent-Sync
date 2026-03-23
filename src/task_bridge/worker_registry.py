from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerDefinition:
    name: str


CANONICAL_WORKER_REGISTRY: tuple[WorkerDefinition, ...] = (
    WorkerDefinition(name="planning-agent"),
    WorkerDefinition(name="code-agent"),
    WorkerDefinition(name="quality-agent"),
    WorkerDefinition(name="release-agent"),
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
