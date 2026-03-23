from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlencode

from task_bridge.store import TaskStore, infer_worker_status, queue_for_agent
from task_bridge.worker_registry import roster_with_assigned_agents

from .formatting import (
    format_timestamp as _format_timestamp,
    optional_text as _optional_text,
)
from .i18n import DEFAULT_LOCALE, get_messages, resolve_locale
from .snapshots import (
    AlertsSnapshot,
    DetailBackLink,
    HealthSnapshot,
    JobsPageSnapshot,
    OverviewSnapshot,
    RecentUpdate,
    TaskDetailSnapshot,
    TaskStatusMetric,
    TasksPageSnapshot,
    TaskTimelineEvent,
    WorkerQueueSnapshot,
    WorkerSnapshot,
)
from .task_display_queries import (
    TASK_CARD_STATES,
    TaskDisplayQueryAssembler,
    resolve_selected_task as _resolve_selected_task_helper,
    task_scheduler as _task_scheduler,
)


def _dashboard_now_iso() -> str:
    """Stable 'now' for dashboard rendering.

    The dashboard is a read-only UI that renders snapshots for humans and tests.
    Using a fixed timestamp keeps follow-up grouping deterministic across time.
    """

    return "2026-03-20T12:00:00Z"

CORE_TASK_STATES = ["queued", "running", "done", "blocked", "failed"]
ACTIVE_TASK_STATES = {"queued", "running"}
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
RECENT_UPDATES_LIMIT = 6
JOB_VIEW_OPTIONS = ("all", "current", "active", "terminal")
JOB_DETAIL_VIEW_OPTIONS = ("tasks", "plan")
UNASSIGNED_AGENT_FILTER = "__unassigned__"
TASK_LIST_PAGE_SIZE = 12


