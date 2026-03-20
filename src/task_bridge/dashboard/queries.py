from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from task_bridge.runtime import now_iso
from task_bridge.store import TaskStore, infer_worker_status, queue_for_agent

from .i18n import DEFAULT_LOCALE, get_messages, resolve_locale

CORE_TASK_STATES = ["queued", "running", "done", "blocked", "failed"]
ACTIVE_TASK_STATES = {"queued", "running"}
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
ALERT_TASK_STATES = {"blocked", "failed"}
RECENT_UPDATES_LIMIT = 6
JOB_TASK_PREVIEW_LIMIT = 6
DETAIL_PREVIEW_LINE_LIMIT = 60
DETAIL_PREVIEW_CHAR_LIMIT = 5000
JOB_VIEW_OPTIONS = ("all", "current", "active", "terminal")
UNASSIGNED_AGENT_FILTER = "__unassigned__"


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


@dataclass(frozen=True)
class LinkOption:
    key: str
    label: str
    href: str
    is_active: bool = False
    count: int | None = None


@dataclass(frozen=True)
class FilterGroup:
    key: str
    label: str
    options: list[LinkOption]


@dataclass(frozen=True)
class AppliedFilter:
    label: str
    value: str
    clear_href: str


@dataclass(frozen=True)
class JobListItem:
    job_id: str
    title: str
    notify_target: str
    created_at: str
    updated_at: str
    is_current: bool
    is_selected: bool
    task_count: int
    active_task_count: int
    terminal_task_count: int
    detail_href: str


@dataclass(frozen=True)
class DetailBackLink:
    label: str
    href: str


@dataclass(frozen=True)
class JobTaskPreview:
    task_id: str
    state: str
    assigned_agent: str
    updated_at: str
    summary_label: str
    summary_text: str
    detail_href: str


@dataclass(frozen=True)
class JobDetailSnapshot:
    job_id: str
    title: str
    notify_target: str
    created_at: str
    updated_at: str
    is_current: bool
    task_count: int
    active_task_count: int
    terminal_task_count: int
    tasks_href: str
    latest_task_href: str | None
    task_status_metrics: list[TaskStatusMetric]
    task_previews: list[JobTaskPreview]


@dataclass(frozen=True)
class JobsPageSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    jobs_count: int
    tasks_count: int
    visible_jobs_count: int
    active_view: str
    view_options: list[LinkOption]
    jobs: list[JobListItem]
    selected_job: JobDetailSnapshot | None
    detail_back_link: DetailBackLink | None
    is_empty: bool
    filtered_empty: bool
    selection_missing: bool


@dataclass(frozen=True)
class TaskListItem:
    task_id: str
    job_id: str
    state: str
    assigned_agent: str
    created_at: str
    updated_at: str
    summary_label: str
    summary_text: str
    detail_status_label: str
    detail_href: str
    job_href: str
    is_selected: bool


@dataclass(frozen=True)
class DetailPreviewBlock:
    kind: str
    text: str = ""
    level: int = 0
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetailPreview:
    status: str
    path: str
    blocks: tuple[DetailPreviewBlock, ...] = ()
    is_truncated: bool = False
    error_message: str | None = None
    line_limit: int = DETAIL_PREVIEW_LINE_LIMIT
    char_limit: int = DETAIL_PREVIEW_CHAR_LIMIT


@dataclass(frozen=True)
class TaskTimelineEvent:
    key: str
    title: str
    timestamp_display: str
    note: str


@dataclass(frozen=True)
class TaskDetailSnapshot:
    task_id: str
    job_id: str
    job_href: str
    state: str
    assigned_agent: str
    notify_target: str
    created_at: str
    updated_at: str
    requirement: str
    result: str | None
    detail_path: str
    detail_status_label: str
    detail_preview: DetailPreview
    timeline: list[TaskTimelineEvent]
    back_links: list[DetailBackLink]


@dataclass(frozen=True)
class TasksPageSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    jobs_count: int
    tasks_count: int
    visible_tasks_count: int
    filter_groups: list[FilterGroup]
    applied_filters: list[AppliedFilter]
    clear_filters_href: str
    tasks: list[TaskListItem]
    selected_task: TaskDetailSnapshot | None
    detail_back_link: DetailBackLink | None
    is_empty: bool
    filtered_empty: bool
    selection_missing: bool


@dataclass(frozen=True)
class QueueTaskSnapshot:
    task_id: str
    job_id: str
    assigned_agent: str
    state: str
    updated_at: str
    summary_label: str
    summary_text: str


