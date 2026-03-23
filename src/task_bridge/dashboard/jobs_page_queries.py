from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from .detail_preview import load_detail_preview as _load_detail_preview
from .formatting import (
    file_timestamp_iso as _file_timestamp_iso,
    format_timestamp as _format_timestamp,
    optional_text as _optional_text,
    parse_timestamp as _parse_timestamp,
)
from .snapshots import (
    DetailBackLink,
    JobDispatchTimelineNode,
    JobDetailSnapshot,
    JobListItem,
    JobsPageSnapshot,
    JobTaskGroup,
    JobTaskPreview,
    LinkOption,
    TaskStatusMetric,
    WorkPlanSnapshot,
)

if TYPE_CHECKING:
    from .queries import DashboardQueryService


class JobsPageQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build(
        self,
        *,
        selected_job_id: str | None,
        selected_task_id: str | None,
        selected_view: str | None,
        selected_detail_view: str | None,
    ) -> JobsPageSnapshot:
        from .queries import ACTIVE_TASK_STATES, JOB_VIEW_OPTIONS, TERMINAL_TASK_STATES

        jobs = self._service.store.list_jobs()
        tasks = self._service.store.list_tasks(all_jobs=True)
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
        if selected_task_id:
            resolved_task, _ = self._service._resolve_selected_task(
                selected_job_tasks,
                selected_task_id,
                resolved_job_id,
            )
        detail_back_link = self._build_detail_back_link(
            job=selected_job_raw,
            active_view=active_view,
            active_detail_view=active_detail_view,
            has_selected_task=resolved_task is not None,
        )

        return JobsPageSnapshot(
            home_path=self._service.home_path,
            current_job_id=self._service.store.get_current_job_id(),
            generated_at=_format_timestamp(
                self._service._now_provider(),
                fallback=self._messages["common"]["unknown"],
            ),
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
            selected_task=self._service._build_task_detail(
                resolved_task,
                selected_job_id=resolved_job_id,
                back_links=[],
                job_href=self._service._jobs_path(
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

    def _build_detail_back_link(
        self,
        *,
        job: dict[str, object] | None,
        active_view: str,
        active_detail_view: str,
        has_selected_task: bool,
    ) -> DetailBackLink | None:
        if job is None:
            return None

        if has_selected_task:
            is_current = bool(job.get("is_current"))
            detail_view = active_detail_view if is_current and active_detail_view == "plan" else None
            anchor = "#job-work-plan" if detail_view == "plan" else "#job-detail"
            return DetailBackLink(
                label=self._messages["tasks"]["back_to_job"],
                href=self._service._jobs_path(
                    job_id=str(job["id"]),
                    view=active_view,
                    detail_view=detail_view,
                )
                + anchor,
            )

        return DetailBackLink(
            label=self._messages["jobs"]["back_to_list"],
            href=self._service._jobs_path(view=active_view) + "#jobs-registry",
        )

    def _build_job_row(
        self,
        job: dict[str, object],
        *,
        job_tasks: list[dict[str, object]],
        selected_job_id: str | None,
        active_view: str,
    ) -> JobListItem:
        from .queries import ACTIVE_TASK_STATES, TERMINAL_TASK_STATES

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
            detail_href=self._service._jobs_path(job_id=job_id, view=active_view) + "#job-detail",
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
        from .queries import ACTIVE_TASK_STATES, CORE_TASK_STATES, TERMINAL_TASK_STATES

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
                assigned_agent=agent.display_label,
                assigned_agent_raw=agent.raw_key,
                assigned_agent_fallback_kind=agent.fallback_kind,
                updated_at=_format_timestamp(
                    str(task.get("updatedAt") or task.get("createdAt") or ""),
                    fallback=self._messages["common"]["unknown"],
                ),
                summary_label=summary_label,
                summary_text=summary_text,
                detail_href=self._service._jobs_path(
                    job_id=str(task["job_id"]),
                    task_id=str(task["id"]),
                    view=active_view,
                )
                + "#job-task-detail",
                is_selected=str(task["id"]) == selected_task_id,
            )
            for task, agent, (summary_label, summary_text) in [
                (
                    task,
                    self._service._agent_presentation(
                        task.get("assigned_agent"),
                        empty_label=self._messages["tasks"]["assigned_agent_empty"],
                    ),
                    self._service._task_summary(task),
                )
                for task in self._service._sort_tasks_for_cards(job_tasks)
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
            tasks_href=self._service._tasks_path(job_id=str(job["id"])) + "#tasks-registry",
            latest_task_href=latest_task_href,
            task_status_metrics=status_metrics,
            timeline=self._build_job_timeline(job_tasks, active_view=active_view),
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

    def _build_job_timeline(
        self,
        job_tasks: list[dict[str, object]],
        *,
        active_view: str,
    ) -> list[JobDispatchTimelineNode]:
        from .queries import _task_scheduler

        status_messages = self._messages["status"]
        task_messages = self._messages["tasks"]

        timeline_tasks = sorted(
            (
                task
                for task in job_tasks
                if _optional_text(_task_scheduler(task).get("last_dispatch_at"))
            ),
            key=lambda item: (
                str(_task_scheduler(item).get("last_dispatch_at") or ""),
                str(item.get("createdAt") or ""),
                str(item["id"]),
            ),
        )
        newest_index = len(timeline_tasks) - 1
        nodes: list[JobDispatchTimelineNode] = []
        for index, task in enumerate(timeline_tasks):
            dispatch_at = _optional_text(_task_scheduler(task).get("last_dispatch_at"))
            if not dispatch_at:
                continue

            state = str(task.get("state") or "queued")
            dispatch_date_display, dispatch_time_display = self._format_dispatch_parts(dispatch_at)
            task_id = str(task["id"])
            agent = self._service._agent_presentation(
                task.get("assigned_agent"),
                empty_label=task_messages["assigned_agent_empty"],
            )
            nodes.append(
                JobDispatchTimelineNode(
                    task_id=task_id,
                    task_short_id=self._short_task_id(task_id),
                    assigned_agent=agent.display_label,
                    assigned_agent_raw=agent.raw_key,
                    assigned_agent_fallback_kind=agent.fallback_kind,
                    state=state,
                    state_label=status_messages.get(state, status_messages["queued"])["label"],
                    dispatch_at_iso=dispatch_at,
                    dispatch_at_full=_format_timestamp(
                        dispatch_at,
                        fallback=self._messages["common"]["unknown"],
                    ),
                    dispatch_date_display=dispatch_date_display,
                    dispatch_time_display=dispatch_time_display,
                    detail_href=self._service._jobs_path(
                        job_id=str(task["job_id"]),
                        task_id=task_id,
                        view=active_view,
                    )
                    + "#job-task-detail",
                    is_newest=index == newest_index,
                )
            )
        return nodes

    def _format_dispatch_parts(self, value: str) -> tuple[str, str]:
        parsed = _parse_timestamp(value)
        if parsed is None:
            fallback = value or self._messages["common"]["unknown"]
            return fallback, ""
        return parsed.strftime("%m-%d"), parsed.strftime("%H:%M UTC")

    @staticmethod
    def _short_task_id(task_id: str) -> str:
        suffix = task_id.rsplit("-", 1)[-1]
        return f"#{suffix}"

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

    def _job_matches_view(
        self,
        job: dict[str, object],
        job_tasks: list[dict[str, object]],
        selected_view: str,
    ) -> bool:
        from .queries import ACTIVE_TASK_STATES, TERMINAL_TASK_STATES

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
        from .queries import JOB_VIEW_OPTIONS

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
                href=self._service._jobs_path(
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
        from .queries import JOB_DETAIL_VIEW_OPTIONS

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
                href=self._service._jobs_path(
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
                href=self._service._jobs_path(
                    job_id=job_id,
                    view=active_view,
                    detail_view="plan",
                )
                + "#job-work-plan",
                is_active=active_detail_view == "plan",
            ),
        ]

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

    def _build_job_task_groups(self, tasks: list[JobTaskPreview]) -> list[JobTaskGroup]:
        from .queries import TASK_CARD_STATES

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
