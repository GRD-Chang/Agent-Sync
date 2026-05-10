from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from task_bridge.store import make_id, now_iso, resolve_home

from .types import SCHEMA_VERSION


class CodexTeamStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = resolve_home(home)
        self.runs_dir = self.home / "codex-team" / "runs"

    def ensure_dirs(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        *,
        repo_root: Path,
        input_text: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_dirs()
        actual_run_id = run_id or make_id("codex-run")
        run_home = self.run_home(actual_run_id)
        if run_home.exists():
            raise FileExistsError(f"codex team run already exists: {actual_run_id}")
        self._ensure_run_layout(run_home)
        (run_home / "input.md").write_text(input_text, encoding="utf-8")
        now = now_iso()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "run_id": actual_run_id,
            "repo_root": str(repo_root.expanduser().resolve()),
            "run_home": str(run_home),
            "state": "created",
            "status": "running",
            "current_owner": "planner",
            "current_attempt": 0,
            "current_milestone_id": None,
            "latest_implementation": None,
            "latest_plan_evaluation": None,
            "latest_evaluation": None,
            "last_error": None,
            "sessions": {},
            "fix_loop_count": 0,
            "createdAt": now,
            "updatedAt": now,
        }
        self.save_metadata(actual_run_id, metadata)
        self.append_event(actual_run_id, {"type": "run_created", "state": "created"})
        return metadata

    def run_home(self, run_id: str) -> Path:
        return (self.runs_dir / run_id).resolve()

    def run_exists(self, run_id: str) -> bool:
        return self.metadata_path(run_id).exists()

    def metadata_path(self, run_id: str) -> Path:
        return self.run_home(run_id) / "metadata.json"

    def events_path(self, run_id: str) -> Path:
        return self.run_home(run_id) / "events.jsonl"

    def next_action_path(self, run_id: str) -> Path:
        return self.run_home(run_id) / "next_action.json"

    def pending_question_path(self, run_id: str) -> Path:
        return self.run_home(run_id) / "pending_question.json"

    def answers_path(self, run_id: str) -> Path:
        return self.run_home(run_id) / "answers.jsonl"

    def load_metadata(self, run_id: str) -> dict[str, Any]:
        path = self.metadata_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"codex team run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_metadata(self, run_id: str, metadata: dict[str, Any]) -> None:
        payload = dict(metadata)
        payload["updatedAt"] = now_iso()
        self._atomic_write_json(self.metadata_path(run_id), payload)

    def update_metadata(self, run_id: str, **updates: Any) -> dict[str, Any]:
        metadata = self.load_metadata(run_id)
        metadata.update(updates)
        self.save_metadata(run_id, metadata)
        return self.load_metadata(run_id)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        path = self.events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "at": now_iso(),
            **event,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.events_path(run_id)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def create_attempt_dir(self, run_id: str, attempt: int | None = None) -> Path:
        if attempt is None:
            attempt = int(self.load_metadata(run_id).get("current_attempt") or 0) + 1
        attempt_dir = self.attempt_dir(run_id, attempt)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def attempt_dir(self, run_id: str, attempt: int) -> Path:
        return self.run_home(run_id) / "attempts" / f"{attempt:03d}"

    def write_next_action(self, run_id: str, envelope: dict[str, Any]) -> None:
        self._atomic_write_json(self.next_action_path(run_id), envelope)

    def load_next_action(self, run_id: str) -> dict[str, Any]:
        return json.loads(self.next_action_path(run_id).read_text(encoding="utf-8"))

    def write_pending_question(self, run_id: str, question: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        question_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "question": question,
            "payload": payload or {},
            "created_at": now_iso(),
        }
        self._atomic_write_json(self.pending_question_path(run_id), question_payload)
        return question_payload

    def append_answer(self, run_id: str, answer: str) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "answer": answer,
            "created_at": now_iso(),
        }
        path = self.answers_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    def clear_pending_question(self, run_id: str) -> None:
        try:
            self.pending_question_path(run_id).unlink()
        except FileNotFoundError:
            pass

    def is_inside_run_home(self, run_id: str, path: str | Path) -> bool:
        run_home = self.run_home(run_id)
        try:
            real_path = Path(path).expanduser().resolve()
            real_path.relative_to(run_home)
        except (OSError, ValueError):
            return False
        return True

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.runs_dir.exists():
            return []
        runs = []
        for path in sorted(self.runs_dir.glob("*/metadata.json")):
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        runs.sort(key=lambda item: (item.get("createdAt", ""), item.get("run_id", "")))
        return runs

    def _ensure_run_layout(self, run_home: Path) -> None:
        for path in (
            run_home,
            run_home / "attempts",
            run_home / "artifacts" / "logs",
            run_home / "artifacts" / "test-output",
            run_home / "schemas",
        ):
            path.mkdir(parents=True, exist_ok=True)

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
