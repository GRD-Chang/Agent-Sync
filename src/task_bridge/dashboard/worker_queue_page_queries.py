from __future__ import annotations

from typing import TYPE_CHECKING

from task_bridge.store import queue_for_agent

from .formatting import format_timestamp as _format_timestamp
from .formatting import optional_text as _optional_text
from .snapshots import QueueTaskSnapshot, WorkerLaneSnapshot, WorkerQueueSnapshot

if TYPE_CHECKING:
    from .queries import DashboardQueryService


class WorkerQueuePageQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build(self) -> WorkerQueueSnapshot:
        tasks = self._service.store.list_tasks(all_jobs=True)
        worker_rows = self._service._worker_status_rows(tasks)
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
                running_label, running_text = self._service._task_summary(running_task)
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
            home_path=self._service.home_path,
            current_job_id=self._service.store.get_current_job_id(),
            generated_at=_format_timestamp(
                self._service._now_provider(),
                fallback=self._messages["common"]["unknown"],
            ),
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

    def _build_queue_task(self, task: dict[str, object]) -> QueueTaskSnapshot:
        summary_label, summary_text = self._service._task_summary(task)
        agent = self._service._agent_presentation(
            task.get("assigned_agent"),
            empty_label=self._messages["common"]["none"],
        )
        return QueueTaskSnapshot(
            task_id=str(task["id"]),
            job_id=str(task["job_id"]),
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
        )
