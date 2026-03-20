from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from task_bridge.runtime import now_iso
from task_bridge.store import TaskStore, infer_worker_status, queue_for_agent

from .detail_preview import load_detail_preview as _load_detail_preview
from .formatting import (
    format_timestamp as _format_timestamp,
    optional_display_text as _optional_display_text,
    optional_text as _optional_text,
    truncate as _truncate,
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

CORE_TASK_STATES = ["queued", "running", "done", "blocked", "failed"]
TASK_CARD_STATES = ("running", "blocked", "failed", "queued", "done")
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
        now_provider: Callable[[], str] = now_iso,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self.store = TaskStore(home)
        self._now_provider = now_provider
        self._locale = resolve_locale(locale)
        self._messages = get_messages(self._locale)

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
        summary_label, summary_text = self._task_summary(task)
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
            summary_text=summary_text,
            detail_href=self._jobs_path(
                job_id=str(task["job_id"]),
                task_id=str(task["id"]),
            )
            + "#job-task-detail",
        )

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
        from .tasks_page_queries import TasksPageQueryAssembler

        job_id = str(task["job_id"])
        detail_path = str(task.get("detail_path") or "")
        detail_preview = _load_detail_preview(detail_path)
        return TaskDetailSnapshot(
            task_id=str(task["id"]),
            job_id=job_id,
            job_href=job_href or self._jobs_path(job_id=job_id, task_id=str(task["id"])) + "#job-task-detail",
            state=str(task.get("state") or "queued"),
            assigned_agent=_optional_text(task.get("assigned_agent"))
            or self._messages["tasks"]["assigned_agent_empty"],
            notify_target=_optional_text(task.get("notify_target")) or self._messages["common"]["unknown"],
            created_at=_format_timestamp(
                str(task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            updated_at=_format_timestamp(
                str(task.get("updatedAt") or task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            requirement=_optional_display_text(task.get("requirement")) or self._messages["common"]["unknown"],
            result=_optional_display_text(task.get("result")),
            detail_path=detail_path,
            detail_status_label=self._messages["tasks"]["detail_status_labels"][detail_preview.status],
            detail_preview=detail_preview,
            timeline=self._build_task_timeline(task),
            back_links=back_links
            or TasksPageQueryAssembler(self)._build_task_back_links(
                task_id=str(task["id"]),
                job_id=job_id,
                selected_job_id=selected_job_id,
                selected_state=selected_state,
                selected_agent=selected_agent,
                selected_page=selected_page,
            ),
        )

    def _build_task_timeline(self, task: dict[str, object]) -> list[TaskTimelineEvent]:
        status_messages = self._messages["status"]
        tasks_messages = self._messages["tasks"]
        recent_label, recent_summary = self._task_summary(task)
        state = str(task.get("state") or "queued")
        state_label = status_messages.get(state, status_messages["queued"])["label"]
        agent = _optional_text(task.get("assigned_agent")) or tasks_messages["assigned_agent_empty"]
        target = _optional_text(task.get("notify_target")) or self._messages["common"]["unknown"]

        events: list[tuple[str, int, TaskTimelineEvent]] = []
        created_at = str(task.get("createdAt") or "")
        if created_at:
            events.append(
                (
                    created_at,
                    0,
                    TaskTimelineEvent(
                        key="created",
                        title=tasks_messages["timeline_created"],
                        timestamp_display=_format_timestamp(
                            created_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_created_note"].format(
                            summary=_truncate(
                                _optional_display_text(task.get("requirement")) or self._messages["common"]["unknown"],
                                140,
                            )
                        ),
                    ),
                )
            )

        updated_at = str(task.get("updatedAt") or "")
        if updated_at and updated_at != created_at:
            events.append(
                (
                    updated_at,
                    1,
                    TaskTimelineEvent(
                        key="updated",
                        title=tasks_messages["timeline_updated"],
                        timestamp_display=_format_timestamp(
                            updated_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_updated_note"].format(
                            state_label=state_label,
                            summary_label=recent_label,
                            summary=_truncate(recent_summary, 140),
                        ),
                    ),
                )
            )

        scheduler = _task_scheduler(task)
        dispatch_at = _optional_text(scheduler.get("last_dispatch_at"))
        if dispatch_at:
            events.append(
                (
                    dispatch_at,
                    2,
                    TaskTimelineEvent(
                        key="dispatch",
                        title=tasks_messages["timeline_dispatch"],
                        timestamp_display=_format_timestamp(
                            dispatch_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_dispatch_note"].format(agent=agent),
                    ),
                )
            )

        final_notified_at = _optional_text(scheduler.get("final_notified_at"))
        if final_notified_at:
            events.append(
                (
                    final_notified_at,
                    3,
                    TaskTimelineEvent(
                        key="final-notified",
                        title=tasks_messages["timeline_final_notified"],
                        timestamp_display=_format_timestamp(
                            final_notified_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_final_notified_note"].format(target=target),
                    ),
                )
            )

        followup_due_at = _optional_text(scheduler.get("leader_followup_due_at"))
        if followup_due_at:
            events.append(
                (
                    followup_due_at,
                    4,
                    TaskTimelineEvent(
                        key="followup-due",
                        title=tasks_messages["timeline_followup_due"],
                        timestamp_display=_format_timestamp(
                            followup_due_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_followup_due_note"],
                    ),
                )
            )

        followup_sent_at = _optional_text(scheduler.get("leader_followup_sent_at"))
        if followup_sent_at:
            events.append(
                (
                    followup_sent_at,
                    5,
                    TaskTimelineEvent(
                        key="followup-sent",
                        title=tasks_messages["timeline_followup_sent"],
                        timestamp_display=_format_timestamp(
                            followup_sent_at,
                            fallback=self._messages["common"]["unknown"],
                        ),
                        note=tasks_messages["timeline_followup_sent_note"],
                    ),
                )
            )

        events.sort(key=lambda item: (item[0], item[1]))
        return [event for _, _, event in events]

    @staticmethod
    def _resolve_selected_task(
        tasks: list[dict[str, object]],
        requested_task_id: str | None,
        requested_job_id: str | None,
    ) -> tuple[dict[str, object] | None, bool]:
        if not tasks:
            return None, False

        if requested_task_id:
            selected = next(
                (
                    task
                    for task in tasks
                    if str(task["id"]) == requested_task_id
                    and (requested_job_id is None or str(task["job_id"]) == requested_job_id)
                ),
                None,
            )
            if selected is not None:
                return selected, False
            return None, True

        return None, False

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
        result_text = _optional_display_text(task.get("result"))
        requirement_text = _optional_display_text(task.get("requirement"))
        if result_text:
            return self._messages["recent_update"]["result"], _truncate(result_text, 180)
        if requirement_text:
            return self._messages["recent_update"]["requirement"], _truncate(requirement_text, 180)
        return self._messages["recent_update"]["update"], self._messages["recent_update"]["no_detail"]

    def _path_with_locale(self, path: str, *pairs: tuple[str, str]) -> str:
        query_items = [(key, value) for key, value in pairs if value]
        if self._locale != DEFAULT_LOCALE:
            query_items.append(("lang", self._locale))
        return f"{path}?{urlencode(query_items)}" if query_items else path

    def _sort_tasks_for_cards(self, tasks: list[dict[str, object]]) -> list[dict[str, object]]:
        ordered = sorted(
            tasks,
            key=lambda item: (
                str(item.get("updatedAt") or item.get("createdAt") or ""),
                str(item["job_id"]),
                str(item["id"]),
            ),
            reverse=True,
        )
        ordered.sort(key=lambda item: _task_state_priority(str(item.get("state") or "queued")))
        return ordered


def _task_scheduler(task: dict[str, object]) -> dict[str, object]:
    scheduler = task.get("_scheduler")
    return scheduler if isinstance(scheduler, dict) else {}


def _task_state_priority(state: str) -> int:
    try:
        return TASK_CARD_STATES.index(state)
    except ValueError:
        return len(TASK_CARD_STATES)
