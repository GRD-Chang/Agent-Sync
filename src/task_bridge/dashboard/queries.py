from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from task_bridge.runtime import now_iso
from task_bridge.store import TaskStore, infer_worker_status, queue_for_agent

from .detail_preview import (
    detail_preview_status as _detail_preview_status,
    load_detail_preview as _load_detail_preview,
)
from .formatting import (
    file_timestamp_iso as _file_timestamp_iso,
    format_timestamp as _format_timestamp,
    is_overdue as _is_overdue,
    optional_display_text as _optional_display_text,
    optional_text as _optional_text,
    parse_timestamp as _parse_timestamp,
    truncate as _truncate,
)
from .i18n import DEFAULT_LOCALE, get_messages, resolve_locale
from .pagination import page_for_task as _page_for_task
from .pagination import paginate_items
from .pagination import parse_page_number as _parse_page_number
from .snapshots import (
    AlertTaskGroup,
    AlertTaskSnapshot,
    AlertsSnapshot,
    AppliedFilter,
    DetailBackLink,
    DetailPreview,
    FilterGroup,
    FollowupTaskGroup,
    FollowupTaskSnapshot,
    HealthCheck,
    HealthSnapshot,
    JobDetailSnapshot,
    JobListItem,
    JobsPageSnapshot,
    JobTaskGroup,
    JobTaskPreview,
    LinkOption,
    OverviewSnapshot,
    PaginationSnapshot,
    QueueTaskSnapshot,
    RecentUpdate,
    TaskDetailSnapshot,
    TaskListGroup,
    TaskListItem,
    TaskStatusMetric,
    TasksPageSnapshot,
    TaskTimelineEvent,
    WorkerLaneSnapshot,
    WorkerQueueSnapshot,
    WorkerSnapshot,
    WorkPlanSnapshot,
)