@dataclass(frozen=True)
class WorkerLaneSnapshot:
    agent: str
    status: str
    running_task_id: str | None
    running_summary_label: str | None
    running_summary_text: str | None
    queued_tasks: list[QueueTaskSnapshot]


@dataclass(frozen=True)
class WorkerQueueSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    worker_count: int
    busy_workers: int
    idle_workers: int
    running_tasks: int
    assigned_queue_depth: int
    unassigned_queue_depth: int
    lanes: list[WorkerLaneSnapshot]
    unassigned_queued_tasks: list[QueueTaskSnapshot]
    has_activity: bool


@dataclass(frozen=True)
class AlertTaskSnapshot:
    task_id: str
    job_id: str
    assigned_agent: str
    state: str
    updated_at: str
    summary_label: str
    summary_text: str


@dataclass(frozen=True)
class FollowupTaskSnapshot:
    task_id: str
    job_id: str
    state: str
    notify_target: str
    final_notified_at: str
    due_at: str
    is_overdue: bool
    summary_label: str
    summary_text: str


@dataclass(frozen=True)
class AlertsSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    blocked_count: int
    failed_count: int
    pending_followups_count: int
    overdue_followups_count: int
    risk_tasks: list[AlertTaskSnapshot]
    followup_tasks: list[FollowupTaskSnapshot]
    has_alerts: bool


@dataclass(frozen=True)
class HealthCheck:
    key: str
    label: str
    status: str
    detail: str


