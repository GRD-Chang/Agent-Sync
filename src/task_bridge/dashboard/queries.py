from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .i18n import DEFAULT_LOCALE, get_messages
from ..store import TaskStore, infer_worker_status, now_iso, queue_for_agent

CORE_TASK_STATES = ("queued", "running", "done", "blocked", "failed")
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
RECENT_UPDATES_LIMIT = 6


@dataclass(frozen=True)
class TaskStatusMetric:
    state: str
    label: str
    description: str
    count: int


@dataclass(frozen=True)
class WorkerSnapshot:
    agent: str
    status: str
    running_task_id: str | None
    queued: int
    next_queued_task_id: str | None
    next_queued_job_id: str | None


@dataclass(frozen=True)
class RecentUpdate:
    task_id: str
    job_id: str
    assigned_agent: str
    state: str
    updated_at: str
    summary_label: str
    summary_text: str


@dataclass(frozen=True)
class OverviewSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    jobs_count: int
    tasks_count: int
    terminal_count: int
    worker_count: int
    busy_workers: int
    idle_workers: int
    queued_tasks: int
    task_status_metrics: list[TaskStatusMetric]
    workers: list[WorkerSnapshot]
    recent_updates: list[RecentUpdate]
    is_empty: bool


class DashboardQueryService:
    def __init__(
        self,
        home: Path | None = None,
        *,
        now_provider: Callable[[], str] = now_iso,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self.store = TaskStore(home)
        self._now_provider = now_provider
        self._messages = get_messages(locale)

    @property
    def home_path(self) -> str:
        return str(self.store.home)

    def overview(self) -> OverviewSnapshot:
        jobs = self.store.list_jobs()
        tasks = self.store.list_tasks(all_jobs=True)
        current_job_id = self.store.get_current_job_id()
        status_counts = Counter(str(task.get("state") or "queued") for task in tasks)
        metrics = [
            TaskStatusMetric(
                state=state,
                label=self._messages["status"][state]["label"],
                description=self._messages["status"][state]["description"],
                count=status_counts.get(state, 0),
            )
            for state in CORE_TASK_STATES
        ]

        worker_rows = infer_worker_status(tasks)
        worker_snapshots: list[WorkerSnapshot] = []
        for row in worker_rows:
            queue = queue_for_agent(tasks, str(row["agent"]))
            next_queued = queue["queued_tasks"][0] if queue["queued_tasks"] else None
            worker_snapshots.append(
                WorkerSnapshot(
                    agent=str(row["agent"]),
                    status=str(row["status"]),
                    running_task_id=_optional_text(row.get("running_task_id")),
                    queued=int(row["queued"]),
                    next_queued_task_id=_optional_text(next_queued.get("id")) if next_queued else None,
                    next_queued_job_id=_optional_text(next_queued.get("job_id")) if next_queued else None,
                )
            )

        busy_workers = sum(1 for worker in worker_snapshots if worker.status == "busy")
        queued_tasks = sum(worker.queued for worker in worker_snapshots)
        recent_updates = [
            self._build_recent_update(task)
            for task in sorted(
                tasks,
                key=lambda item: (str(item.get("updatedAt") or ""), str(item["job_id"]), str(item["id"])),
                reverse=True,
            )[:RECENT_UPDATES_LIMIT]
        ]

        return OverviewSnapshot(
            home_path=self.home_path,
            current_job_id=current_job_id,
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            jobs_count=len(jobs),
            tasks_count=len(tasks),
            terminal_count=sum(status_counts.get(state, 0) for state in TERMINAL_TASK_STATES),
            worker_count=len(worker_snapshots),
            busy_workers=busy_workers,
            idle_workers=max(len(worker_snapshots) - busy_workers, 0),
            queued_tasks=queued_tasks,
            task_status_metrics=metrics,
            workers=worker_snapshots,
            recent_updates=recent_updates,
            is_empty=not jobs and not tasks,
        )

    def _build_recent_update(self, task: dict[str, object]) -> RecentUpdate:
        result_text = _optional_text(task.get("result"))
        requirement_text = _optional_text(task.get("requirement"))
        if result_text:
            summary_label = self._messages["recent_update"]["result"]
            summary_text = result_text
        elif requirement_text:
            summary_label = self._messages["recent_update"]["requirement"]
            summary_text = requirement_text
        else:
            summary_label = self._messages["recent_update"]["update"]
            summary_text = self._messages["recent_update"]["no_detail"]
        return RecentUpdate(
            task_id=str(task["id"]),
            job_id=str(task["job_id"]),
            assigned_agent=_optional_text(task.get("assigned_agent")) or self._messages["recent_update"]["unassigned"],
            state=str(task.get("state") or "queued"),
            updated_at=_format_timestamp(
                str(task.get("updatedAt") or task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            summary_label=summary_label,
            summary_text=_truncate(summary_text, 180),
        )


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _format_timestamp(value: str, *, fallback: str) -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M UTC")