CORE_TASK_STATES = ["queued", "running", "done", "blocked", "failed"]
TASK_CARD_STATES = ("running", "blocked", "failed", "queued", "done")
ACTIVE_TASK_STATES = {"queued", "running"}
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
ALERT_TASK_STATES = {"blocked", "failed"}
RECENT_UPDATES_LIMIT = 6
JOB_VIEW_OPTIONS = ("all", "current", "active", "terminal")
JOB_DETAIL_VIEW_OPTIONS = ("tasks", "plan")
UNASSIGNED_AGENT_FILTER = "__unassigned__"
TASK_LIST_PAGE_SIZE = 12
ALERT_LIST_PAGE_SIZE = 8


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
                href=self._jobs_path(view=active_view) + "#jobs-registry",
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
        selected_job_tasks = tasks_by_job.get(resolved_job_id or "", [])
        active_detail_view = self._resolve_job_detail_view(selected_job_raw, selected_detail_view)
        resolved_task = None
        if active_detail_view == "tasks":
            resolved_task, _ = self._resolve_selected_task(selected_job_tasks, selected_task_id, resolved_job_id)

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
                selected_task_id=selected_task_id,
            ),
            jobs=job_rows,
            selected_job=self._build_job_detail(
                selected_job_raw,
                selected_job_tasks,
                active_view=active_view,
                active_detail_view=active_detail_view,
                selected_task_id=str(resolved_task["id"]) if resolved_task else None,
            )
            if selected_job_raw
            else None,
            selected_task=self._build_task_detail(
                resolved_task,
                selected_job_id=resolved_job_id,
                back_links=self._build_job_task_back_links(
                    job_id=resolved_job_id or "",
                    task_id=str(resolved_task["id"]),
                    active_view=active_view,
                ),
                job_href=self._jobs_path(
                    job_id=resolved_job_id,
                    task_id=str(resolved_task["id"]),
                    view=active_view,
                )
                + "#job-task-detail",
            )
            if resolved_task is not None and resolved_job_id is not None
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
        selected_page: str | None = None,
    ) -> TasksPageSnapshot:
        jobs = self.store.list_jobs()
        tasks = self._sort_tasks_for_cards(self.store.list_tasks(all_jobs=True))

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
        page = _parse_page_number(selected_page)
        if resolved_task is not None:
            page = _page_for_task(filtered_tasks, str(resolved_task["id"]), per_page=TASK_LIST_PAGE_SIZE)
        paged_tasks, pagination = paginate_items(
            filtered_tasks,
            page=page,
            per_page=TASK_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._tasks_path(
                job_id=selected_job_id,
                state=active_state,
                agent=active_agent,
                page=page_number,
            )
            + "#tasks-registry",
        )
        resolved_task_id = str(resolved_task["id"]) if resolved_task else None
        detail_back_link = (
            DetailBackLink(
                label=self._messages["tasks"]["back_to_list"],
                href=self._tasks_path(
                    job_id=selected_job_id,
                    state=active_state,
                    agent=active_agent,
                    page=pagination.page,
                )
                + "#tasks-registry",
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
                selected_page=pagination.page,
            )
            for task in paged_tasks
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
            clear_filters_href=self._tasks_path() + "#tasks-registry",
            tasks=task_rows,
            task_groups=self._build_task_list_groups(task_rows),
            visible_status_metrics=self._build_task_status_metrics(filtered_tasks),
            pagination=pagination,
            selected_task=self._build_task_detail(
                resolved_task,
                selected_job_id=selected_job_id,
                selected_state=active_state,
                selected_agent=active_agent,
                selected_page=pagination.page,
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

    def alerts(
        self,
        *,
        risk_page: str | None = None,
        followup_page: str | None = None,
    ) -> AlertsSnapshot:
        self.store.list_jobs()
        tasks = self.store.list_tasks(all_jobs=True)
        status_counts = Counter(str(task.get("state") or "queued") for task in tasks)
        now_value = _parse_timestamp(self._now_provider())
        risk_tasks_all = [
            self._build_alert_task(task)
            for task in self._sort_tasks_for_cards(
                [task for task in tasks if str(task.get("state") or "queued") in ALERT_TASK_STATES]
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
        followups_all = [self._build_followup_task(task, now_value=now_value) for task in followup_raw]
        risk_tasks, risk_pagination = paginate_items(
            risk_tasks_all,
            page=_parse_page_number(risk_page),
            per_page=ALERT_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._alerts_path(
                risk_page=page_number,
                followup_page=_parse_page_number(followup_page),
            )
            + "#alerts-risk-list",
        )
        followups, followup_pagination = paginate_items(
            followups_all,
            page=_parse_page_number(followup_page),
            per_page=ALERT_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._alerts_path(
                risk_page=risk_pagination.page,
                followup_page=page_number,
            )
            + "#alerts-followups",
        )
        return AlertsSnapshot(
            home_path=self.home_path,
            current_job_id=self.store.get_current_job_id(),
            generated_at=_format_timestamp(self._now_provider(), fallback=self._messages["common"]["unknown"]),
            blocked_count=status_counts.get("blocked", 0),
            failed_count=status_counts.get("failed", 0),
            pending_followups_count=len(followups_all),
            overdue_followups_count=sum(1 for task in followups_all if task.is_overdue),
            risk_tasks=risk_tasks,
            risk_groups=self._build_alert_risk_groups(risk_tasks),
            followup_tasks=followups,
            followup_groups=self._build_followup_groups(followups),
            risk_pagination=risk_pagination,
            followup_pagination=followup_pagination,
            has_alerts=bool(risk_tasks_all or followups_all),
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
            detail_href=self._jobs_path(
                job_id=str(task["job_id"]),
                task_id=str(task["id"]),
            )
            + "#job-task-detail",
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
            detail_href=self._jobs_path(job_id=job_id, view=active_view) + "#job-detail",
        )

    def _build_job_detail(
        self,
        job: dict[str, object] | None,
        job_tasks: list[dict[str, object]],
        *,
        active_view: str,
        active_detail_view: str,
        selected_task_id: str | None,
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
                detail_href=self._jobs_path(
                    job_id=str(task["job_id"]),
                    task_id=str(task["id"]),
                    view=active_view,
                )
                + "#job-task-detail",
                is_selected=str(task["id"]) == selected_task_id,
            )
            for task, (summary_label, summary_text) in [
                (task, self._task_summary(task))
                for task in self._sort_tasks_for_cards(job_tasks)
            ]
        ]
        latest_task_href = task_previews[0].detail_href if task_previews else None
        is_current = bool(job.get("is_current"))
        work_plan = self._build_current_job_work_plan() if is_current else None

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
            is_current=is_current,
            task_count=len(job_tasks),
            active_task_count=sum(counts.get(state, 0) for state in ACTIVE_TASK_STATES),
            terminal_task_count=sum(counts.get(state, 0) for state in TERMINAL_TASK_STATES),
            tasks_href=self._tasks_path(job_id=str(job["id"])) + "#tasks-registry",
            latest_task_href=latest_task_href,
            task_status_metrics=status_metrics,
            task_previews=task_previews,
            detail_view=active_detail_view,
            detail_view_options=self._build_job_detail_view_options(
                job_id=str(job["id"]),
                active_view=active_view,
                active_detail_view=active_detail_view,
                selected_task_id=selected_task_id,
            )
            if is_current
            else [],
            task_groups=self._build_job_task_groups(task_previews),
            work_plan=work_plan,
        )

    def _build_task_row(
        self,
        task: dict[str, object],
        *,
        resolved_task_id: str | None,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
        selected_page: int,
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
                page=selected_page,
            )
            + "#tasks-detail",
            job_href=self._jobs_path(job_id=job_id, task_id=task_id) + "#job-task-detail",
            is_selected=task_id == resolved_task_id,
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
            or self._build_task_back_links(
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
        selected_task_id: str | None,
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
                href=self._jobs_path(
                    job_id=selected_job_id,
                    task_id=selected_task_id,
                    view=view_key,
                )
                + "#jobs-registry",
                is_active=view_key == active_view,
                count=sum(
                    1
                    for job in jobs
                    if self._job_matches_view(job, tasks_by_job.get(str(job["id"]), []), view_key)
                ),
            )
            for view_key in JOB_VIEW_OPTIONS
        ]

    @staticmethod
    def _resolve_job_detail_view(
        job: dict[str, object] | None,
        selected_detail_view: str | None,
    ) -> str:
        if job is None or not bool(job.get("is_current")):
            return "tasks"
        if selected_detail_view in JOB_DETAIL_VIEW_OPTIONS:
            return selected_detail_view
        return "tasks"

    def _build_job_detail_view_options(
        self,
        *,
        job_id: str,
        active_view: str,
        active_detail_view: str,
        selected_task_id: str | None,
    ) -> list[LinkOption]:
        messages = self._messages["jobs"]
        return [
            LinkOption(
                key="tasks",
                label=messages["detail_view_tasks"],
                href=self._jobs_path(
                    job_id=job_id,
                    task_id=selected_task_id,
                    view=active_view,
                    detail_view="tasks",
                )
                + "#job-task-groups",
                is_active=active_detail_view == "tasks",
            ),
            LinkOption(
                key="plan",
                label=messages["detail_view_plan"],
                href=self._jobs_path(
                    job_id=job_id,
                    view=active_view,
                    detail_view="plan",
                )
                + "#job-work-plan",
                is_active=active_detail_view == "plan",
            ),
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
                href=self._tasks_path(state=selected_state, agent=selected_agent) + "#tasks-registry",
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
                    href=self._tasks_path(job_id=job_id, state=selected_state, agent=selected_agent) + "#tasks-registry",
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
                href=self._tasks_path(job_id=selected_job_id, agent=selected_agent) + "#tasks-registry",
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
                    href=self._tasks_path(job_id=selected_job_id, state=state, agent=selected_agent) + "#tasks-registry",
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
                href=self._tasks_path(job_id=selected_job_id, state=selected_state) + "#tasks-registry",
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
                    )
                    + "#tasks-registry",
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
                    href=self._tasks_path(job_id=selected_job_id, state=selected_state, agent=agent) + "#tasks-registry",
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
        selected_page: int | None,
    ) -> list[DetailBackLink]:
        links = [
            DetailBackLink(
                label=self._messages["tasks"]["back_to_tasks"],
                href=self._tasks_path(
                    job_id=selected_job_id,
                    state=selected_state,
                    agent=selected_agent,
                    page=selected_page,
                )
                + "#tasks-registry",
            )
        ]
        job_link = self._jobs_path(job_id=job_id, task_id=task_id) + "#job-task-detail"
        links.append(DetailBackLink(label=self._messages["tasks"]["back_to_job"], href=job_link))
        return links

    def _build_job_task_back_links(
        self,
        *,
        job_id: str,
        task_id: str,
        active_view: str,
    ) -> list[DetailBackLink]:
        return [
            DetailBackLink(
                label=self._messages["jobs"]["back_to_task_groups"],
                href=self._jobs_path(job_id=job_id, view=active_view) + "#job-task-groups",
            ),
            DetailBackLink(
                label=self._messages["jobs"]["open_standalone_task"],
                href=self._tasks_path(job_id=job_id, task_id=task_id) + "#tasks-detail",
            ),
        ]

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
                    clear_href=self._tasks_path(state=selected_state, agent=selected_agent) + "#tasks-registry",
                )
            )
        if selected_state:
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["state"],
                    value=self._messages["status"][selected_state]["label"],
                    clear_href=self._tasks_path(job_id=selected_job_id, agent=selected_agent) + "#tasks-registry",
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
                    clear_href=self._tasks_path(job_id=selected_job_id, state=selected_state) + "#tasks-registry",
                )
            )
        return applied

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

    def _alerts_path(
        self,
        *,
        risk_page: int | None = None,
        followup_page: int | None = None,
    ) -> str:
        return self._path_with_locale(
            "/alerts",
            ("risk_page", str(risk_page) if risk_page and risk_page > 1 else ""),
            ("followup_page", str(followup_page) if followup_page and followup_page > 1 else ""),
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

    def _build_current_job_work_plan(self) -> WorkPlanSnapshot:
        work_plan_path = Path.home() / ".openclaw" / "agents" / "team-leader" / "memory" / "work-plan.md"
        path_value = str(work_plan_path)
        preview = _load_detail_preview(path_value)
        updated_at = _format_timestamp(
            _file_timestamp_iso(work_plan_path) or "",
            fallback=self._messages["common"]["unknown"],
        )
        return WorkPlanSnapshot(
            path=path_value,
            updated_at=updated_at,
            status_label=self._messages["tasks"]["detail_status_labels"][preview.status],
            detail_preview=preview,
        )

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

    def _build_job_task_groups(self, tasks: list[JobTaskPreview]) -> list[JobTaskGroup]:
        groups: list[JobTaskGroup] = []
        for state in TASK_CARD_STATES:
            grouped_tasks = [task for task in tasks if task.state == state]
            if not grouped_tasks:
                continue
            groups.append(
                JobTaskGroup(
                    state=state,
                    label=self._messages["status"][state]["label"],
                    description=self._messages["status"][state]["description"],
                    count=len(grouped_tasks),
                    tasks=grouped_tasks,
                )
            )
        return groups

    def _build_task_list_groups(self, tasks: list[TaskListItem]) -> list[TaskListGroup]:
        groups: list[TaskListGroup] = []
        for state in TASK_CARD_STATES:
            grouped_tasks = [task for task in tasks if task.state == state]
            if not grouped_tasks:
                continue
            groups.append(
                TaskListGroup(
                    state=state,
                    label=self._messages["status"][state]["label"],
                    description=self._messages["status"][state]["description"],
                    count=len(grouped_tasks),
                    tasks=grouped_tasks,
                )
            )
        return groups

    def _build_task_status_metrics(self, tasks: list[dict[str, object]]) -> list[TaskStatusMetric]:
        counts = Counter(str(task.get("state") or "queued") for task in tasks)
        return [
            TaskStatusMetric(
                state=state,
                label=self._messages["status"][state]["label"],
                description=self._messages["status"][state]["description"],
                count=counts.get(state, 0),
            )
            for state in TASK_CARD_STATES
        ]

    def _build_alert_risk_groups(self, tasks: list[AlertTaskSnapshot]) -> list[AlertTaskGroup]:
        groups: list[AlertTaskGroup] = []
        for state in ("blocked", "failed"):
            grouped_tasks = [task for task in tasks if task.state == state]
            if not grouped_tasks:
                continue
            groups.append(
                AlertTaskGroup(
                    state=state,
                    label=self._messages["status"][state]["label"],
                    description=self._messages["status"][state]["description"],
                    count=len(grouped_tasks),
                    tasks=grouped_tasks,
                )
            )
        return groups

    def _build_followup_groups(self, tasks: list[FollowupTaskSnapshot]) -> list[FollowupTaskGroup]:
        definitions = (
            ("due", self._messages["alerts"]["followup_due"], self._messages["status"]["blocked"]["description"]),
            (
                "scheduled",
                self._messages["alerts"]["followup_scheduled"],
                self._messages["alerts"]["followup_note"],
            ),
        )
        groups: list[FollowupTaskGroup] = []
        for state, label, description in definitions:
            grouped_tasks = [task for task in tasks if (task.is_overdue if state == "due" else not task.is_overdue)]
            if not grouped_tasks:
                continue
            groups.append(
                FollowupTaskGroup(
                    state=state,
                    label=label,
                    description=description,
                    count=len(grouped_tasks),
                    tasks=grouped_tasks,
                )
        )
        return groups


def _task_scheduler(task: dict[str, object]) -> dict[str, object]:
    scheduler = task.get("_scheduler")
    return scheduler if isinstance(scheduler, dict) else {}


def _task_state_priority(state: str) -> int:
    try:
        return TASK_CARD_STATES.index(state)
    except ValueError:
        return len(TASK_CARD_STATES)
