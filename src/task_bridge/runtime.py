from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from .config import resolve_user_chat_id
from .prompts import load_prompts
from .store import TaskStore, now_iso, queue_for_agent

Sender = Callable[[str, str], object]
ResetSender = Callable[[str, str], object]
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
LEADER_UNRESOLVED_FOLLOWUP_SECONDS = 300.0
DISPATCH_BACKOFF_SECONDS = (300, 900, 1800, 3600)
MAX_DISPATCH_FAILURES_BEFORE_BLOCKED = 5
SEND_RETRY_AFTER_SECONDS = 60


@dataclass(frozen=True)
class SendResult:
    sent: bool
    pid: int | None = None
    reason: str | None = None
    error: dict[str, object] | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    returncode: int = 0
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0


class OpenClawCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        argv: list[str],
        returncode: int | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
        duration_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.argv = argv
        self.returncode = returncode
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.duration_ms = duration_ms

    def to_error_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": type(self).__name__,
            "message": str(self),
            "argv": self.argv,
        }
        if self.returncode is not None:
            payload["returncode"] = self.returncode
        if self.stdout_tail:
            payload["stdout_tail"] = self.stdout_tail
        if self.stderr_tail:
            payload["stderr_tail"] = self.stderr_tail
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        return payload


@dataclass
class DispatchOutcome:
    dispatched: list[str] = field(default_factory=list)
    skipped_busy: dict[str, str] = field(default_factory=dict)
    skipped_pending_claim: dict[str, str] = field(default_factory=dict)
    skipped_cooldown: dict[str, str] = field(default_factory=dict)
    skipped_blocked: dict[str, str] = field(default_factory=dict)
    dispatch_deferred: dict[str, dict[str, object]] = field(default_factory=dict)
    dispatch_failed: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class NotifyOutcome:
    notified: list[str] = field(default_factory=list)
    notify_failed: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class ReminderOutcome:
    worker_reminded: list[str] = field(default_factory=list)
    leader_pinged: bool = False


@dataclass
class LeaderFollowupOutcome:
    followed_up: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingLeaderFollowupJob:
    job_id: str
    tasks: tuple[dict[str, object], ...]
    latest_task: dict[str, object]
    latest_due_at: str
    latest_final_notified_at: str
    is_due: bool
    is_current_job: bool
    has_newer_task: bool


