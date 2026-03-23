from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .detail_preview import detail_preview_status as _detail_preview_status
from .formatting import format_timestamp as _format_timestamp
from .formatting import optional_text as _optional_text
from .pagination import page_for_task as _page_for_task
from .pagination import paginate_items
from .pagination import parse_page_number as _parse_page_number
from .snapshots import AppliedFilter, DetailBackLink, FilterGroup, LinkOption, TaskListGroup, TaskListItem, TaskStatusMetric, TasksPageSnapshot

if TYPE_CHECKING:
    from .queries import DashboardQueryService


class TasksPageQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build(
        self,
        *,
        selected_task_id: str | None,
        selected_job_id: str | None,
        selected_state: str | None,
        selected_agent: str | None,
        selected_page: str | None,
    ) -> TasksPageSnapshot:
        from .queries import CORE_TASK_STATES, TASK_LIST_PAGE_SIZE

        jobs = self._service.store.list_jobs()
        tasks = self._service._sort_tasks_for_cards(self._service.store.list_tasks(all_jobs=True))

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
        resolved_task, selection_missing = self._service._resolve_selected_task(
            filtered_tasks,
            selected_task_id,
            selected_job_id,
        )
        page = _parse_page_number(selected_page)
        if resolved_task is not None:
            page = _page_for_task(filtered_tasks, str(resolved_task["id"]), per_page=TASK_LIST_PAGE_SIZE)
        paged_tasks, pagination = paginate_items(
            filtered_tasks,
            page=page,
            per_page=TASK_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._service._tasks_path(
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
                href=self._service._tasks_path(
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
            home_path=self._service.home_path,
            current_job_id=self._service.store.get_current_job_id(),
            generated_at=_format_timestamp(
                self._service._now_provider(),
                fallback=self._messages["common"]["unknown"],
            ),
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
            clear_filters_href=self._service._tasks_path() + "#tasks-registry",
            tasks=task_rows,
            task_groups=self._build_task_list_groups(task_rows),
            visible_status_metrics=self._build_task_status_metrics(filtered_tasks),
            pagination=pagination,
            selected_task=self._service._build_task_detail(
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
        summary_label, summary_text = self._service._task_summary(task)
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
            detail_href=self._service._tasks_path(
                job_id=selected_job_id or job_id,
                task_id=task_id,
                state=selected_state,
                agent=selected_agent,
                page=selected_page,
            )
            + "#tasks-detail",
            job_href=self._service._jobs_path(job_id=job_id, task_id=task_id) + "#job-task-detail",
            is_selected=task_id == resolved_task_id,
        )

    def _task_matches_filters(
        self,
        task: dict[str, object],
        *,
        job_id: str | None = None,
        state: str | None = None,
        agent: str | None = None,
    ) -> bool:
        from .queries import UNASSIGNED_AGENT_FILTER

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
        from .queries import CORE_TASK_STATES, UNASSIGNED_AGENT_FILTER

        common = self._messages["common"]
        task_messages = self._messages["tasks"]
        job_options = [
            LinkOption(
                key="all",
                label=common["all"],
                href=self._service._tasks_path(state=selected_state, agent=selected_agent) + "#tasks-registry",
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
                    href=self._service._tasks_path(job_id=job_id, state=selected_state, agent=selected_agent)
                    + "#tasks-registry",
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
                href=self._service._tasks_path(job_id=selected_job_id, agent=selected_agent) + "#tasks-registry",
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
                    href=self._service._tasks_path(job_id=selected_job_id, state=state, agent=selected_agent)
                    + "#tasks-registry",
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
                href=self._service._tasks_path(job_id=selected_job_id, state=selected_state) + "#tasks-registry",
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
                    href=self._service._tasks_path(
                        job_id=selected_job_id,
                        state=selected_state,
                        agent=UNASSIGNED_AGENT_FILTER,
                    )
                    + "#tasks-registry",
                    is_active=selected_agent == UNASSIGNED_AGENT_FILTER,
                    count=unassigned_count,
                )
            )
        known_agents = self._service._worker_roster(
            (_optional_text(task.get("assigned_agent")) or "" for task in tasks),
            include_agents=(selected_agent,) if selected_agent and selected_agent != UNASSIGNED_AGENT_FILTER else (),
        )
        for agent_name in known_agents:
            agent_options.append(
                LinkOption(
                    key=agent_name,
                    label=agent_name,
                    href=self._service._tasks_path(
                        job_id=selected_job_id,
                        state=selected_state,
                        agent=agent_name,
                    )
                    + "#tasks-registry",
                    is_active=agent_name == selected_agent,
                    count=sum(
                        1
                        for task in tasks
                        if self._task_matches_filters(
                            task,
                            job_id=selected_job_id,
                            state=selected_state,
                            agent=agent_name,
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
                href=self._service._tasks_path(
                    job_id=selected_job_id,
                    state=selected_state,
                    agent=selected_agent,
                    page=selected_page,
                )
                + "#tasks-registry",
            )
        ]
        job_link = self._service._jobs_path(job_id=job_id, task_id=task_id) + "#job-task-detail"
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
        from .queries import UNASSIGNED_AGENT_FILTER

        applied: list[AppliedFilter] = []
        if selected_job_id:
            selected_job = next((job for job in jobs if str(job["id"]) == selected_job_id), None)
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["job_id"],
                    value=str(selected_job.get("title") or selected_job_id) if selected_job else selected_job_id,
                    clear_href=self._service._tasks_path(state=selected_state, agent=selected_agent)
                    + "#tasks-registry",
                )
            )
        if selected_state:
            applied.append(
                AppliedFilter(
                    label=self._messages["tasks"]["state"],
                    value=self._messages["status"][selected_state]["label"],
                    clear_href=self._service._tasks_path(job_id=selected_job_id, agent=selected_agent)
                    + "#tasks-registry",
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
                    clear_href=self._service._tasks_path(job_id=selected_job_id, state=selected_state)
                    + "#tasks-registry",
                )
            )
        return applied

    def _build_task_list_groups(self, tasks: list[TaskListItem]) -> list[TaskListGroup]:
        from .queries import TASK_CARD_STATES

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
        from .queries import TASK_CARD_STATES

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
