from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from task_bridge.runtime import PendingLeaderFollowupJob, collect_pending_leader_followup_jobs

from .formatting import (
    format_timestamp as _format_timestamp,
    is_overdue as _is_overdue,
    optional_text as _optional_text,
    parse_timestamp as _parse_timestamp,
)
from .pagination import paginate_items
from .pagination import parse_page_number as _parse_page_number
from .snapshots import (
    AlertTaskGroup,
    AlertTaskSnapshot,
    AlertsSnapshot,
    FollowupTaskGroup,
    FollowupTaskSnapshot,
)

if TYPE_CHECKING:
    from .queries import DashboardQueryService


ALERT_TASK_STATES = {"blocked", "failed"}
ALERT_LIST_PAGE_SIZE = 8


class AlertsPageQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build(
        self,
        *,
        risk_page: str | None,
        followup_page: str | None,
    ) -> AlertsSnapshot:
        self._service.store.list_jobs()
        tasks = self._service.store.list_tasks(all_jobs=True)
        current_job_id = self._service.store.get_current_job_id()
        status_counts = Counter(str(task.get("state") or "queued") for task in tasks)
        now_value = _parse_timestamp(self._service._now_provider())
        risk_tasks_all = [
            self._build_alert_task(task)
            for task in self._service._sort_tasks_for_cards(
                [task for task in tasks if str(task.get("state") or "queued") in ALERT_TASK_STATES]
            )
        ]
        followup_raw = self._followup_jobs(tasks, current_job_id=current_job_id, now_value=now_value)
        followups_all = [self._build_followup_task(group, now_value=now_value) for group in followup_raw]

        risk_page_number = _parse_page_number(risk_page)
        followup_page_number = _parse_page_number(followup_page)
        risk_tasks, risk_pagination = paginate_items(
            risk_tasks_all,
            page=risk_page_number,
            per_page=ALERT_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._alerts_path(
                risk_page=page_number,
                followup_page=followup_page_number,
            )
            + "#alerts-risk-list",
        )
        followups, followup_pagination = paginate_items(
            followups_all,
            page=followup_page_number,
            per_page=ALERT_LIST_PAGE_SIZE,
            href_builder=lambda page_number: self._alerts_path(
                risk_page=risk_pagination.page,
                followup_page=page_number,
            )
            + "#alerts-followups",
        )
        return AlertsSnapshot(
            home_path=self._service.home_path,
            current_job_id=current_job_id,
            generated_at=_format_timestamp(
                self._service._now_provider(),
                fallback=self._messages["common"]["unknown"],
            ),
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

    def _alerts_path(
        self,
        *,
        risk_page: int | None = None,
        followup_page: int | None = None,
    ) -> str:
        return self._service._path_with_locale(
            "/alerts",
            ("risk_page", str(risk_page) if risk_page and risk_page > 1 else ""),
            ("followup_page", str(followup_page) if followup_page and followup_page > 1 else ""),
        )

    def _followup_jobs(
        self,
        tasks: list[dict[str, object]],
        *,
        current_job_id: str | None,
        now_value: datetime | None,
    ) -> list[PendingLeaderFollowupJob]:
        followup_jobs = [
            group
            for group in collect_pending_leader_followup_jobs(
                tasks,
                current_job_id=current_job_id,
                current_time=now_value,
            )
            if group.is_current_job and not group.has_newer_task
        ]

        followup_jobs.sort(
            key=lambda item: self._followup_sort_key(item, now_value=now_value),
        )
        return followup_jobs

    def _followup_sort_key(
        self,
        group: PendingLeaderFollowupJob,
        *,
        now_value: datetime | None,
    ) -> tuple[int, str, str, str]:
        due_at = group.latest_due_at
        return (
            0 if _is_overdue(due_at, now_value) else 1,
            due_at,
            group.job_id,
            str(group.latest_task["id"]),
        )

    def _build_alert_task(self, task: dict[str, object]) -> AlertTaskSnapshot:
        summary_label, summary_text = self._service._task_summary(task)
        task_id = str(task["id"])
        job_id = str(task["job_id"])
        agent = self._service._agent_presentation(
            task.get("assigned_agent"),
            empty_label=self._messages["recent_update"]["unassigned"],
        )
        return AlertTaskSnapshot(
            task_id=task_id,
            job_id=job_id,
            assigned_agent=agent.display_label,
            assigned_agent_raw=agent.raw_key,
            assigned_agent_fallback_kind=agent.fallback_kind,
            state=str(task.get("state") or "queued"),
            updated_at=_format_timestamp(
                str(task.get("updatedAt") or task.get("createdAt") or ""),
                fallback=self._messages["common"]["unknown"],
            ),
            summary_label=summary_label,
            summary_text=summary_text,
            detail_href=self._service._tasks_path(job_id=job_id, task_id=task_id) + "#tasks-detail",
        )

    def _build_followup_task(
        self,
        group: PendingLeaderFollowupJob,
        *,
        now_value: datetime | None,
    ) -> FollowupTaskSnapshot:
        task = group.latest_task
        summary_label, summary_text = self._service._task_summary(task)
        due_at_raw = group.latest_due_at
        task_id = str(task["id"])
        job_id = group.job_id
        return FollowupTaskSnapshot(
            task_id=task_id,
            job_id=job_id,
            state=str(task.get("state") or "queued"),
            notify_target=_optional_text(task.get("notify_target")) or self._messages["common"]["unknown"],
            final_notified_at=_format_timestamp(
                group.latest_final_notified_at,
                fallback=self._messages["common"]["unknown"],
            ),
            due_at=_format_timestamp(due_at_raw, fallback=self._messages["common"]["unknown"]),
            is_overdue=_is_overdue(due_at_raw, now_value),
            summary_label=summary_label,
            summary_text=summary_text,
            detail_href=self._service._tasks_path(job_id=job_id, task_id=task_id) + "#tasks-detail",
        )

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