class BridgeRuntime:
    def __init__(
        self,
        home: Path | None = None,
        sender: Sender | None = None,
        reset_sender: ResetSender | None = None,
        leader_unresolved_followup_seconds: float = LEADER_UNRESOLVED_FOLLOWUP_SECONDS,
    ) -> None:
        if leader_unresolved_followup_seconds < 0:
            raise ValueError("leader-followup must be >= 0")
        self.store = TaskStore(home)
        self.sender = sender or default_openclaw_sender
        self.reset_sender = reset_sender or default_openclaw_reset_sender
        self.leader_unresolved_followup_seconds = leader_unresolved_followup_seconds
        self.user_chat_id = resolve_user_chat_id()
        self.prompts = load_prompts()

    @property
    def home(self) -> Path:
        return self.store.home

    def dispatch_once(self) -> DispatchOutcome:
        tasks = self.store.list_tasks(all_jobs=True)
        outcome = DispatchOutcome()
        now_at = _coerce_utc(None)

        by_agent: dict[str, dict[str, object]] = {}
        for task in tasks:
            agent = str(task.get("assigned_agent") or "").strip()
            if not agent:
                continue
            slot = by_agent.setdefault(agent, {"running": None, "queued": []})
            if task.get("state") == "running":
                slot["running"] = task
            elif task.get("state") == "queued":
                slot["queued"].append(task)

        for agent, slot in by_agent.items():
            running = slot["running"]
            if running:
                outcome.skipped_busy[agent] = str(running["id"])
                continue

            queued_tasks = list(slot["queued"])
            queued_tasks.sort(key=lambda item: (item.get("createdAt", ""), item["job_id"], item["id"]))
            if not queued_tasks:
                continue

            candidate = queued_tasks[0]
            scheduler = candidate.setdefault("_scheduler", {})
            if scheduler.get("awaiting_claim"):
                outcome.skipped_pending_claim[agent] = str(candidate["id"])
                continue
            if scheduler.get("dispatch_blocked"):
                outcome.skipped_blocked[agent] = str(candidate["id"])
                continue
            if self._dispatch_in_cooldown(scheduler, now_at):
                outcome.skipped_cooldown[agent] = str(candidate["id"])
                continue
            budget_reason = (
                _openclaw_budget_reason(agent)
                if _should_precheck_openclaw_budget(self.sender, self.reset_sender)
                else None
            )
            if budget_reason:
                deferred = self._record_dispatch_deferred(
                    candidate,
                    agent=agent,
                    reason=budget_reason,
                    retry_after_seconds=SEND_RETRY_AFTER_SECONDS,
                )
                outcome.dispatch_deferred[agent] = deferred
                continue

            scheduler["awaiting_claim"] = True
            candidate["updatedAt"] = now_iso()
            self.store.save_task(candidate)

            dispatch_at: str | None = None
            try:
                reset_result = self.reset_sender(agent, "/reset")
                if not _result_was_sent(reset_result):
                    if _send_result_reason(reset_result) == "process_budget":
                        deferred = self._record_dispatch_deferred(
                            candidate,
                            agent=agent,
                            reason="process_budget",
                            retry_after_seconds=_send_result_retry_after(reset_result),
                        )
                        outcome.dispatch_deferred[agent] = deferred
                        continue
                    failure = self._record_dispatch_failure(
                        candidate,
                        agent=agent,
                        phase="reset",
                        error=_send_result_error(reset_result),
                    )
                    outcome.dispatch_failed[agent] = failure
                    continue
                latest = self.store.load_task(str(candidate["id"]), job_id=str(candidate["job_id"]))
                latest_scheduler = latest.setdefault("_scheduler", {})
                if latest.get("state") != "queued" or latest_scheduler.get("awaiting_claim") is not True:
                    continue
                if str(latest.get("assigned_agent") or "").strip() != agent:
                    latest_scheduler["awaiting_claim"] = False
                    latest["updatedAt"] = now_iso()
                    self.store.save_task(latest)
                    continue

                task_path = self.store.task_path(str(latest["job_id"]), str(latest["id"]))
                message = self._build_dispatch_message(latest, task_path)
                dispatch_at = now_iso()
                latest_scheduler["last_dispatch_at"] = dispatch_at
                latest["updatedAt"] = dispatch_at
                self.store.save_task(latest)
                send_result = self.sender(agent, message)
                if not _result_was_sent(send_result):
                    if _send_result_reason(send_result) == "process_budget":
                        deferred = self._record_dispatch_deferred(
                            latest,
                            agent=agent,
                            reason="process_budget",
                            dispatch_at=dispatch_at,
                            retry_after_seconds=_send_result_retry_after(send_result),
                        )
                        outcome.dispatch_deferred[agent] = deferred
                        continue
                    failure = self._record_dispatch_failure(
                        latest,
                        agent=agent,
                        phase="send",
                        dispatch_at=dispatch_at,
                        error=_send_result_error(send_result),
                    )
                    outcome.dispatch_failed[agent] = failure
                    continue
                latest = self.store.load_task(str(candidate["id"]), job_id=str(candidate["job_id"]))
                latest_scheduler = latest.setdefault("_scheduler", {})
                latest_scheduler["last_dispatch_error"] = None
                latest_scheduler["dispatch_failure_count"] = 0
                latest_scheduler["dispatch_cooldown_until"] = None
                latest_scheduler["dispatch_blocked"] = False
                self.store.save_task(latest)
            except Exception as exc:
                failure = self._record_dispatch_failure(
                    candidate,
                    agent=agent,
                    phase="reset" if dispatch_at is None else "send",
                    dispatch_at=dispatch_at,
                    error=_exception_error(exc),
                )
                outcome.dispatch_failed[agent] = failure
                continue
            self._record_worker_prompt(latest, dispatch_at)
            outcome.dispatched.append(str(latest["id"]))

        return outcome

    def send_due_reminders(
        self,
        *,
        worker_interval_seconds: float = 900.0,
        leader_interval_seconds: float = 3600.0,
        current_time: datetime | None = None,
    ) -> ReminderOutcome:
        now_at = _coerce_utc(current_time)
        now_value = _format_iso(now_at)
        tasks = self.store.list_tasks(all_jobs=True)
        daemon_state = self.store.load_daemon_state()
        worker_last_prompt_at = daemon_state["worker_last_prompt_at"]
        outcome = ReminderOutcome()
        active_worker_keys: set[str] = set()
        running_tasks: list[dict[str, object]] = []
        dirty = False

        for task in tasks:
            agent = str(task.get("assigned_agent") or "").strip()
            if str(task.get("state") or "") == "running" and agent:
                running_tasks.append(task)

            if not self._should_send_worker_reminder(task):
                continue

            key = self._task_key(task)
            active_worker_keys.add(key)
            scheduler = task.setdefault("_scheduler", {})
            last_prompt_at = worker_last_prompt_at.get(key)
            if last_prompt_at is None and scheduler.get("last_dispatch_at"):
                worker_last_prompt_at[key] = str(scheduler["last_dispatch_at"])
                last_prompt_at = str(scheduler["last_dispatch_at"])
                dirty = True
            if not self._is_due(last_prompt_at, worker_interval_seconds, now_at):
                continue

            task_path = self.store.task_path(str(task["job_id"]), str(task["id"]))
            send_result = self.sender(agent, self._build_worker_reminder_message(task, task_path))
            if not _result_was_sent(send_result):
                continue
            worker_last_prompt_at[key] = now_value
            self.store.save_daemon_state(daemon_state)
            outcome.worker_reminded.append(str(task["id"]))
            dirty = False

        stale_worker_keys = [key for key in worker_last_prompt_at if key not in active_worker_keys]
        for key in stale_worker_keys:
            del worker_last_prompt_at[key]
            dirty = True

        last_leader_notice_at = daemon_state.get("leader_last_running_notice_at")
        if running_tasks:
            if self._is_due(last_leader_notice_at, leader_interval_seconds, now_at):
                send_result = self.sender("team-leader", self._build_team_leader_reminder_message(running_tasks))
                if _result_was_sent(send_result):
                    daemon_state["leader_last_running_notice_at"] = now_value
                    self.store.save_daemon_state(daemon_state)
                    outcome.leader_pinged = True
                    dirty = False
            elif last_leader_notice_at is None:
                daemon_state["leader_last_running_notice_at"] = now_value
                dirty = True
        elif last_leader_notice_at is not None:
            daemon_state["leader_last_running_notice_at"] = None
            dirty = True

        if dirty:
            self.store.save_daemon_state(daemon_state)
        return outcome

    def notify_updates(self, *, scope: Literal["current", "all"] = "current") -> NotifyOutcome:
        tasks = self._notification_scope_tasks(scope)
        outcome = NotifyOutcome()
        pending_by_target: dict[str, list[dict[str, object]]] = {}
        for task in tasks:
            if not self._should_notify(task):
                continue
            target = str(task.get("notify_target") or "team-leader")
            pending_by_target.setdefault(target, []).append(task)

        for target, target_tasks in pending_by_target.items():
            message = self._build_notify_batch_message(target_tasks, target)
            send_result = self.sender(target, message)
            if not _result_was_sent(send_result):
                outcome.notify_failed[target] = {
                    "task_ids": [str(task["id"]) for task in target_tasks],
                    "reason": _send_result_reason(send_result),
                }
                self._record_notify_failure(target_tasks, send_result)
                continue

            for task in target_tasks:
                scheduler = task.setdefault("_scheduler", {})
                notified_at = now_iso()
                scheduler["final_notified_at"] = notified_at
                scheduler["final_notify_error"] = None
                self._schedule_leader_followup(task, target=target, notified_at=notified_at)
                task["updatedAt"] = notified_at
                self.store.save_task(task)
                outcome.notified.append(str(task["id"]))
        return outcome

    def notify_backfill(self, *, mode: Literal["mark-only", "summary"] = "mark-only") -> NotifyOutcome:
        if mode not in {"mark-only", "summary"}:
            raise ValueError("notify backfill mode must be mark-only or summary")
        current_job_id = self.store.get_current_job_id()
        tasks = [
            task
            for task in self.store.list_tasks(all_jobs=True)
            if str(task.get("job_id") or "") != str(current_job_id or "") and self._should_notify(task)
        ]
        outcome = NotifyOutcome()
        if not tasks:
            return outcome

        if mode == "summary":
            message = self._build_notify_backfill_summary_message(tasks)
            send_result = self.sender("team-leader", message)
            if not _result_was_sent(send_result):
                outcome.notify_failed["team-leader"] = {
                    "task_ids": [str(task["id"]) for task in tasks],
                    "reason": _send_result_reason(send_result),
                }
                self._record_notify_failure(tasks, send_result)
                return outcome

        marked_at = now_iso()
        for task in tasks:
            scheduler = task.setdefault("_scheduler", {})
            scheduler["final_notified_at"] = marked_at
            scheduler["leader_followup_due_at"] = None
            scheduler["leader_followup_sent_at"] = None
            scheduler["final_notify_error"] = None
            task["updatedAt"] = marked_at
            self.store.save_task(task)
            outcome.notified.append(str(task["id"]))

        daemon_state = self.store.load_daemon_state()
        daemon_state["historical_notify_backfill_completed_at"] = marked_at
        self.store.save_daemon_state(daemon_state)
        return outcome

    def notify_task(self, task_id: str, *, job_id: str | None = None, force: bool = False) -> bool:
        task = self.store.load_task(task_id, job_id=job_id)
        if not force and not self._should_notify(task):
            return False
        target = str(task.get("notify_target") or "team-leader")
        send_result = self.sender(target, self._build_notify_message(task, target))
        if not _result_was_sent(send_result):
            self._record_notify_failure([task], send_result)
            return False
        scheduler = task.setdefault("_scheduler", {})
        if str(task.get("state") or "") in TERMINAL_TASK_STATES:
            notified_at = now_iso()
            scheduler["final_notified_at"] = notified_at
            scheduler["final_notify_error"] = None
            self._schedule_leader_followup(task, target=target, notified_at=notified_at)
            task["updatedAt"] = notified_at
        self.store.save_task(task)
        return True

    def send_due_leader_unresolved_followups(
        self,
        *,
        current_time: datetime | None = None,
    ) -> LeaderFollowupOutcome:
        tasks = self.store.list_tasks(all_jobs=True)
        outcome = LeaderFollowupOutcome()
        if self.leader_unresolved_followup_seconds <= 0:
            for task in tasks:
                if not self._is_pending_leader_followup(task):
                    continue
                self._clear_leader_followup(task)
                self.store.save_task(task)
            return outcome

        now_at = _coerce_utc(current_time)
        now_value = _format_iso(now_at)
        current_job_id = self.store.get_current_job_id()
        groups = collect_pending_leader_followup_jobs(
            tasks,
            current_job_id=current_job_id,
            current_time=now_at,
        )
        for group in groups:
            if not group.is_current_job or group.has_newer_task:
                self._clear_leader_followup_tasks(group.tasks)
                continue
            if not group.is_due:
                continue

            send_result = self.sender(
                "team-leader",
                self._build_leader_unresolved_followup_message(group.job_id, list(group.tasks)),
            )
            if not _result_was_sent(send_result):
                continue
            self._mark_leader_followup_sent(group.tasks, sent_at=now_value)
            outcome.followed_up.append(str(group.latest_task["id"]))

        return outcome

    def queue_for_agent(self, agent: str) -> dict[str, object]:
        return queue_for_agent(self.store.list_tasks(all_jobs=True), agent)

    def _build_dispatch_message(self, task: dict[str, object], task_path: Path) -> str:
        prompts = self._reload_prompts()
        return self._render_prompt(
            "dispatch",
            prompts.dispatch,
            {
                "job_id": task["job_id"],
                "task_id": task["id"],
                "task_path": task_path,
                "detail_path": self._task_detail_path(task),
                "assigned_agent": task["assigned_agent"],
                "requirement": task.get("requirement") or "(empty requirement)",
            },
        )

    def _build_notify_message(self, task: dict[str, object], target: str) -> str:
        prompts = self._reload_prompts()
        follow_up = ""
        detail_path = self._existing_detail_path(task)
        if target == "team-leader":
            follow_up = self._render_prompt(
                "notify.team_leader_follow_up",
                prompts.notify_team_leader_follow_up,
                {
                    "user_chat_id": self._user_chat_id_value(),
                },
            )
        return self._render_prompt(
            "notify",
            prompts.notify,
            {
                "job_id": task["job_id"],
                "task_id": task["id"],
                "assigned_agent": task["assigned_agent"],
                "state": task["state"],
                "detail_path_line": f"detail_path={detail_path}\n" if detail_path else "",
                "user_chat_id": self._user_chat_id_value(),
                "result": task.get("result") or "(empty result)",
                "follow_up": follow_up,
            },
        )

    def _build_notify_batch_message(self, tasks: list[dict[str, object]], target: str) -> str:
        ordered = sorted(tasks, key=lambda item: (item.get("updatedAt", ""), item.get("createdAt", ""), item["id"]))
        if len(ordered) == 1:
            return self._build_notify_message(ordered[0], target)
        return "\n\n---\n\n".join(self._build_notify_message(task, target) for task in ordered)

    def _build_notify_backfill_summary_message(self, tasks: list[dict[str, object]]) -> str:
        ordered = sorted(tasks, key=lambda item: (item.get("updatedAt", ""), item.get("createdAt", ""), item["id"]))
        lines = [
            "[TASK_NOTIFY_BACKFILL]",
            f"historical_terminal_tasks={len(ordered)}",
            "以下历史终态任务缺少 final_notified_at，已按 summary backfill 聚合处理：",
        ]
        for task in ordered:
            lines.append(
                f"- job_id={task['job_id']} task_id={task['id']} "
                f"worker_agent={task.get('assigned_agent')} state={task.get('state')}"
            )
        lines.append("本消息是历史补标汇总，不代表这些任务刚刚完成。")
        return "\n".join(lines)

    def _build_worker_reminder_message(self, task: dict[str, object], task_path: Path) -> str:
        prompts = self._reload_prompts()
        return self._render_prompt(
            "worker_reminder",
            prompts.worker_reminder,
            {
                "job_id": task["job_id"],
                "task_id": task["id"],
                "assigned_agent": task["assigned_agent"],
                "state": task["state"],
                "task_path": task_path,
            },
        )

    def _build_team_leader_reminder_message(self, tasks: list[dict[str, object]]) -> str:
        prompts = self._reload_prompts()
        ordered = sorted(
            tasks,
            key=lambda item: (
                str(item.get("assigned_agent") or ""),
                str(item.get("job_id") or ""),
                str(item.get("id") or ""),
            ),
        )
        summaries = [
            (
                f"- worker={task['assigned_agent']} "
                f"task_id={task['id']} "
                f"job_id={task['job_id']} "
                f"state={task['state']}"
            )
            for task in ordered
        ]
        return self._render_prompt(
            "running_summary",
            prompts.running_summary,
            {
                "running_tasks_count": len(ordered),
                "user_chat_id": self._user_chat_id_value(),
                "task_summaries": "\n".join(summaries),
            },
        )

    def _build_leader_unresolved_followup_message(
        self,
        job_id: str,
        tasks: list[dict[str, object]],
    ) -> str:
        prompts = self._reload_prompts()
        summaries = "\n".join(
            self._format_followup_task_summary(task)
            for task in sorted(tasks, key=_leader_followup_group_task_sort_key)
        )
        return self._render_prompt(
            "leader_unresolved_followup",
            prompts.leader_unresolved_followup,
            {
                "job_id": job_id,
                "user_chat_id": self._user_chat_id_value(),
                "source_task_summaries": summaries,
            },
        )

    def _should_notify(self, task: dict[str, object]) -> bool:
        state = str(task.get("state") or "")
        if state not in TERMINAL_TASK_STATES:
            return False
        scheduler = task.setdefault("_scheduler", {})
        cooldown_until = str(scheduler.get("final_notify_cooldown_until") or "")
        if cooldown_until:
            try:
                if _parse_iso(cooldown_until) > _coerce_utc(None):
                    return False
            except ValueError:
                pass
        return scheduler.get("final_notified_at") is None

    def _schedule_leader_followup(self, task: dict[str, object], *, target: str, notified_at: str) -> None:
        scheduler = task.setdefault("_scheduler", {})
        job_id = str(task["job_id"])
        current_task_id = str(task["id"])
        current_job_id = self.store.get_current_job_id()
        if (
            target != "team-leader"
            or str(task.get("state") or "") not in TERMINAL_TASK_STATES
            or self.leader_unresolved_followup_seconds <= 0
            or current_job_id != job_id
        ):
            scheduler["leader_followup_due_at"] = None
            scheduler["leader_followup_sent_at"] = None
            return

        for sibling in self.store.list_tasks(job_id=job_id):
            if str(sibling["id"]) == current_task_id:
                continue
            if not _is_pending_leader_followup_task(sibling):
                continue
            self._clear_leader_followup(sibling)
            self.store.save_task(sibling)

        due_at = _parse_iso(notified_at) + timedelta(seconds=self.leader_unresolved_followup_seconds)
        scheduler["leader_followup_due_at"] = _format_iso(due_at)
        scheduler["leader_followup_sent_at"] = None

    @staticmethod
    def _clear_leader_followup(task: dict[str, object]) -> None:
        scheduler = task.setdefault("_scheduler", {})
        scheduler["leader_followup_due_at"] = None
        scheduler["leader_followup_sent_at"] = None

    def _clear_leader_followup_tasks(
        self,
        tasks: list[dict[str, object]] | tuple[dict[str, object], ...],
    ) -> None:
        for task in tasks:
            self._clear_leader_followup(task)
            self.store.save_task(task)

    def _mark_leader_followup_sent(
        self,
        tasks: list[dict[str, object]] | tuple[dict[str, object], ...],
        *,
        sent_at: str,
    ) -> None:
        for task in tasks:
            scheduler = task.setdefault("_scheduler", {})
            scheduler["leader_followup_due_at"] = None
            scheduler["leader_followup_sent_at"] = sent_at
            task["updatedAt"] = sent_at
            self.store.save_task(task)

    @staticmethod
    def _is_pending_leader_followup(task: dict[str, object]) -> bool:
        return _is_pending_leader_followup_task(task)

    @staticmethod
    def _job_has_newer_task(
        tasks: list[dict[str, object]],
        *,
        source_task: dict[str, object],
        after_timestamp: str,
    ) -> bool:
        return _job_has_newer_task(
            tasks,
            job_id=str(source_task["job_id"]),
            after_timestamp=after_timestamp,
            exclude_task_ids={str(source_task["id"])},
        )

    def _rollback_dispatch_claim(self, *, job_id: str, task_id: str, dispatch_at: str | None) -> None:
        latest = self.store.load_task(task_id, job_id=job_id)
        scheduler = latest.setdefault("_scheduler", {})
        if latest.get("state") != "queued":
            return
        if dispatch_at is not None and scheduler.get("last_dispatch_at") != dispatch_at:
            return
        if scheduler.get("awaiting_claim") is not True:
            return
        scheduler["awaiting_claim"] = False
        latest["updatedAt"] = now_iso()
        self.store.save_task(latest)

    def _record_worker_prompt(self, task: dict[str, object], timestamp: str) -> None:
        daemon_state = self.store.load_daemon_state()
        daemon_state["worker_last_prompt_at"][self._task_key(task)] = timestamp
        self.store.save_daemon_state(daemon_state)

    def _record_dispatch_failure(
        self,
        task: dict[str, object],
        *,
        agent: str,
        phase: str,
        error: dict[str, object],
        dispatch_at: str | None = None,
    ) -> dict[str, object]:
        latest = self.store.load_task(str(task["id"]), job_id=str(task["job_id"]))
        scheduler = latest.setdefault("_scheduler", {})
        if latest.get("state") == "queued":
            scheduler["awaiting_claim"] = False
        if dispatch_at is not None:
            scheduler["last_dispatch_at"] = dispatch_at
        failure_count = int(scheduler.get("dispatch_failure_count") or 0) + 1
        cooldown_until = self._dispatch_cooldown_until(failure_count)
        error_payload = {
            "at": now_iso(),
            "phase": phase,
            **error,
        }
        scheduler["last_dispatch_error"] = error_payload
        scheduler["dispatch_failure_count"] = failure_count
        scheduler["dispatch_cooldown_until"] = cooldown_until
        scheduler["dispatch_blocked"] = failure_count >= MAX_DISPATCH_FAILURES_BEFORE_BLOCKED
        latest["updatedAt"] = now_iso()
        self.store.save_task(latest)
        return {
            "task_id": str(latest["id"]),
            "phase": phase,
            "cooldown_until": cooldown_until,
            "failure_count": failure_count,
            "error": error_payload,
        }

    def _record_dispatch_deferred(
        self,
        task: dict[str, object],
        *,
        agent: str,
        reason: str,
        dispatch_at: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> dict[str, object]:
        latest = self.store.load_task(str(task["id"]), job_id=str(task["job_id"]))
        scheduler = latest.setdefault("_scheduler", {})
        if latest.get("state") == "queued":
            scheduler["awaiting_claim"] = False
        if dispatch_at is not None:
            if scheduler.get("last_dispatch_at") == dispatch_at:
                scheduler["last_dispatch_at"] = None
        cooldown_until = self._send_cooldown_until(retry_after_seconds)
        scheduler["dispatch_cooldown_until"] = cooldown_until
        scheduler["last_dispatch_error"] = {
            "at": now_iso(),
            "phase": "send",
            "message": reason,
            "transient": True,
        }
        latest["updatedAt"] = now_iso()
        self.store.save_task(latest)
        return {
            "task_id": str(latest["id"]),
            "reason": reason,
            "cooldown_until": cooldown_until,
        }

    def _record_notify_failure(self, tasks: list[dict[str, object]], send_result: object) -> None:
        retry_after = _send_result_retry_after(send_result)
        cooldown_until = self._send_cooldown_until(retry_after)
        for task in tasks:
            latest = self.store.load_task(str(task["id"]), job_id=str(task["job_id"]))
            scheduler = latest.setdefault("_scheduler", {})
            attempt_count = int(scheduler.get("final_notify_attempt_count") or 0) + 1
            scheduler["final_notify_attempt_count"] = attempt_count
            scheduler["final_notify_error"] = {
                "at": now_iso(),
                "reason": _send_result_reason(send_result),
            }
            scheduler["final_notify_cooldown_until"] = cooldown_until
            latest["updatedAt"] = now_iso()
            self.store.save_task(latest)

    def _notification_scope_tasks(self, scope: Literal["current", "all"]) -> list[dict[str, object]]:
        if scope == "all":
            return self.store.list_tasks(all_jobs=True)
        if scope != "current":
            raise ValueError("notify scope must be current or all")
        current_job_id = self.store.get_current_job_id()
        if not current_job_id:
            return []
        return self.store.list_tasks(job_id=current_job_id)

    @staticmethod
    def _dispatch_in_cooldown(scheduler: dict[str, object], current_time: datetime) -> bool:
        until = str(scheduler.get("dispatch_cooldown_until") or "")
        if not until:
            return False
        try:
            return _parse_iso(until) > current_time
        except ValueError:
            return False

    @staticmethod
    def _dispatch_cooldown_until(failure_count: int) -> str:
        index = max(0, min(failure_count - 1, len(DISPATCH_BACKOFF_SECONDS) - 1))
        return _format_iso(_coerce_utc(None) + timedelta(seconds=DISPATCH_BACKOFF_SECONDS[index]))

    @staticmethod
    def _send_cooldown_until(retry_after_seconds: int | None = None) -> str:
        retry_after = retry_after_seconds if retry_after_seconds is not None else SEND_RETRY_AFTER_SECONDS
        return _format_iso(_coerce_utc(None) + timedelta(seconds=retry_after))

    def _reload_prompts(self):
        self.prompts = load_prompts()
        return self.prompts

    def _user_chat_id_value(self) -> str:
        return self.user_chat_id or "(not set)"

    def _task_detail_path(self, task: dict[str, object]) -> str:
        detail_path = str(task.get("detail_path") or "").strip()
        if detail_path:
            return detail_path
        return str(self.store.detail_path(str(task["job_id"]), str(task["id"])))

    def _existing_detail_path(self, task: dict[str, object]) -> str | None:
        detail_path = self._task_detail_path(task)
        if not Path(detail_path).is_file():
            return None
        return detail_path

    def _format_followup_task_summary(self, task: dict[str, object]) -> str:
        summary = f"- task_id={task['id']} worker_agent={task['assigned_agent']} state={task['state']}"
        detail_path = self._existing_detail_path(task)
        if detail_path:
            summary += f" detail_path={detail_path}"
        return summary

    @staticmethod
    def _render_prompt(name: str, template: str, context: dict[str, object]) -> str:
        rendered_context = {key: str(value) for key, value in context.items()}
        try:
            return template.format_map(rendered_context)
        except KeyError as exc:
            missing = exc.args[0]
            raise ValueError(f"prompt template '{name}' references unknown placeholder: {missing}") from exc

    @staticmethod
    def _should_send_worker_reminder(task: dict[str, object]) -> bool:
        agent = str(task.get("assigned_agent") or "").strip()
        if not agent:
            return False
        state = str(task.get("state") or "")
        scheduler = task.setdefault("_scheduler", {})
        if not scheduler.get("last_dispatch_at"):
            return False
        if state == "running":
            return True
        return state == "queued" and scheduler.get("awaiting_claim") is True

    @staticmethod
    def _task_key(task: dict[str, object]) -> str:
        return f"{task['job_id']}:{task['id']}"

    @staticmethod
    def _is_due(last_at: str | None, interval_seconds: float, current_time: datetime) -> bool:
        if last_at is None:
            return interval_seconds <= 0
        try:
            previous = _parse_iso(last_at)
        except ValueError:
            return True
        return (current_time - previous).total_seconds() >= interval_seconds


def collect_pending_leader_followup_jobs(
    tasks: list[dict[str, object]],
    *,
    current_job_id: str | None,
    current_time: datetime | None = None,
) -> list[PendingLeaderFollowupJob]:
    now_at = _coerce_utc(current_time)
    pending_by_job: dict[str, list[dict[str, object]]] = {}
    for task in tasks:
        if not _is_pending_leader_followup_task(task):
            continue
        pending_by_job.setdefault(str(task["job_id"]), []).append(task)

    groups: list[PendingLeaderFollowupJob] = []
    for job_id, job_tasks in pending_by_job.items():
        ordered_tasks = tuple(sorted(job_tasks, key=_leader_followup_group_task_sort_key))
        latest_task = ordered_tasks[-1]
        latest_due_at = _leader_followup_due_at(latest_task)
        latest_final_notified_at = _leader_followup_anchor_timestamp(latest_task)
        groups.append(
            PendingLeaderFollowupJob(
                job_id=job_id,
                tasks=ordered_tasks,
                latest_task=latest_task,
                latest_due_at=latest_due_at,
                latest_final_notified_at=latest_final_notified_at,
                is_due=BridgeRuntime._is_due(latest_due_at or None, 0, now_at),
                is_current_job=current_job_id is not None and job_id == current_job_id,
                has_newer_task=(
                    bool(latest_final_notified_at)
                    and _job_has_newer_task(
                        tasks,
                        job_id=job_id,
                        after_timestamp=latest_final_notified_at,
                        exclude_task_ids={str(latest_task["id"])},
                    )
                ),
            )
        )

    groups.sort(
        key=lambda group: (
            0 if group.is_due else 1,
            group.latest_due_at,
            group.job_id,
            str(group.latest_task["id"]),
        )
    )
    return groups


def _leader_followup_group_task_sort_key(task: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        _leader_followup_anchor_timestamp(task),
        _leader_followup_due_at(task),
        str(task.get("createdAt") or ""),
        str(task["id"]),
    )


def _leader_followup_anchor_timestamp(task: dict[str, object]) -> str:
    scheduler = task.setdefault("_scheduler", {})
    return str(
        scheduler.get("final_notified_at")
        or task.get("updatedAt")
        or task.get("createdAt")
        or ""
    )


def _leader_followup_due_at(task: dict[str, object]) -> str:
    scheduler = task.setdefault("_scheduler", {})
    return str(scheduler.get("leader_followup_due_at") or "")


def _is_pending_leader_followup_task(task: dict[str, object]) -> bool:
    if str(task.get("notify_target") or "team-leader") != "team-leader":
        return False
    if str(task.get("state") or "") not in TERMINAL_TASK_STATES:
        return False
    scheduler = task.setdefault("_scheduler", {})
    return scheduler.get("leader_followup_due_at") is not None and scheduler.get("leader_followup_sent_at") is None


def _job_has_newer_task(
    tasks: list[dict[str, object]],
    *,
    job_id: str,
    after_timestamp: str,
    exclude_task_ids: set[str] | None = None,
) -> bool:
    excluded = exclude_task_ids or set()
    return any(
        str(task.get("job_id") or "") == job_id
        and str(task.get("id") or "") not in excluded
        and str(task.get("createdAt") or "") > after_timestamp
        for task in tasks
    )


def _coerce_utc(current_time: datetime | None) -> datetime:
    if current_time is None:
        return datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=timezone.utc)
    return current_time.astimezone(timezone.utc)