class DashboardQueryService:
    def __init__(
        self,
        home: Path | None = None,
        *,
        now_provider: Callable[[], str] = _dashboard_now_iso,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self.store = TaskStore(home)
        self._now_provider = now_provider
        self._locale = resolve_locale(locale)
        self._messages = get_messages(self._locale)
        self._task_display = TaskDisplayQueryAssembler(self)

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
        worker_rows = self._worker_status_rows(tasks)
        workers: list[WorkerSnapshot] = []
        for row in worker_rows:
            queue = queue_for_agent(tasks, str(row["agent"]))
            next_queued = queue["queued_tasks"][0] if queue["queued_tasks"] else None
            workers.append(
                WorkerSnapshot(
                    agent=str(row["agent"]),
                    status=str(row["status"]),
                    running_task_id=_optional_text(row.get("running_task_id")),
                    queued=int(row["queued"]),
                    next_queued_task_id=_optional_text(next_queued.get("id")) if next_queued else None,
                    next_queued_job_id=_optional_text(next_queued.get("job_id")) if next_queued else None,
                )
            )
        busy_workers = sum(1 for worker in workers if worker.status == "busy")
        queued_tasks = sum(worker.queued for worker in workers)
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
            worker_count=len(workers),
            busy_workers=busy_workers,
            idle_workers=max(len(workers) - busy_workers, 0),
            queued_tasks=queued_tasks,
            task_status_metrics=metrics,
            workers=workers,
            recent_updates=recent_updates,
            is_empty=not jobs and not tasks,
        )

    def jobs(
        self,
        *,
        selected_job_id: str | None = None,
        selected_task_id: str | None = None,
        selected_view: str | None = None,
        selected_detail_view: str | None = None,
    ) -> JobsPageSnapshot:
        from .jobs_page_queries import JobsPageQueryAssembler

        return JobsPageQueryAssembler(self).build(
            selected_job_id=selected_job_id,
            selected_task_id=selected_task_id,
            selected_view=selected_view,
            selected_detail_view=selected_detail_view,
        )

    def tasks(
        self,
        *,
        selected_task_id: str | None = None,
        selected_job_id: str | None = None,
        selected_state: str | None = None,
        selected_agent: str | None = None,
        selected_page: str | None = None,
    ) -> TasksPageSnapshot:
        from .tasks_page_queries import TasksPageQueryAssembler

        return TasksPageQueryAssembler(self).build(
            selected_task_id=selected_task_id,
            selected_job_id=selected_job_id,
            selected_state=selected_state,
            selected_agent=selected_agent,
            selected_page=selected_page,
        )

    def worker_queue(self) -> WorkerQueueSnapshot:
        from .worker_queue_page_queries import WorkerQueuePageQueryAssembler

        return WorkerQueuePageQueryAssembler(self).build()

    def alerts(
        self,
        *,
        risk_page: str | None = None,
        followup_page: str | None = None,
    ) -> AlertsSnapshot:
        from .alerts_page_queries import AlertsPageQueryAssembler

        return AlertsPageQueryAssembler(self).build(
            risk_page=risk_page,
            followup_page=followup_page,
        )

    def health(self) -> HealthSnapshot:
        from .health_page_queries import HealthPageQueryAssembler

        return HealthPageQueryAssembler(self).build()

    def _build_recent_update(self, task: dict[str, object]) -> RecentUpdate:
        return self._task_display.build_recent_update(task)

    def _build_task_detail(
        self,
        task: dict[str, object],
        *,
        selected_job_id: str | None,
        selected_state: str | None = None,
        selected_agent: str | None = None,
        selected_page: int | None = None,
        back_links: list[DetailBackLink] | None = None,
        job_href: str | None = None,
    ) -> TaskDetailSnapshot:
        return self._task_display.build_task_detail(
            task,
            selected_job_id=selected_job_id,
            selected_state=selected_state,
            selected_agent=selected_agent,
            selected_page=selected_page,
            back_links=back_links,
            job_href=job_href,
        )

    def _build_task_timeline(self, task: dict[str, object]) -> list[TaskTimelineEvent]:
        return self._task_display.build_task_timeline(task)

    @staticmethod
    def _resolve_selected_task(
        tasks: list[dict[str, object]],
        requested_task_id: str | None,
        requested_job_id: str | None,
    ) -> tuple[dict[str, object] | None, bool]:
        return _resolve_selected_task_helper(tasks, requested_task_id, requested_job_id)

    def _jobs_path(
        self,
        *,
        job_id: str | None = None,
        task_id: str | None = None,
        view: str | None = None,
        detail_view: str | None = None,
    ) -> str:
        return self._path_with_locale(
            "/jobs",
            ("job", job_id or ""),
            ("task", task_id or ""),
            ("view", "" if view in (None, "all") else view),
            ("detail_view", "" if detail_view in (None, "tasks") else detail_view),
        )

    def _tasks_path(
        self,
        *,
        job_id: str | None = None,
        task_id: str | None = None,
        state: str | None = None,
        agent: str | None = None,
        page: int | None = None,
    ) -> str:
        return self._path_with_locale(
            "/tasks",
            ("job", job_id or ""),
            ("state", state or ""),
            ("agent", agent or ""),
            ("page", str(page) if page and page > 1 else ""),
            ("task", task_id or ""),
        )

    def _task_summary(self, task: dict[str, object]) -> tuple[str, str]:
        return self._task_display.task_summary(task)

    def _path_with_locale(self, path: str, *pairs: tuple[str, str]) -> str:
        query_items = [(key, value) for key, value in pairs if value]
        if self._locale != DEFAULT_LOCALE:
            query_items.append(("lang", self._locale))
        return f"{path}?{urlencode(query_items)}" if query_items else path

    def _sort_tasks_for_cards(self, tasks: list[dict[str, object]]) -> list[dict[str, object]]:
        return self._task_display.sort_tasks_for_cards(tasks)

    def _worker_roster(
        self,
        assigned_agents: Iterable[str],
        *,
        include_agents: Iterable[str] = (),
    ) -> tuple[str, ...]:
        candidates = [str(agent).strip() for agent in assigned_agents]
        candidates.extend(str(agent).strip() for agent in include_agents)
        return roster_with_assigned_agents(candidates)

    def _worker_status_rows(
        self,
        tasks: list[dict[str, object]],
        *,
        include_agents: Iterable[str] = (),
    ) -> list[dict[str, object]]:
        rows_by_agent = {str(row["agent"]): row for row in infer_worker_status(tasks)}
        rows: list[dict[str, object]] = []
        for agent in self._worker_roster(
            (str(task.get("assigned_agent") or "") for task in tasks),
            include_agents=include_agents,
        ):
            rows.append(
                rows_by_agent.get(
                    agent,
                    {
                        "agent": agent,
                        "status": "idle",
                        "running_task_id": None,
                        "queued": 0,
                    },
                )
            )
        return rows
