from __future__ import annotations

from typing import TYPE_CHECKING

from .detail_preview import load_detail_preview as _load_detail_preview
from .formatting import (
    format_timestamp_for_client as _format_timestamp_for_client,
    optional_display_text as _optional_display_text,
    optional_text as _optional_text,
    truncate as _truncate,
)
from .snapshots import DetailBackLink, RecentUpdate, TaskDetailSnapshot, TaskTimelineEvent

if TYPE_CHECKING:
    from .queries import DashboardQueryService


TASK_CARD_STATES = ("running", "blocked", "failed", "queued", "done")


class TaskDisplayQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build_recent_update(self, task: dict[str, object]) -> RecentUpdate:
        summary_label, summary_text = self.task_summary(task)
        agent = self._service._agent_presentation(
            task.get("assigned_agent"),
            empty_label=self._messages["recent_update"]["unassigned"],
        )
        updated_at = _format_timestamp_for_client(
            str(task.get("updatedAt") or task.get("createdAt") or ""),
            fallback=self._messages["common"]["unknown"],
        )
        return RecentUpdate(
            task_id=str(task["id"]),
            job_id=str(task["job_id"]),
            assigned_agent=agent.display_label,
            assigned_agent_raw=agent.raw_key,
            assigned_agent_fallback_kind=agent.fallback_kind,
            state=str(task.get("state") or "queued"),
            updated_at=updated_at.display,
            updated_at_iso=updated_at.raw_iso,
            summary_label=summary_label,
            summary_text=summary_text,
            detail_href=self._service._jobs_path(
                job_id=str(task["job_id"]),
                task_id=str(task["id"]),
            )
            + "#job-task-detail",
        )

    def build_task_detail(
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
        detail_path_display = self._messages["tasks"]["detail_path_available"] if detail_path else self._messages["tasks"]["detail_path_unavailable"]
        resolved_back_links = (
            back_links
            if back_links is not None
            else TasksPageQueryAssembler(self._service)._build_task_back_links(
                task_id=str(task["id"]),
                job_id=job_id,
                selected_job_id=selected_job_id,
                selected_state=selected_state,
                selected_agent=selected_agent,
                selected_page=selected_page,
            )
        )
        agent = self._service._agent_presentation(
            task.get("assigned_agent"),
            empty_label=self._messages["tasks"]["assigned_agent_empty"],
        )
        created_at = _format_timestamp_for_client(
            str(task.get("createdAt") or ""),
            fallback=self._messages["common"]["unknown"],
        )
        updated_at = _format_timestamp_for_client(
            str(task.get("updatedAt") or task.get("createdAt") or ""),
            fallback=self._messages["common"]["unknown"],
        )
        return TaskDetailSnapshot(
            task_id=str(task["id"]),
            job_id=job_id,
            job_href=job_href or self._service._jobs_path(job_id=job_id, task_id=str(task["id"])) + "#job-task-detail",
            state=str(task.get("state") or "queued"),
            assigned_agent=agent.display_label,
            assigned_agent_raw=agent.raw_key,
            assigned_agent_fallback_kind=agent.fallback_kind,
            notify_target=_optional_text(task.get("notify_target")) or self._messages["common"]["unknown"],
            created_at=created_at.display,
            created_at_iso=created_at.raw_iso,
            updated_at=updated_at.display,
            updated_at_iso=updated_at.raw_iso,
            requirement=_optional_display_text(task.get("requirement")) or self._messages["common"]["unknown"],
            result=_optional_display_text(task.get("result")),
            detail_path=detail_path,
            detail_path_display=detail_path_display,
            detail_status_label=self._messages["tasks"]["detail_status_labels"][detail_preview.status],
            detail_preview=detail_preview,
            timeline=self.build_task_timeline(task),
            back_links=resolved_back_links,
        )

    def build_task_timeline(self, task: dict[str, object]) -> list[TaskTimelineEvent]:
        status_messages = self._messages["status"]
        tasks_messages = self._messages["tasks"]
        recent_label, recent_summary = self.task_summary(task)
        state = str(task.get("state") or "queued")
        state_label = status_messages.get(state, status_messages["queued"])["label"]
        agent = self._service._agent_presentation(
            task.get("assigned_agent"),
            empty_label=tasks_messages["assigned_agent_empty"],
        )
        target = _optional_text(task.get("notify_target")) or self._messages["common"]["unknown"]

        events: list[tuple[str, int, TaskTimelineEvent]] = []
        created_at = str(task.get("createdAt") or "")
        if created_at:
            created_at_display = _format_timestamp_for_client(
                created_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    created_at,
                    0,
                    TaskTimelineEvent(
                        key="created",
                        title=tasks_messages["timeline_created"],
                        timestamp_iso=created_at_display.raw_iso,
                        timestamp_display=created_at_display.display,
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
            updated_at_display = _format_timestamp_for_client(
                updated_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    updated_at,
                    1,
                    TaskTimelineEvent(
                        key="updated",
                        title=tasks_messages["timeline_updated"],
                        timestamp_iso=updated_at_display.raw_iso,
                        timestamp_display=updated_at_display.display,
                        note=tasks_messages["timeline_updated_note"].format(
                            state_label=state_label,
                            summary_label=recent_label,
                            summary=_truncate(recent_summary, 140),
                        ),
                    ),
                )
            )

        scheduler = task_scheduler(task)
        dispatch_at = _optional_text(scheduler.get("last_dispatch_at"))
        if dispatch_at:
            dispatch_at_display = _format_timestamp_for_client(
                dispatch_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    dispatch_at,
                    2,
                    TaskTimelineEvent(
                        key="dispatch",
                        title=tasks_messages["timeline_dispatch"],
                        timestamp_iso=dispatch_at_display.raw_iso,
                        timestamp_display=dispatch_at_display.display,
                        note=tasks_messages["timeline_dispatch_note"].format(agent=agent.display_label),
                    ),
                )
            )

        final_notified_at = _optional_text(scheduler.get("final_notified_at"))
        if final_notified_at:
            final_notified_display = _format_timestamp_for_client(
                final_notified_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    final_notified_at,
                    3,
                    TaskTimelineEvent(
                        key="final-notified",
                        title=tasks_messages["timeline_final_notified"],
                        timestamp_iso=final_notified_display.raw_iso,
                        timestamp_display=final_notified_display.display,
                        note=tasks_messages["timeline_final_notified_note"].format(target=target),
                    ),
                )
            )

        followup_due_at = _optional_text(scheduler.get("leader_followup_due_at"))
        if followup_due_at:
            followup_due_display = _format_timestamp_for_client(
                followup_due_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    followup_due_at,
                    4,
                    TaskTimelineEvent(
                        key="followup-due",
                        title=tasks_messages["timeline_followup_due"],
                        timestamp_iso=followup_due_display.raw_iso,
                        timestamp_display=followup_due_display.display,
                        note=tasks_messages["timeline_followup_due_note"],
                    ),
                )
            )

        followup_sent_at = _optional_text(scheduler.get("leader_followup_sent_at"))
        if followup_sent_at:
            followup_sent_display = _format_timestamp_for_client(
                followup_sent_at,
                fallback=self._messages["common"]["unknown"],
            )
            events.append(
                (
                    followup_sent_at,
                    5,
                    TaskTimelineEvent(
                        key="followup-sent",
                        title=tasks_messages["timeline_followup_sent"],
                        timestamp_iso=followup_sent_display.raw_iso,
                        timestamp_display=followup_sent_display.display,
                        note=tasks_messages["timeline_followup_sent_note"],
                    ),
                )
            )

        events.sort(key=lambda item: (item[0], item[1]))
        return [event for _, _, event in events]

    def task_summary(self, task: dict[str, object]) -> tuple[str, str]:
        result_text = _optional_display_text(task.get("result"))
        requirement_text = _optional_display_text(task.get("requirement"))
        if result_text:
            return self._messages["recent_update"]["result"], _truncate(result_text, 180)
        if requirement_text:
            return self._messages["recent_update"]["requirement"], _truncate(requirement_text, 180)
        return self._messages["recent_update"]["update"], self._messages["recent_update"]["no_detail"]

    def sort_tasks_for_cards(self, tasks: list[dict[str, object]]) -> list[dict[str, object]]:
        ordered = sorted(
            tasks,
            key=lambda item: (
                str(item.get("updatedAt") or item.get("createdAt") or ""),
                str(item["job_id"]),
                str(item["id"]),
            ),
            reverse=True,
        )
        ordered.sort(key=lambda item: task_state_priority(str(item.get("state") or "queued")))
        return ordered


def resolve_selected_task(
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


def task_scheduler(task: dict[str, object]) -> dict[str, object]:
    scheduler = task.get("_scheduler")
    return scheduler if isinstance(scheduler, dict) else {}


def task_state_priority(state: str) -> int:
    try:
        return TASK_CARD_STATES.index(state)
    except ValueError:
        return len(TASK_CARD_STATES)
