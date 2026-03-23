from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .config import resolve_user_chat_id
from .prompts import load_prompts
from .store import TaskStore, now_iso, queue_for_agent

Sender = Callable[[str, str], None]
ResetSender = Callable[[str, str], None]
TERMINAL_TASK_STATES = {"done", "blocked", "failed"}
LEADER_UNRESOLVED_FOLLOWUP_SECONDS = 300.0


@dataclass
class DispatchOutcome:
    dispatched: list[str] = field(default_factory=list)
    skipped_busy: dict[str, str] = field(default_factory=dict)
    skipped_pending_claim: dict[str, str] = field(default_factory=dict)


@dataclass
class NotifyOutcome:
    notified: list[str] = field(default_factory=list)


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

            scheduler["awaiting_claim"] = True
            candidate["updatedAt"] = now_iso()
            self.store.save_task(candidate)

            dispatch_at: str | None = None
            try:
                self.reset_sender(agent, "/reset")
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
                self.sender(agent, message)
            except Exception:
                self._rollback_dispatch_claim(
                    job_id=str(candidate["job_id"]),
                    task_id=str(candidate["id"]),
                    dispatch_at=dispatch_at,
                )
                raise
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
            self.sender(agent, self._build_worker_reminder_message(task, task_path))
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
                self.sender("team-leader", self._build_team_leader_reminder_message(running_tasks))
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

    def notify_updates(self) -> NotifyOutcome:
        tasks = self.store.list_tasks(all_jobs=True)
        outcome = NotifyOutcome()
        for task in tasks:
            if not self._should_notify(task):
                continue
            target = str(task.get("notify_target") or "team-leader")
            self.sender(target, self._build_notify_message(task, target))
            scheduler = task.setdefault("_scheduler", {})
            notified_at = now_iso()
            scheduler["final_notified_at"] = notified_at
            self._schedule_leader_followup(task, target=target, notified_at=notified_at)
            task["updatedAt"] = notified_at
            self.store.save_task(task)
            outcome.notified.append(str(task["id"]))
        return outcome

    def notify_task(self, task_id: str, *, job_id: str | None = None, force: bool = False) -> bool:
        task = self.store.load_task(task_id, job_id=job_id)
        if not force and not self._should_notify(task):
            return False
        target = str(task.get("notify_target") or "team-leader")
        self.sender(target, self._build_notify_message(task, target))
        scheduler = task.setdefault("_scheduler", {})
        if str(task.get("state") or "") in TERMINAL_TASK_STATES:
            notified_at = now_iso()
            scheduler["final_notified_at"] = notified_at
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
        if current_job_id is None:
            return outcome

        groups = collect_pending_leader_followup_jobs(
            tasks,
            current_job_id=current_job_id,
            current_time=now_at,
        )
        for group in groups:
            stale_tasks = [task for task in group.tasks if task is not group.latest_task]
            if stale_tasks:
                self._clear_leader_followup_tasks(stale_tasks)

            if not group.is_current_job or group.has_newer_task:
                self._clear_leader_followup_tasks([group.latest_task])
                continue
            if not group.is_due:
                continue

            self.sender(
                "team-leader",
                self._build_leader_unresolved_followup_message(group.job_id, [group.latest_task]),
            )
            self._mark_leader_followup_sent([group.latest_task], sent_at=now_value)
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
            for task in sorted(tasks, key=lambda item: (item.get("createdAt", ""), item["id"]))
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
        return scheduler.get("final_notified_at") is None

    def _schedule_leader_followup(self, task: dict[str, object], *, target: str, notified_at: str) -> None:
        scheduler = task.setdefault("_scheduler", {})
        if (
            target != "team-leader"
            or str(task.get("state") or "") not in TERMINAL_TASK_STATES
            or self.leader_unresolved_followup_seconds <= 0
            or self.store.get_current_job_id() != str(task["job_id"])
        ):
            scheduler["leader_followup_due_at"] = None
            scheduler["leader_followup_sent_at"] = None
            return

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


def default_openclaw_sender(agent: str, message: str) -> None:
    if _capture_message(agent, message):
        return

    subprocess.Popen(
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


def default_openclaw_reset_sender(agent: str, message: str) -> None:
    if _capture_message(agent, message):
        return

    subprocess.run(
        [
            "openclaw",
            "agent",
            "--agent",
            agent,
            "-m",
            message,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


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
