from __future__ import annotations

from dataclasses import dataclass

DETAIL_PREVIEW_LINE_LIMIT = 60
DETAIL_PREVIEW_CHAR_LIMIT = 5000


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
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    state: str
    updated_at: str
    updated_at_iso: str | None
    summary_label: str
    summary_text: str
    detail_href: str


@dataclass(frozen=True)
class OverviewSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    generated_at_iso: str | None
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
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
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
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    updated_at: str
    updated_at_iso: str | None
    summary_label: str
    summary_text: str
    detail_href: str
    is_selected: bool


@dataclass(frozen=True)
class JobTaskGroup:
    state: str
    label: str
    description: str
    count: int
    tasks: list[JobTaskPreview]


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
class WorkPlanSnapshot:
    path: str
    updated_at: str
    updated_at_iso: str | None
    status_label: str
    detail_preview: DetailPreview


@dataclass(frozen=True)
class JobDispatchTimelineNode:
    task_id: str
    task_short_id: str
    assigned_agent: str
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    state: str
    state_label: str
    dispatch_at_iso: str
    dispatch_at_display: str
    detail_href: str
    is_newest: bool


@dataclass(frozen=True)
class JobDetailSnapshot:
    job_id: str
    title: str
    notify_target: str
    created_at: str
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
    is_current: bool
    task_count: int
    active_task_count: int
    terminal_task_count: int
    tasks_href: str
    latest_task_href: str | None
    task_status_metrics: list[TaskStatusMetric]
    timeline: list[JobDispatchTimelineNode]
    task_previews: list[JobTaskPreview]
    detail_view: str
    detail_view_options: list[LinkOption]
    task_groups: list[JobTaskGroup]
    work_plan: WorkPlanSnapshot | None


@dataclass(frozen=True)
class TaskTimelineEvent:
    key: str
    title: str
    timestamp_iso: str | None
    timestamp_display: str
    note: str


@dataclass(frozen=True)
class TaskDetailSnapshot:
    task_id: str
    job_id: str
    job_href: str
    state: str
    assigned_agent: str
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    notify_target: str
    created_at: str
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
    requirement: str
    result: str | None
    detail_path: str
    detail_path_display: str
    detail_status_label: str
    detail_preview: DetailPreview
    timeline: list[TaskTimelineEvent]
    back_links: list[DetailBackLink]


@dataclass(frozen=True)
class JobsPageSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    generated_at_iso: str | None
    jobs_count: int
    tasks_count: int
    visible_jobs_count: int
    active_view: str
    view_options: list[LinkOption]
    jobs: list[JobListItem]
    pagination: PaginationSnapshot
    selected_job: JobDetailSnapshot | None
    selected_task: TaskDetailSnapshot | None
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
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    created_at: str
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
    summary_label: str
    summary_text: str
    detail_status_label: str
    detail_href: str
    job_href: str
    is_selected: bool


@dataclass(frozen=True)
class TaskListGroup:
    state: str
    label: str
    description: str
    count: int
    tasks: list[TaskListItem]


@dataclass(frozen=True)
class PaginationSnapshot:
    page: int
    page_count: int
    per_page: int
    total_items: int
    start_index: int
    end_index: int
    prev_href: str | None
    next_href: str | None
    page_links: list["PaginationLink"]


@dataclass(frozen=True)
class PaginationLink:
    label: str
    page: int | None
    href: str | None
    is_current: bool = False
    is_gap: bool = False


@dataclass(frozen=True)
class TasksPageSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    generated_at_iso: str | None
    jobs_count: int
    tasks_count: int
    visible_tasks_count: int
    filter_groups: list[FilterGroup]
    applied_filters: list[AppliedFilter]
    clear_filters_href: str
    tasks: list[TaskListItem]
    task_groups: list[TaskListGroup]
    visible_status_metrics: list[TaskStatusMetric]
    pagination: PaginationSnapshot
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
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    state: str
    updated_at: str
    updated_at_iso: str | None
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
    generated_at_iso: str | None
    worker_count: int
    busy_workers: int
    idle_workers: int
    running_tasks: int
    assigned_queue_depth: int
    unassigned_queue_depth: int
    lanes: list[WorkerLaneSnapshot]
    active_lanes: list[WorkerLaneSnapshot]
    quiet_lanes: list[WorkerLaneSnapshot]
    unassigned_queued_tasks: list[QueueTaskSnapshot]
    has_activity: bool


@dataclass(frozen=True)
class AlertTaskSnapshot:
    task_id: str
    job_id: str
    assigned_agent: str
    assigned_agent_raw: str | None
    assigned_agent_fallback_kind: str
    state: str
    updated_at: str
    updated_at_iso: str | None
    summary_label: str
    summary_text: str
    detail_href: str


@dataclass(frozen=True)
class FollowupTaskSnapshot:
    task_id: str
    job_id: str
    state: str
    notify_target: str
    final_notified_at: str
    final_notified_at_iso: str | None
    due_at: str
    due_at_iso: str | None
    is_overdue: bool
    summary_label: str
    summary_text: str
    detail_href: str


@dataclass(frozen=True)
class AlertTaskGroup:
    state: str
    label: str
    description: str
    count: int
    tasks: list[AlertTaskSnapshot]


@dataclass(frozen=True)
class FollowupTaskGroup:
    state: str
    label: str
    description: str
    count: int
    tasks: list[FollowupTaskSnapshot]


@dataclass(frozen=True)
class AlertsSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    generated_at_iso: str | None
    blocked_count: int
    failed_count: int
    pending_followups_count: int
    overdue_followups_count: int
    risk_tasks: list[AlertTaskSnapshot]
    failed_tasks: list[AlertTaskSnapshot]
    blocked_tasks: list[AlertTaskSnapshot]
    followup_tasks: list[FollowupTaskSnapshot]
    followup_groups: list[FollowupTaskGroup]
    failed_pagination: PaginationSnapshot
    blocked_pagination: PaginationSnapshot
    followup_pagination: PaginationSnapshot
    has_alerts: bool


@dataclass(frozen=True)
class HealthCheck:
    key: str
    label: str
    status: str
    detail: str
    detail_time_label: str | None = None
    detail_time_display: str | None = None
    detail_time_iso: str | None = None


@dataclass(frozen=True)
class HealthSnapshot:
    home_path: str
    current_job_id: str | None
    generated_at: str
    generated_at_iso: str | None
    jobs_count: int
    tasks_count: int
    worker_prompt_entries: int
    leader_last_running_notice_at: str
    leader_last_running_notice_at_iso: str | None
    checks: list[HealthCheck]