@dataclass(frozen=True)
class HealthSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    jobs_count: int
    tasks_count: int
    worker_prompt_entries: int
    leader_last_running_notice_at: str
    checks: list[HealthCheck]


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
        selected_view: str | None = None,
    ) -> JobsPageSnapshot:
        jobs = self.store.list_jobs()
        tasks = self.store.list_tasks(all_jobs=True)
        tasks_by_job: dict[str, list[dict[str, object]]] = defaultdict(list)
        for task in tasks:
            tasks_by_job[str(task["job_id"])].append(task)

        active_view = selected_view if selected_view in JOB_VIEW_OPTIONS else "all"
        ordered_jobs = [
            job
            for job in reversed(jobs)
            if self._job_matches_view(job, tasks_by_job.get(str(job["id"]), []), active_view)
        ]
        resolved_job_id, selection_missing = self._resolve_selected_job_id(ordered_jobs, selected_job_id)
        detail_back_link = (
            DetailBackLink(
                label=self._messages["jobs"]["back_to_list"],
                href=self._jobs_path(view=active_view),
            )
            if resolved_job_id
            else None
        )
        job_rows = [
            self._build_job_row(
                job,
                job_tasks=tasks_by_job.get(str(job["id"]), []),
                selected_job_id=resolved_job_id,
                active_view=active_view,
            )
            for job in ordered_jobs
        ]
        selected_job_raw = next((job for job in ordered_jobs if str(job["id"]) == resolved_job_id), None)

        return JobsPageSnapshot(
            home_path=self.home_path,
            current_job_id=self.store.get_current_job_id(),
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            jobs_count=len(jobs),
            tasks_count=len(tasks),
            visible_jobs_count=len(ordered_jobs),
            active_view=active_view,
            view_options=self._build_job_view_options(
                jobs,
                tasks_by_job=tasks_by_job,
                active_view=active_view,
                selected_job_id=selected_job_id,
            ),
            jobs=job_rows,
            selected_job=self._build_job_detail(selected_job_raw, tasks_by_job.get(resolved_job_id or "", []))
            if selected_job_raw
            else None,
            detail_back_link=detail_back_link,
            is_empty=not jobs,
            filtered_empty=bool(jobs and not ordered_jobs),
            selection_missing=selection_missing,
        )

    def tasks(
        self,
        *,
        selected_task_id: str | None = None,
        selected_job_id: str | None = None,
        selected_state: str | None = None,
        selected_agent: str | None = None,
    ) -> TasksPageSnapshot:
        jobs = self.store.list_jobs()
        tasks = sorted(
            self.store.list_tasks(all_jobs=True),
            key=lambda item: (
                str(item.get("updatedAt") or item.get("createdAt") or ""),
                str(item["job_id"]),
                str(item["id"]),
            ),
            reverse=True,
        )

        active_state = selected_state if selected_state in CORE_TASK_STATES else None
        active_agent = selected_agent or None
        filtered_tasks = [
            task
            for task in tasks
            if self._task_matches_filters(
                task,
                job_id=selected_job_id,
                state=active_state,
                agent=active_agent,
            )
        ]
        resolved_task, selection_missing = self._resolve_selected_task(filtered_tasks, selected_task_id, selected_job_id)
        resolved_task_id = str(resolved_task["id"]) if resolved_task else None
        detail_back_link = (
            DetailBackLink(
                label=self._messages["tasks"]["back_to_list"],
                href=self._tasks_path(job_id=selected_job_id, state=active_state, agent=active_agent),
            )
            if resolved_task_id
            else None
        )
        task_rows = [
            self._build_task_row(
                task,
                resolved_task_id=resolved_task_id,
                selected_job_id=selected_job_id,
                selected_state=active_state,
                selected_agent=active_agent,
            )
            for task in filtered_tasks
        ]

        return TasksPageSnapshot(
            home_path=self.home_path,
            current_job_id=self.store.get_current_job_id(),
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            jobs_count=len(jobs),
            tasks_count=len(tasks),
            visible_tasks_count=len(filtered_tasks),
            filter_groups=self._build_task_filter_groups(
                tasks=tasks,
                jobs=jobs,
                selected_job_id=selected_job_id,
                selected_state=active_state,
                selected_agent=active_agent,
            ),
            applied_filters=self._build_task_applied_filters(
                jobs,
                selected_job_id=selected_job_id,
                selected_state=active_state,
                selected_agent=active_agent,
            ),
            clear_filters_href=self._tasks_path(),
            tasks=task_rows,
            selected_task=self._build_task_detail(
                resolved_task,
                selected_job_id=selected_job_id,
                selected_state=active_state,
                selected_agent=active_agent,
            )
            if resolved_task
            else None,
            detail_back_link=detail_back_link,
            is_empty=not tasks,
            filtered_empty=bool(tasks and not filtered_tasks),
            selection_missing=selection_missing,
        )

    def worker_queue(self) -> WorkerQueueSnapshot:
        tasks = self.store.list_tasks(all_jobs=True)
        worker_rows = infer_worker_status(tasks)
        lanes: list[WorkerLaneSnapshot] = []
        assigned_queue_depth = 0
        for row in worker_rows:
            agent = str(row["agent"])
            queue = queue_for_agent(tasks, agent)
            queued_tasks = [self._build_queue_task(task) for task in queue["queued_tasks"]]
            assigned_queue_depth += len(queued_tasks)
            running_task = next(
                (
                    task
                    for task in tasks
                    if str(task.get("assigned_agent") or "") == agent and str(task.get("state") or "queued") == "running"
                ),
                None,
            )
            running_label = None
            running_text = None
            if running_task is not None:
                running_label, running_text = self._task_summary(running_task)
            lanes.append(
                WorkerLaneSnapshot(
                    agent=agent,
                    status=str(row["status"]),
                    running_task_id=_optional_text(row.get("running_task_id")),
                    running_summary_label=running_label,
                    running_summary_text=running_text,
                    queued_tasks=queued_tasks,
                )
            )
        unassigned = [
            self._build_queue_task(task)
            for task in sorted(
                [
                    task
                    for task in tasks
                    if str(task.get("state") or "queued") == "queued" and not _optional_text(task.get("assigned_agent"))
                ],
                key=lambda item: (str(item.get("createdAt") or ""), str(item["job_id"]), str(item["id"])),
            )
        ]
        busy_workers = sum(1 for lane in lanes if lane.status == "busy")
        return WorkerQueueSnapshot(
            home_path=self.home_path,
            current_job_id=self.store.get_current_job_id(),
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            worker_count=len(lanes),
            busy_workers=busy_workers,
            idle_workers=max(len(lanes) - busy_workers, 0),
            running_tasks=sum(1 for lane in lanes if lane.running_task_id),
            assigned_queue_depth=assigned_queue_depth,
            unassigned_queue_depth=len(unassigned),
            lanes=lanes,
            unassigned_queued_tasks=unassigned,
            has_activity=bool(tasks),
        )

    def alerts(self) -> AlertsSnapshot:
        self.store.list_jobs()
        tasks = self.store.list_tasks(all_jobs=True)
        status_counts = Counter(str(task.get("state") or "queued") for task in tasks)
        now_value = _parse_timestamp(self._now_provider())
        risk_tasks = [
            self._build_alert_task(task)
            for task in sorted(
                [task for task in tasks if str(task.get("state") or "queued") in ALERT_TASK_STATES],
                key=lambda item: (
                    str(item.get("updatedAt") or item.get("createdAt") or ""),
                    str(item["job_id"]),
                    str(item["id"]),
                ),
                reverse=True,
            )
        ]
        followup_raw = [
            task
            for task in tasks
            if _optional_text(_task_scheduler(task).get("leader_followup_due_at"))
            and _task_scheduler(task).get("leader_followup_sent_at") is None
        ]
        followup_raw.sort(
            key=lambda item: (
                0 if _is_overdue(_optional_text(_task_scheduler(item).get("leader_followup_due_at")), now_value) else 1,
                str(_task_scheduler(item).get("leader_followup_due_at") or ""),
                str(item["job_id"]),
                str(item["id"]),
            )
        )
        followups = [self._build_followup_task(task, now_value=now_value) for task in followup_raw]
        return AlertsSnapshot(
            home_path=self.home_path,
            current_job_id=self.store.get_current_job_id(),
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            blocked_count=status_counts.get("blocked", 0),
            failed_count=status_counts.get("failed", 0),
            pending_followups_count=len(followups),
            overdue_followups_count=sum(1 for task in followups if task.is_overdue),
            risk_tasks=risk_tasks,
            followup_tasks=followups,
            has_alerts=bool(risk_tasks or followups),
        )

    def health(self) -> HealthSnapshot:
        messages = self._messages["health"]
        current_job_id = self.store.get_current_job_id()
        generated_at = _format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"])
        jobs_count = 0
        tasks_count = 0
        records_status = "ok"
        records_detail = messages["records_ok"].format(jobs_count=jobs_count, tasks_count=tasks_count)
        try:
            jobs = self.store.list_jobs()
            tasks = self.store.list_tasks(all_jobs=True)
            jobs_count = len(jobs)
            tasks_count = len(tasks)
            records_detail = messages["records_ok"].format(jobs_count=jobs_count, tasks_count=tasks_count)
        except Exception:
            records_status = "warn"
            records_detail = messages["records_warn"]
        worker_prompt_entries = 0
        leader_last_running_notice_at = messages["leader_last_running_notice_empty"]
        daemon_status = "ok"
        daemon_detail = messages["daemon_ok_existing"]
        cache_status = "ok"
        cache_detail = messages["cache_ok"].format(
            worker_prompt_entries=worker_prompt_entries,
            leader_last_running_notice_at=leader_last_running_notice_at,
        )
        try:
            daemon_exists = self.store.daemon_state_path().exists()
            daemon_state = self.store.load_daemon_state()
            worker_prompt_entries = len(daemon_state["worker_last_prompt_at"])
            leader_last_running_notice_at = _format_timestamp(
                str(daemon_state.get("leader_last_running_notice_at") or ""),
                fallback=messages["leader_last_running_notice_empty"],
            )
            daemon_detail = messages["daemon_ok_existing"] if daemon_exists else messages["daemon_ok_default"]
            cache_detail = messages["cache_ok"].format(
                worker_prompt_entries=worker_prompt_entries,
                leader_last_running_notice_at=leader_last_running_notice_at,
            )
        except Exception:
            daemon_status = "warn"
            cache_status = "warn"
            daemon_detail = messages["daemon_warn"]
            cache_detail = messages["cache_warn"]
            leader_last_running_notice_at = messages["leader_last_running_notice_empty"]
        checks = [
            HealthCheck("store-home", messages["store_home_check"], "ok", self.home_path),
            HealthCheck("records", messages["records_check"], records_status, records_detail),
            HealthCheck("daemon-state", messages["daemon_check"], daemon_status, daemon_detail),
            HealthCheck("prompt-cache", messages["cache_check"], cache_status, cache_detail),
        ]
        return HealthSnapshot(
            home_path=self.home_path,
            current_job_id=current_job_id,
            generated_at=generated_at,
            jobs_count=jobs_count,
            tasks_count=tasks_count,
            worker_prompt_entries=worker_prompt_entries,
            leader_last_running_notice_at=leader_last_running_notice_at,
            checks=checks,
        )

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
        )

    def _build_job_row(
        self,
        job: dict[str, object],
        *,
        job_tasks: list[dict[str, object]],
        selected_job_id: str | None,
        active_view: str,
    ) -> JobListItem:
        counts = Counter(str(task.get("state") or "queued") for task in job_tasks)
        job_id = str(job["id"])
        return JobListItem(
            job_id=job_id,
            title=str(job.get("title") or self._messages["common"]["unknown"]),
            notify_target=_optional_text(job.get("notify_target")) or self._messages["common"]["unknown"],
            created_at=_format_timestamp(
                str(job.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            updated_at=_format_timestamp(
                str(job.get("updatedAt") or job.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            is_current=bool(job.get("is_current")),
            is_selected=job_id == selected_job_id,
            task_count=len(job_tasks),
            active_task_count=sum(counts.get(state, 0) for state in ACTIVE_TASK_STATES),
            terminal_task_count=sum(counts.get(state, 0) for state in TERMINAL_TASK_STATES),
            detail_href=self._jobs_path(job_id=job_id, view=active_view),
        )

    def _build_job_detail(
        self,
        job: dict[str, object] | None,
        job_tasks: list[dict[str, object]],
    ) -> JobDetailSnapshot | None:
        if job is None:
            return None

        counts = Counter(str(task.get("state") or "queued") for task in job_tasks)
        status_metrics = [
            TaskStatusMetric(
                state=state,
                label=self._messages["status"][state]["label"],
                description=self._messages["status"][state]["description"],
                count=counts.get(state, 0),
            )
            for state in CORE_TASK_STATES
        ]
        task_previews = [
            JobTaskPreview(
                task_id=str(task["id"]),
                state=str(task.get("state") or "queued"),
                assigned_agent=_optional_text(task.get("assigned_agent"))
                or self._messages["tasks"]["assigned_agent_empty"],
                updated_at=_format_timestamp(
                    str(task.get("updatedAt") or task.get("createdAt") or ""),
                    fallback=self._messages["common"]["unknown"],
                ),
                summary_label=summary_label,
                summary_text=summary_text,
                detail_href=self._path_with_locale(
                    "/tasks",
                    ("job", str(task["job_id"])),
                    ("task", str(task["id"])),
                ),
            )
            for task, (summary_label, summary_text) in [
                (task, self._task_summary(task))
                for task in sorted(
                    job_tasks,
                    key=lambda item: (
                        str(item.get("updatedAt") or item.get("createdAt") or ""),
                        str(item["id"]),
                    ),
                    reverse=True,
                )[:JOB_TASK_PREVIEW_LIMIT]
            ]
        ]
        latest_task_href = task_previews[0].detail_href if task_previews else None

        return JobDetailSnapshot(
            job_id=str(job["id"]),
            title=str(job.get("title") or self._messages["common"]["unknown"]),
            notify_target=_optional_text(job.get("notify_target")) or self._messages["common"]["unknown"],
            created_at=_format_timestamp(
                str(job.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            updated_at=_format_timestamp(
                str(job.get("updatedAt") or job.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            is_current=bool(job.get("is_current")),
            task_count=len(job_tasks),
            active_task_count=sum(counts.get(state, 0) for state in ACTIVE_TASK_STATES),
            terminal_task_count=sum(counts.get(state, 0) for state in TERMINAL_TASK_STATES),
            tasks_href=self._tasks_path(job_id=str(job["id"])),
            latest_task_href=latest_task_href,
            task_status_metrics=status_metrics,
            task_previews=task_previews,
        )

    def _build_task_row(
        self,
        task: dict[str, object],
        *,
        resolved_task_id: str | None,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
    ) -> TaskListItem:
        summary_label, summary_text = self._task_summary(task)
        task_id = str(task["id"])
        job_id = str(task["job_id"])
        detail_status = _detail_preview_status(str(task.get("detail_path") or ""))
        return TaskListItem(
            task_id=task_id,
            job_id=job_id,
            state=str(task.get("state") or "queued"),
            assigned_agent=_optional_text(task.get("assigned_agent"))
            or self._messages["tasks"]["assigned_agent_empty"],
            created_at=_format_timestamp(
                str(task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            updated_at=_format_timestamp(
                str(task.get("updatedAt") or task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            summary_label=summary_label,
            summary_text=summary_text,
            detail_status_label=self._messages["tasks"]["detail_status_labels"][detail_status],
            detail_href=self._tasks_path(
                job_id=selected_job_id or job_id,
                task_id=task_id,
                state=selected_state,
                agent=selected_agent,
            ),
            job_href=self._path_with_locale("/jobs", ("job", job_id)),
            is_selected=task_id == resolved_task_id,
        )

    def _build_task_detail(
        self,
        task: dict[str, object],
        *,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
    ) -> TaskDetailSnapshot:
        job_id = str(task["job_id"])
        detail_path = str(task.get("detail_path") or "")
        detail_preview = _load_detail_preview(detail_path)
        return TaskDetailSnapshot(
            task_id=str(task["id"]),
            job_id=job_id,
            job_href=self._path_with_locale("/jobs", ("job", job_id)),
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
            back_links=self._build_task_back_links(
                task_id=str(task["id"]),
                job_id=job_id,
                selected_job_id=selected_job_id,
                selected_state=selected_state,
                selected_agent=selected_agent,
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
    def _resolve_selected_job_id(
        jobs: list[dict[str, object]],
        requested_job_id: str | None,
    ) -> tuple[str | None, bool]:
        if not jobs:
            return None, False

        if requested_job_id:
            requested_job = next((job for job in jobs if str(job["id"]) == requested_job_id), None)
            if requested_job:
                return requested_job_id, False
            return None, True

        return None, False

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

    def _job_matches_view(
        self,
        job: dict[str, object],
        job_tasks: list[dict[str, object]],
        selected_view: str,
    ) -> bool:
        counts = Counter(str(task.get("state") or "queued") for task in job_tasks)
        if selected_view == "current":
            return bool(job.get("is_current"))
        if selected_view == "active":
            return sum(counts.get(state, 0) for state in ACTIVE_TASK_STATES) > 0
        if selected_view == "terminal":
            return sum(counts.get(state, 0) for state in TERMINAL_TASK_STATES) > 0
        return True

    def _build_job_view_options(
        self,
        jobs: list[dict[str, object]],
        *,
        tasks_by_job: dict[str, list[dict[str, object]]],
        active_view: str,
        selected_job_id: str | None,
    ) -> list[LinkOption]:
        messages = self._messages["jobs"]
        view_labels = {
            "all": messages["view_all"],
            "current": messages["view_current"],
            "active": messages["view_active"],
            "terminal": messages["view_terminal"],
        }
        return [
            LinkOption(
                key=view_key,
                label=view_labels[view_key],
                href=self._jobs_path(job_id=selected_job_id, view=view_key),
                is_active=view_key == active_view,
                count=sum(
                    1
                    for job in jobs
                    if self._job_matches_view(job, tasks_by_job.get(str(job["id"]), []), view_key)
                ),
            )
            for view_key in JOB_VIEW_OPTIONS
        ]

    def _task_matches_filters(
        self,
        task: dict[str, object],
        *,
        job_id: str | None = None,
        state: str | None = None,
        agent: str | None = None,
    ) -> bool:
        if job_id and str(task["job_id"]) != job_id:
            return False
        if state and str(task.get("state") or "queued") != state:
            return False
        if agent == UNASSIGNED_AGENT_FILTER:
            return _optional_text(task.get("assigned_agent")) is None
        if agent and _optional_text(task.get("assigned_agent")) != agent:
            return False
        return True

    def _build_task_filter_groups(
        self,
        *,
        tasks: list[dict[str, object]],
        jobs: list[dict[str, object]],
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
    ) -> list[FilterGroup]:
        common = self._messages["common"]
        task_messages = self._messages["tasks"]
        job_options = [
            LinkOption(
                key="all",
                label=common["all"],
                href=self._tasks_path(state=selected_state, agent=selected_agent),
                is_active=selected_job_id is None,
                count=sum(
                    1
                    for task in tasks
                    if self._task_matches_filters(task, state=selected_state, agent=selected_agent)
                ),
            )
        ]
        for job in reversed(jobs):
            job_id = str(job["id"])
            job_options.append(
                LinkOption(
                    key=job_id,
                    label=str(job.get("title") or job_id),
                    href=self._tasks_path(job_id=job_id, state=selected_state, agent=selected_agent),
                    is_active=job_id == selected_job_id,
                    count=sum(
                        1
                        for task in tasks
                        if self._task_matches_filters(
                            task,
                            job_id=job_id,
                            state=selected_state,
                            agent=selected_agent,
                        )
                    ),
                )
            )

        state_options = [
            LinkOption(
                key="all",
                label=common["all"],
                href=self._tasks_path(job_id=selected_job_id, agent=selected_agent),
                is_active=selected_state is None,
                count=sum(
                    1
                    for task in tasks
                    if self._task_matches_filters(task, job_id=selected_job_id, agent=selected_agent)
                ),
            )
        ]
        for state in CORE_TASK_STATES:
            state_options.append(
                LinkOption(
                    key=state,
                    label=self._messages["status"][state]["label"],
                    href=self._tasks_path(job_id=selected_job_id, state=state, agent=selected_agent),
                    is_active=state == selected_state,
                    count=sum(
                        1
                        for task in tasks
                        if self._task_matches_filters(
                            task,
                            job_id=selected_job_id,
                            state=state,
                            agent=selected_agent,
                        )
                    ),
                )
            )

        agent_options = [
            LinkOption(
                key="all",
                label=common["all"],
                href=self._tasks_path(job_id=selected_job_id, state=selected_state),
                is_active=selected_agent is None,
                count=sum(
                    1
                    for task in tasks
                    if self._task_matches_filters(task, job_id=selected_job_id, state=selected_state)
                ),
            )
        ]
        unassigned_count = sum(
            1
            for task in tasks
            if self._task_matches_filters(
                task,
                job_id=selected_job_id,
                state=selected_state,
                agent=UNASSIGNED_AGENT_FILTER,
            )
        )
        if unassigned_count or selected_agent == UNASSIGNED_AGENT_FILTER:
            agent_options.append(
                LinkOption(
                    key="unassigned",
                    label=task_messages["assigned_agent_empty"],
                    href=self._tasks_path(
                        job_id=selected_job_id,
                        state=selected_state,
                        agent=UNASSIGNED_AGENT_FILTER,
                    ),
                    is_active=selected_agent == UNASSIGNED_AGENT_FILTER,
                    count=unassigned_count,
                )
            )
        known_agents = sorted(
            {
                agent
                for agent in (_optional_text(task.get("assigned_agent")) for task in tasks)
                if agent
            }
        )
        for agent in known_agents:
            agent_options.append(
                LinkOption(
                    key=agent,
                    label=agent,
                    href=self._tasks_path(job_id=selected_job_id, state=selected_state, agent=agent),
                    is_active=agent == selected_agent,
                    count=sum(
                        1
                        for task in tasks
                        if self._task_matches_filters(
                            task,
                            job_id=selected_job_id,
                            state=selected_state,
                            agent=agent,
                        )
                    ),
                )
            )

        return [
            FilterGroup(key="job", label=task_messages["filter_group_job"], options=job_options),
            FilterGroup(key="state", label=task_messages["filter_group_state"], options=state_options),
            FilterGroup(key="agent", label=task_messages["filter_group_agent"], options=agent_options),
        ]

    def _build_task_back_links(
        self,
        *,
        task_id: str,
        job_id: str,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
    ) -> list[DetailBackLink]:
        links = [
            DetailBackLink(
                label=self._messages["tasks"]["back_to_tasks"],
                href=self._tasks_path(job_id=selected_job_id, state=selected_state, agent=selected_agent),
            )
        ]
        job_link = self._jobs_path(job_id=job_id)
        if selected_job_id != job_id:
            job_link = self._path_with_locale(
                "/jobs",
                ("job", job_id),
                ("source_task", task_id),
            )
        links.append(DetailBackLink(label=self._messages["tasks"]["back_to_job"], href=job_link))
        return links

    def _build_task_applied_filters(
        self,
        jobs: list[dict[str, object]],
        *,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
    ) -> list[AppliedFilter]:
        applied: list[AppliedFilter] = []
        if selected_job_id:
            selected_job = next((job for job in jobs if str(job["id"]) == selected_job_id), None)
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["job_id"],
                    value=str(selected_job.get("title") or selected_job_id) if selected_job else selected_job_id,
                    clear_href=self._tasks_path(state=selected_state, agent=selected_agent),
                )
            )
        if selected_state:
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["state"],
                    value=self._messages["status"][selected_state]["label"],
                    clear_href=self._tasks_path(job_id=selected_job_id, agent=selected_agent),
                )
            )
        if selected_agent:
            agent_label = (
                self._messages["tasks"]["assigned_agent_empty"]
                if selected_agent == UNASSIGNED_AGENT_FILTER
                else selected_agent
            )
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["assigned_agent"],
                    value=agent_label,
                    clear_href=self._tasks_path(job_id=selected_job_id, state=selected_state),
                )
            )
        return applied

    def _jobs_path(self, *, job_id: str | None = None, view: str | None = None) -> str:
        return self._path_with_locale(
            "/jobs",
            ("job", job_id or ""),
            ("view", "" if view in (None, "all") else view),
        )

    def _tasks_path(
        self,
        *,
        job_id: str | None = None,
        task_id: str | None = None,
        state: str | None = None,
        agent: str | None = None,
    ) -> str:
        return self._path_with_locale(
            "/tasks",
            ("job", job_id or ""),
            ("state", state or ""),
            ("agent", agent or ""),
            ("task", task_id or ""),
        )

    def _build_queue_task(self, task: dict[str, object]) -> QueueTaskSnapshot:
        summary_label, summary_text = self._task_summary(task)
        return QueueTaskSnapshot(
            task_id=str(task["id"]),
            job_id=str(task["job_id"]),
            assigned_agent=_optional_text(task.get("assigned_agent")) or self._messages["common"]["none"],
            state=str(task.get("state") or "queued"),
            updated_at=_format_timestamp(
                str(task.get("updatedAt") or task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            summary_label=summary_label,
            summary_text=summary_text,
        )

    def _build_alert_task(self, task: dict[str, object]) -> AlertTaskSnapshot:
        summary_label, summary_text = self._task_summary(task)
        return AlertTaskSnapshot(
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
        )

    def _build_followup_task(self, task: dict[str, object], *, now_value: datetime | None) -> FollowupTaskSnapshot:
        summary_label, summary_text = self._task_summary(task)
        scheduler = _task_scheduler(task)
        due_at_raw = _optional_text(scheduler.get("leader_followup_due_at")) or ""
        return FollowupTaskSnapshot(
            task_id=str(task["id"]),
            job_id=str(task["job_id"]),
            state=str(task.get("state") or "queued"),
            notify_target=_optional_text(task.get("notify_target")) or self._messages["common"]["unknown"],
            final_notified_at=_format_timestamp(str(scheduler.get("final_notified_at") or ""), fallback=self._messages["common"]["unknown"]),
            due_at=_format_timestamp(due_at_raw, fallback=self._messages["common"]["unknown"]),
            is_overdue=_is_overdue(due_at_raw, now_value),
            summary_label=summary_label,
            summary_text=summary_text,
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


def _task_scheduler(task: dict[str, object]) -> dict[str, object]:
    scheduler = task.get("_scheduler")
    return scheduler if isinstance(scheduler, dict) else {}


def _is_overdue(value: str | None, now_value: datetime | None) -> bool:
    if not value or now_value is None:
        return False
    due_at = _parse_timestamp(value)
    return bool(due_at and due_at <= now_value)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_display_text(value: object) -> str | None:
    text = _optional_text(value)
    return _normalize_display_text(text) if text is not None else None


def _normalize_display_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" not in normalized and "\\r" not in normalized:
        return normalized
    return normalized.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _format_timestamp(value: str, *, fallback: str) -> str:
    if not value:
        return fallback
    parsed = _parse_timestamp(value)
    if parsed is None:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _detail_preview_status(path_value: str) -> str:
    if not path_value:
        return "missing"

    path = Path(path_value)
    if not path.is_file():
        return "missing"

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:  # pragma: no cover
        return "error"

    return "empty" if not raw_text.strip() else "rendered"


def _load_detail_preview(path_value: str) -> DetailPreview:
    if not path_value:
        return DetailPreview(status="missing", path=path_value)

    path = Path(path_value)
    if not path.is_file():
        return DetailPreview(status="missing", path=path_value)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        return DetailPreview(status="error", path=path_value, error_message=str(exc))

    if not raw_text.strip():
        return DetailPreview(status="empty", path=path_value)

    preview_text, is_truncated = _clamp_preview_text(raw_text)
    blocks = _parse_markdown_blocks(preview_text)
    if not blocks:
        return DetailPreview(status="empty", path=path_value, is_truncated=is_truncated)

    return DetailPreview(
        status="rendered",
        path=path_value,
        blocks=tuple(blocks),
        is_truncated=is_truncated,
    )


def _clamp_preview_text(text: str) -> tuple[str, bool]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    is_truncated = False
    if len(lines) > DETAIL_PREVIEW_LINE_LIMIT:
        lines = lines[:DETAIL_PREVIEW_LINE_LIMIT]
        is_truncated = True
    limited = "\n".join(lines)
    if len(limited) > DETAIL_PREVIEW_CHAR_LIMIT:
        limited = limited[:DETAIL_PREVIEW_CHAR_LIMIT].rstrip()
        is_truncated = True
    return limited.strip(), is_truncated


def _parse_markdown_blocks(text: str) -> list[DetailPreviewBlock]:
    if not text:
        return []

    blocks: list[DetailPreviewBlock] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    quote_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append(DetailPreviewBlock(kind="paragraph", text=" ".join(paragraph_lines).strip()))
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append(DetailPreviewBlock(kind="list", items=tuple(list_items)))
            list_items = []

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            blocks.append(DetailPreviewBlock(kind="quote", text=" ".join(quote_lines).strip()))
            quote_lines = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            blocks.append(DetailPreviewBlock(kind="code", text="\n".join(code_lines).rstrip()))
            code_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if in_code:
            if line.startswith("```"):
                flush_code()
                in_code = False
                continue
            code_lines.append(raw_line)
            continue

        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_quote()
            in_code = True
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_quote()
            blocks.append(
                DetailPreviewBlock(
                    kind="heading",
                    text=heading.group(2).strip(),
                    level=len(heading.group(1)),
                )
            )
            continue

        list_item = re.match(r"^[-*]\s+(.+)$", line)
        if list_item:
            flush_paragraph()
            flush_quote()
            list_items.append(list_item.group(1).strip())
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote and quote.group(1).strip():
            flush_paragraph()
            flush_list()
            quote_lines.append(quote.group(1).strip())
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_quote()
            continue

        paragraph_lines.append(line.strip())

    flush_paragraph()
    flush_list()
    flush_quote()
    if in_code:
        flush_code()
    return blocks
