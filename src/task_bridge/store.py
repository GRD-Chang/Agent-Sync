from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_WORKERS = (
    "planning-agent",
    "code-agent",
    "quality-agent",
    "release-agent",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_home(explicit_home: Path | None = None) -> Path:
    if explicit_home is not None:
        return explicit_home
    env_home = os.environ.get("TASK_BRIDGE_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".openclaw" / "task-bridge").resolve()


def make_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{prefix}-{stamp}-{suffix}"


class TaskStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = resolve_home(home)
        self.jobs_dir = self.home / "jobs"
        self.current_job_file = self.home / "current_job"

    def ensure_dirs(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def tasks_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "tasks"

    def task_path(self, job_id: str, task_id: str) -> Path:
        return self.tasks_dir(job_id) / f"{task_id}.json"

    def artifacts_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "artifacts"

    def task_artifacts_dir(self, job_id: str, task_id: str) -> Path:
        return self.artifacts_dir(job_id) / task_id

    def detail_path(self, job_id: str, task_id: str) -> Path:
        return self.task_artifacts_dir(job_id, task_id) / "detail.md"

    def daemon_state_path(self) -> Path:
        return self.home / "daemon_state.json"

    def job_exists(self, job_id: str) -> bool:
        return self.job_path(job_id).exists()

    def load_job(self, job_id: str) -> dict[str, Any]:
        return json.loads(self.job_path(job_id).read_text())

    def save_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir(job_id).mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(self.job_path(job_id), job)

    def list_jobs(self) -> list[dict[str, Any]]:
        if not self.jobs_dir.exists():
            return []
        jobs = [json.loads(path.read_text()) for path in sorted(self.jobs_dir.glob("*/job.json"))]
        jobs.sort(key=lambda item: (item.get("createdAt", ""), item["id"]))
        current = self.get_current_job_id()
        for job in jobs:
            job["is_current"] = job["id"] == current
        return jobs

    def create_job(
        self,
        *,
        title: str,
        notify_target: str = "team-leader",
    ) -> dict[str, Any]:
        self.ensure_dirs()
        timestamp = now_iso()
        job = {
            "id": make_id("job"),
            "title": title,
            "notify_target": notify_target,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        self.save_job(job)
        self.set_current_job(job["id"])
        return self.load_job(job["id"])

    def get_current_job_id(self) -> str | None:
        if not self.current_job_file.exists():
            return None
        text = self.current_job_file.read_text().strip()
        return text or None

    def set_current_job(self, job_id: str) -> dict[str, Any]:
        if not self.job_exists(job_id):
            raise FileNotFoundError(f"job not found: {job_id}")
        self.current_job_file.write_text(job_id + "\n")
        return self.load_job(job_id)

    def resolve_job_id(self, job_id: str | None = None) -> str:
        if job_id:
            if not self.job_exists(job_id):
                raise FileNotFoundError(f"job not found: {job_id}")
            return job_id

        current = self.get_current_job_id()
        if current and self.job_exists(current):
            return current

        jobs = self.list_jobs()
        if len(jobs) == 1:
            self.set_current_job(jobs[0]["id"])
            return jobs[0]["id"]
        if not jobs:
            raise FileNotFoundError("no job found")
        raise ValueError("multiple jobs exist; use --job or use-job")

    def create_task(
        self,
        *,
        requirement: str,
        job_id: str | None = None,
        assigned_agent: str = "",
    ) -> dict[str, Any]:
        actual_job_id = self.resolve_job_id(job_id)
        job = self.load_job(actual_job_id)
        timestamp = now_iso()
        task_id = make_id("task")
        task = {
            "id": task_id,
            "job_id": actual_job_id,
            "assigned_agent": assigned_agent,
            "notify_target": job.get("notify_target", "team-leader"),
            "state": "queued",
            "requirement": requirement,
            "result": "",
            "detail_path": str(self.detail_path(actual_job_id, task_id)),
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "_scheduler": {
                "awaiting_claim": False,
                "last_dispatch_at": None,
                "final_notified_at": None,
                "leader_followup_due_at": None,
                "leader_followup_sent_at": None,
            },
        }
        self.save_task(task)
        self.touch_job(actual_job_id)
        return task

    def save_task(self, task: dict[str, Any]) -> None:
        task = self._normalize_task(task)
        job_id = str(task["job_id"])
        task_id = str(task["id"])
        task_dir = self.tasks_dir(job_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        self.task_artifacts_dir(job_id, task_id).mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(self.task_path(job_id, task_id), task)

    def load_daemon_state(self) -> dict[str, Any]:
        path = self.daemon_state_path()
        if not path.exists():
            return _ensure_daemon_state({})
        return _ensure_daemon_state(json.loads(path.read_text()))

    def save_daemon_state(self, state: dict[str, Any]) -> None:
        self._atomic_write_json(self.daemon_state_path(), _ensure_daemon_state(dict(state)))

    def load_task(self, task_id: str, job_id: str | None = None) -> dict[str, Any]:
        if job_id:
            path = self.task_path(job_id, task_id)
            if not path.exists():
                raise FileNotFoundError(f"task not found: {task_id}")
            return self._normalize_task(json.loads(path.read_text()))

        current = self.get_current_job_id()
        if current:
            current_path = self.task_path(current, task_id)
            if current_path.exists():
                return self._normalize_task(json.loads(current_path.read_text()))

        matches = list(self.jobs_dir.glob(f"*/tasks/{task_id}.json"))
        if not matches:
            raise FileNotFoundError(f"task not found: {task_id}")
        if len(matches) > 1:
            raise ValueError(f"task id is ambiguous: {task_id}; use --job")
        return self._normalize_task(json.loads(matches[0].read_text()))

    def list_tasks(
        self,
        *,
        job_id: str | None = None,
        all_jobs: bool = False,
    ) -> list[dict[str, Any]]:
        if all_jobs:
            paths = sorted(self.jobs_dir.glob("*/tasks/*.json"))
            tasks = [self._normalize_task(json.loads(path.read_text())) for path in paths]
            tasks.sort(key=lambda item: (item.get("createdAt", ""), item["job_id"], item["id"]))
            return tasks

        actual_job_id = self.resolve_job_id(job_id)
        tasks_dir = self.tasks_dir(actual_job_id)
        if not tasks_dir.exists():
            return []
        tasks = [self._normalize_task(json.loads(path.read_text())) for path in sorted(tasks_dir.glob("*.json"))]
        tasks.sort(key=lambda item: (item.get("createdAt", ""), item["id"]))
        return tasks

    def update_task(
        self,
        task_id: str,
        *,
        job_id: str | None = None,
        state: str | None = None,
        result: str | None = None,
        assigned_agent: str | None = None,
        requirement: str | None = None,
        clear_awaiting_claim: bool = False,
    ) -> dict[str, Any]:
        task = self.load_task(task_id, job_id=job_id)
        original_state = str(task.get("state") or "")
        if assigned_agent is not None:
            if assigned_agent != task.get("assigned_agent") and original_state != "queued":
                raise ValueError("assigned_agent can only be updated when task is queued")
        if requirement is not None:
            if requirement != task.get("requirement") and original_state != "queued":
                raise ValueError("requirement can only be updated when task is queued")
        if state is not None:
            task["state"] = state
        if result is not None:
            task["result"] = result
        if assigned_agent is not None:
            task["assigned_agent"] = assigned_agent
        if requirement is not None:
            task["requirement"] = requirement
        task["updatedAt"] = now_iso()
        scheduler = _ensure_scheduler(task)
        if clear_awaiting_claim:
            scheduler["awaiting_claim"] = False
        self.save_task(task)
        self.touch_job(task["job_id"])
        return task

    def delete_task(self, task_id: str, *, job_id: str | None = None) -> dict[str, Any]:
        task = self.load_task(task_id, job_id=job_id)
        if task.get("state") not in {"queued", "done"}:
            raise ValueError("task can only be deleted when state is queued or done")
        path = self.task_path(str(task["job_id"]), str(task["id"]))
        path.unlink()
        self.touch_job(str(task["job_id"]))
        return {"task_id": str(task["id"]), "deleted": True}

    def touch_job(self, job_id: str) -> dict[str, Any]:
        job = self.load_job(job_id)
        job["updatedAt"] = now_iso()
        self.save_job(job)
        return job

    def _normalize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task)
        job_id = str(payload["job_id"])
        task_id = str(payload["id"])
        payload.setdefault("detail_path", str(self.detail_path(job_id, task_id)))
        _ensure_scheduler(payload)
        return payload

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(path)


def _ensure_scheduler(task: dict[str, Any]) -> dict[str, Any]:
    scheduler = task.setdefault("_scheduler", {})
    scheduler.setdefault("awaiting_claim", False)
    scheduler.setdefault("last_dispatch_at", None)
    scheduler.setdefault("final_notified_at", None)
    scheduler.setdefault("leader_followup_due_at", None)
    scheduler.setdefault("leader_followup_sent_at", None)
    return scheduler


def _ensure_daemon_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    worker_last_prompt_at = payload.get("worker_last_prompt_at")
    payload["worker_last_prompt_at"] = dict(worker_last_prompt_at) if isinstance(worker_last_prompt_at, dict) else {}
    payload.setdefault("leader_last_running_notice_at", None)
    return payload


def infer_worker_status(tasks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks_list = [task for task in tasks if str(task.get("assigned_agent") or "").strip()]
    agents = list(DEFAULT_WORKERS)
    extra_agents = sorted(
        {
            str(task.get("assigned_agent", "")).strip()
            for task in tasks_list
            if str(task.get("assigned_agent", "")).strip()
            and str(task.get("assigned_agent", "")).strip() not in DEFAULT_WORKERS
        }
    )
    agents.extend(extra_agents)

    rows: list[dict[str, Any]] = []
    for agent in agents:
        running = next(
            (
                task
                for task in tasks_list
                if task.get("assigned_agent") == agent and task.get("state") == "running"
            ),
            None,
        )
        queued = [
            task
            for task in tasks_list
            if task.get("assigned_agent") == agent and task.get("state") == "queued"
        ]
        rows.append(
            {
                "agent": agent,
                "status": "busy" if running else "idle",
                "running_task_id": running.get("id") if running else None,
                "queued": len(queued),
            }
        )
    return rows


def queue_for_agent(tasks: Iterable[dict[str, Any]], agent: str) -> dict[str, Any]:
    tasks_list = [
        task for task in tasks if task.get("assigned_agent") == agent and str(task.get("assigned_agent") or "").strip()
    ]
    running = next((task for task in tasks_list if task.get("state") == "running"), None)
    queued = [task for task in tasks_list if task.get("state") == "queued"]
    queued.sort(key=lambda item: (item.get("createdAt", ""), item["job_id"], item["id"]))
    return {
        "agent": agent,
        "running_task_id": running.get("id") if running else None,
        "queued_tasks": queued,
    }