def _format_iso(current_time: datetime) -> str:
    return current_time.isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def default_openclaw_sender(agent: str, message: str) -> SendResult:
    if _capture_message(agent, message):
        return SendResult(sent=True)

    budget_reason = _openclaw_budget_reason(agent)
    if budget_reason:
        return SendResult(sent=False, reason=budget_reason, retry_after_seconds=SEND_RETRY_AFTER_SECONDS)

    process = subprocess.Popen(
        [
            "openclaw",
            "agent",
            "--agent",
            agent,
            "-m",
            message,
            "--timeout",
            "0",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return SendResult(sent=True, pid=getattr(process, "pid", None))


def default_openclaw_reset_sender(agent: str, message: str) -> CommandResult | SendResult:
    if _capture_message(agent, message):
        return CommandResult(ok=True)

    budget_reason = _openclaw_budget_reason(agent)
    if budget_reason:
        return SendResult(sent=False, reason=budget_reason, retry_after_seconds=SEND_RETRY_AFTER_SECONDS)

    argv = [
        "openclaw",
        "agent",
        "--agent",
        agent,
        "-m",
        message,
    ]
    started_at = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("TASK_BRIDGE_OPENCLAW_RESET_TIMEOUT_SECONDS", "60")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        raise OpenClawCommandError(
            "openclaw reset timed out",
            argv=argv,
            stdout_tail=_tail_text(exc.stdout),
            stderr_tail=_tail_text(exc.stderr),
            duration_ms=duration_ms,
        ) from exc
    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    if completed.returncode != 0:
        raise OpenClawCommandError(
            "openclaw reset failed",
            argv=argv,
            returncode=completed.returncode,
            stdout_tail=_tail_text(completed.stdout),
            stderr_tail=_tail_text(completed.stderr),
            duration_ms=duration_ms,
        )
    return CommandResult(
        ok=True,
        returncode=completed.returncode,
        stdout_tail=_tail_text(completed.stdout),
        stderr_tail=_tail_text(completed.stderr),
        duration_ms=duration_ms,
    )


def _result_was_sent(result: object) -> bool:
    if result is None:
        return True
    if isinstance(result, SendResult):
        return result.sent
    if isinstance(result, CommandResult):
        return result.ok
    return True


def _send_result_reason(result: object) -> str:
    if isinstance(result, SendResult):
        return result.reason or "send_failed"
    if isinstance(result, CommandResult):
        return "command_failed" if not result.ok else "ok"
    return "send_failed"


def _send_result_retry_after(result: object) -> int | None:
    if isinstance(result, SendResult):
        return result.retry_after_seconds
    return None


def _send_result_error(result: object) -> dict[str, object]:
    if isinstance(result, SendResult):
        payload: dict[str, object] = {"message": result.reason or "send failed"}
        if result.error:
            payload.update(result.error)
        return payload
    if isinstance(result, CommandResult):
        return {
            "message": "command failed",
            "returncode": result.returncode,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
            "duration_ms": result.duration_ms,
        }
    return {"message": "send failed"}


def _exception_error(exc: Exception) -> dict[str, object]:
    if isinstance(exc, OpenClawCommandError):
        return exc.to_error_dict()
    return {
        "type": type(exc).__name__,
        "message": str(exc),
    }


def _openclaw_budget_reason(agent: str) -> str | None:
    max_global = int(os.environ.get("TASK_BRIDGE_OPENCLAW_MAX_GLOBAL", "2"))
    max_per_agent = int(os.environ.get("TASK_BRIDGE_OPENCLAW_MAX_PER_AGENT", "1"))
    if max_global <= 0 and max_per_agent <= 0:
        return None
    counts = _openclaw_process_counts()
    if max_global > 0 and counts["global"] >= max_global:
        return "process_budget"
    if max_per_agent > 0 and counts["by_agent"].get(agent, 0) >= max_per_agent:
        return "process_budget"
    return None


def _should_precheck_openclaw_budget(sender: Sender | None = None, reset_sender: ResetSender | None = None) -> bool:
    if os.environ.get("TASK_BRIDGE_CAPTURE_FILE"):
        return False
    if sender is None and reset_sender is None:
        return True
    return sender is default_openclaw_sender or reset_sender is default_openclaw_reset_sender


def _openclaw_process_counts() -> dict[str, object]:
    by_agent: dict[str, int] = {}
    try:
        completed = subprocess.run(
            ["ps", "-eo", "args"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"global": 0, "by_agent": by_agent}

    total = 0
    for line in completed.stdout.splitlines():
        if "openclaw" not in line or "agent" not in line or "--agent" not in line:
            continue
        if "ps -eo args" in line:
            continue
        parts = line.split()
        try:
            agent = parts[parts.index("--agent") + 1]
        except (ValueError, IndexError):
            agent = ""
        total += 1
        if agent:
            by_agent[agent] = by_agent.get(agent, 0) + 1
    return {"global": total, "by_agent": by_agent}


def _tail_text(value: object, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value)
    return text[-limit:]

def _capture_message(agent: str, message: str) -> bool:
    capture_file = os.environ.get("TASK_BRIDGE_CAPTURE_FILE")
    if not capture_file:
        return False

    path = Path(capture_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "at": now_iso(),
                    "agent": agent,
                    "message": message,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return True
