from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .prompts import build_envelope_repair_prompt, build_role_prompt
from .runner import FakeCodexRunner, RunnerResult
from .schemas import schema_for_role
from .store import CodexTeamStore
from .validation import (
    ValidationIssue,
    filter_supplemental_artifacts,
    is_repairable_invalid_envelope,
    issues_to_payload,
    validate_fixed_artifact,
    validate_next_action_envelope,
)


@dataclass
class DispatchOutcome:
    run_id: str
    state: str
    status: str
    owner: str | None
    event: str
    error: dict[str, Any] | None = None


class CodexTeamDispatcher:
    def __init__(
        self,
        *,
        store: CodexTeamStore | None = None,
        runner: Any | None = None,
        max_fix_loops: int = 2,
        resume_repair_attempts: int = 2,
    ) -> None:
        self.store = store or CodexTeamStore()
        self.runner = runner or FakeCodexRunner([])
        self.max_fix_loops = max_fix_loops
        self.resume_repair_attempts = resume_repair_attempts

    def start_run(self, *, repo_root: Path, input_text: str) -> DispatchOutcome:
        metadata = self.store.create_run(repo_root=repo_root, input_text=input_text)
        run_id = str(metadata["run_id"])
        metadata = self.store.update_metadata(run_id, state="planning", current_owner="planner")
        self.store.append_event(run_id, {"type": "state_changed", "state": "planning", "owner": "planner"})
        return self._outcome(run_id, metadata, "started")

    def run_until_idle(self, run_id: str, *, max_steps: int = 50) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        outcome = DispatchOutcome(
            run_id=run_id,
            state=str(metadata.get("state")),
            status=str(metadata.get("status")),
            owner=metadata.get("current_owner"),
            event="loaded",
        )
        terminal_states = {"paused", "completed", "cancelled", "failed"}
        steps = 0
        while outcome.state not in terminal_states:
            if steps >= max_steps:
                return self._fail(run_id, "MaxStepsExceeded", f"codex team exceeded max_steps={max_steps}")
            outcome = self.step(run_id)
            steps += 1
        return outcome

    def step(self, run_id: str) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        owner = str(metadata.get("current_owner") or "planner")
        if owner not in {"planner", "generator", "evaluator"}:
            return self._fail(run_id, "InvalidOwner", f"cannot run owner {owner!r}")

        repo_root = Path(str(metadata["repo_root"]))
        run_home = self.store.run_home(run_id)
        if owner == "generator":
            self.store.create_attempt_dir(run_id)
        schema_path = run_home / "schemas" / f"{owner}.schema.json"
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(schema_for_role(owner), ensure_ascii=False, indent=2) + "\n")
        logs_dir = run_home / "artifacts" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        sequence = len(list(logs_dir.glob(f"{owner}-*.last-message.json"))) + 1
        output_path = logs_dir / f"{owner}-{sequence:03d}.last-message.json"
        prompt = build_role_prompt(role=owner, repo_root=repo_root, run_home=run_home, metadata=metadata)
        result = self.runner.run(
            role=owner,
            prompt=prompt,
            repo_root=repo_root,
            run_home=run_home,
            schema_path=schema_path,
            output_last_message_path=output_path,
        )
        if result.error:
            return self._record_runner_error(run_id, result)
        envelope = result.envelope
        if envelope is None and result.last_message_path and result.last_message_path.exists():
            try:
                envelope = json.loads(result.last_message_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                envelope = None
        return self._consume_envelope(run_id, owner, envelope, result=result, repair_attempts=0)

    def answer(self, run_id: str, answer: str) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        if metadata.get("state") != "paused":
            raise ValueError("answer is only allowed for paused codex team runs")
        self.store.append_answer(run_id, answer)
        self.store.clear_pending_question(run_id)
        self.store.append_event(run_id, {"type": "user_answered"})
        self.store.update_metadata(run_id, state="planning", current_owner="planner")
        return DispatchOutcome(run_id, "planning", "running", "planner", "user_answered")

    def cancel(self, run_id: str, reason: str) -> DispatchOutcome:
        self.store.append_event(run_id, {"type": "cancelled", "reason": reason})
        self.store.update_metadata(run_id, state="cancelled", status="cancelled", current_owner=None)
        return DispatchOutcome(run_id, "cancelled", "cancelled", None, "cancelled")

    def _consume_envelope(
        self,
        run_id: str,
        role: str,
        envelope: dict[str, Any] | None,
        *,
        result: RunnerResult,
        repair_attempts: int,
    ) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        run_home = self.store.run_home(run_id)
        repo_root = Path(str(metadata["repo_root"]))
        issues = validate_next_action_envelope(envelope, role=role, run_home=run_home, repo_root=repo_root)
        if not issues and envelope is not None:
            issues = self._validate_fixed_artifact(run_id, role, envelope)
        if issues:
            if self._can_repair(result, issues, repair_attempts):
                return self._repair_envelope(run_id, role, result, issues, repair_attempts + 1)
            return self._invalid(run_id, issues)

        assert envelope is not None
        envelope = self._with_filtered_artifacts(run_id, envelope)
        self.store.write_next_action(run_id, envelope)
        return self._route(run_id, role, envelope)

    def _can_repair(self, result: RunnerResult, issues: list[ValidationIssue], repair_attempts: int) -> bool:
        return (
            repair_attempts < self.resume_repair_attempts
            and result.session_id
            and is_repairable_invalid_envelope(issues)
        )

    def _repair_envelope(
        self,
        run_id: str,
        role: str,
        result: RunnerResult,
        issues: list[ValidationIssue],
        repair_attempts: int,
    ) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        run_home = self.store.run_home(run_id)
        repo_root = Path(str(metadata["repo_root"]))
        invalid_output = ""
        if result.last_message_path and result.last_message_path.exists():
            invalid_output = result.last_message_path.read_text(encoding="utf-8")
        else:
            invalid_output = json.dumps(result.envelope, ensure_ascii=False) if result.envelope is not None else ""
        prompt = build_envelope_repair_prompt(
            validator_errors=issues_to_payload(issues),
            invalid_output=invalid_output,
            preserve_checkpoint_semantics=_has_checkpoint_semantics(result.envelope),
        )
        repair_output = run_home / "artifacts" / "logs" / f"{role}-repair-{repair_attempts:03d}.last-message.json"
        self.store.append_event(run_id, {"type": "repair_started", "role": role, "attempt": repair_attempts})
        repaired = self.runner.run(
            role=role,
            prompt=prompt,
            repo_root=repo_root,
            run_home=run_home,
            output_last_message_path=repair_output,
            session_id=result.session_id,
            resume=True,
        )
        if repaired.error:
            return self._record_runner_error(run_id, repaired)
        if _has_checkpoint_semantics(result.envelope) and _upgrades_to_final_completion(repaired.envelope):
            return self._invalid(
                run_id,
                [
                    ValidationIssue(
                        "InvalidCompletionScope",
                        "repair cannot upgrade a checkpoint envelope to final completion; choose a checkpoint route instead",
                        "completion_scope",
                        repairable=False,
                    )
                ],
            )
        return self._consume_envelope(run_id, role, repaired.envelope, result=repaired, repair_attempts=repair_attempts)

    def _validate_fixed_artifact(self, run_id: str, role: str, envelope: dict[str, Any]) -> list[ValidationIssue]:
        path = self._fixed_artifact_path(run_id, role, envelope)
        if path is None:
            return []
        return validate_fixed_artifact(path, run_home=self.store.run_home(run_id), field_path=f"{role}.fixed_artifact")

    def _fixed_artifact_path(self, run_id: str, role: str, envelope: dict[str, Any]) -> Path | None:
        run_home = self.store.run_home(run_id)
        if role == "planner":
            return run_home / "plan.md"
        if role == "generator":
            attempt = int(self.store.load_metadata(run_id).get("current_attempt") or 0) + 1
            return self.store.attempt_dir(run_id, attempt) / "implementation.md"
        if role == "evaluator":
            metadata = self.store.load_metadata(run_id)
            if metadata.get("state") == "evaluating_plan":
                return run_home / "plan_evaluation.md"
            attempt = int(metadata.get("current_attempt") or 1)
            return self.store.attempt_dir(run_id, attempt) / "evaluation.md"
        return None

    def _with_filtered_artifacts(self, run_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        metadata = self.store.load_metadata(run_id)
        result = filter_supplemental_artifacts(
            list(envelope.get("artifacts") or []),
            run_home=self.store.run_home(run_id),
            repo_root=Path(str(metadata["repo_root"])),
        )
        if result.dropped:
            self.store.append_event(run_id, {"type": "supplemental_artifacts_dropped", "artifacts": result.dropped})
        filtered = dict(envelope)
        filtered["artifacts"] = result.retained
        return filtered

    def _route(self, run_id: str, role: str, envelope: dict[str, Any]) -> DispatchOutcome:
        action = str(envelope["action"])
        target = str(envelope["target"])
        self.store.append_event(
            run_id,
            {
                "type": "route",
                "role": role,
                "action": action,
                "target": target,
                "reason": envelope.get("reason"),
            },
        )

        if action == "ask_user" and role == "planner" and target == "user":
            question = str(envelope.get("reason") or envelope.get("summary") or "Codex Team needs user input.")
            self.store.write_pending_question(run_id, question, {"summary": envelope.get("summary")})
            metadata = self.store.update_metadata(run_id, state="paused", current_owner="user")
            return self._outcome(run_id, metadata, "paused")

        if action == "stop" and target == "system":
            metadata = self.store.update_metadata(run_id, state="completed", status="completed", current_owner=None)
            return self._outcome(run_id, metadata, "completed")

        if action == "pass" and role == "evaluator" and target == "system":
            metadata = self.store.load_metadata(run_id)
            latest_eval_key = "latest_plan_evaluation" if metadata.get("state") == "evaluating_plan" else "latest_evaluation"
            metadata = self.store.update_metadata(
                run_id,
                state="completed",
                status="completed",
                current_owner=None,
                **{latest_eval_key: str(self._fixed_artifact_path(run_id, "evaluator", envelope))},
            )
            return self._outcome(run_id, metadata, "completed")

        if role == "generator" and action == "candidate_ready" and target == "evaluator":
            attempt = int(self.store.load_metadata(run_id).get("current_attempt") or 0) + 1
            metadata = self.store.update_metadata(
                run_id,
                state="evaluating_milestone",
                current_owner="evaluator",
                current_attempt=attempt,
                latest_implementation=str(self.store.attempt_dir(run_id, attempt) / "implementation.md"),
            )
            return self._outcome(run_id, metadata, "candidate_marked")

        if role == "evaluator":
            return self._route_evaluator_result(run_id, action, target)

        if role == "planner" and action == "continue" and target == "evaluator":
            metadata = self.store.update_metadata(run_id, state="evaluating_plan", current_owner="evaluator")
            return self._outcome(run_id, metadata, "routed")

        if target in {"planner", "generator", "evaluator"}:
            metadata = self.store.update_metadata(run_id, state=_state_for_owner(target), current_owner=target)
            return self._outcome(run_id, metadata, "routed")

        return self._invalid(
            run_id,
            [
                ValidationIssue(
                    "InvalidNextAction",
                    f"unsupported route {role}:{action}->{target}",
                    "action",
                    repairable=True,
                )
            ],
        )

    def _route_evaluator_result(self, run_id: str, action: str, target: str) -> DispatchOutcome:
        metadata = self.store.load_metadata(run_id)
        latest_eval_key = "latest_plan_evaluation" if metadata.get("state") == "evaluating_plan" else "latest_evaluation"
        updates: dict[str, Any] = {
            latest_eval_key: str(self._fixed_artifact_path(run_id, "evaluator", {"action": action})),
        }
        if action == "needs_fix" and target == "generator":
            count = int(metadata.get("fix_loop_count") or 0) + 1
            updates["fix_loop_count"] = count
            if count > self.max_fix_loops:
                updates.update({"state": "planning", "current_owner": "planner"})
            else:
                updates.update({"state": "generating", "current_owner": "generator"})
        elif action == "continue" and target == "generator":
            updates.update({"state": "generating", "current_owner": "generator", "fix_loop_count": 0})
        elif action == "needs_design" and target == "planner":
            updates.update({"state": "planning", "current_owner": "planner"})
        elif action == "stop" and target == "system":
            updates.update({"state": "completed", "status": "completed", "current_owner": None})
        else:
            return self._invalid(
                run_id,
                [
                    ValidationIssue(
                        "InvalidNextAction",
                        f"unsupported evaluator route {action!r}->{target!r}",
                        "action",
                        repairable=True,
                    )
                ],
            )
        metadata = self.store.update_metadata(run_id, **updates)
        return self._outcome(run_id, metadata, "routed")

    def _record_runner_error(self, run_id: str, result: RunnerResult) -> DispatchOutcome:
        error = dict(result.error or {"code": "RunnerFailed", "message": "runner failed"})
        details = dict(error.get("details") or {})
        if result.stdout_tail and "stdout_tail" not in details:
            details["stdout_tail"] = result.stdout_tail
        if result.stderr_tail and "stderr_tail" not in details:
            details["stderr_tail"] = result.stderr_tail
        if result.last_message_path and "last_message_path" not in details:
            details["last_message_path"] = str(result.last_message_path)
        if details:
            error["details"] = details
        self.store.append_event(run_id, {"type": "runner_error", "error": error})
        metadata = self.store.update_metadata(run_id, state="failed", status="failed", last_error=error)
        return self._outcome(run_id, metadata, "runner_error", error=error)

    def _invalid(self, run_id: str, issues: list[ValidationIssue]) -> DispatchOutcome:
        error = {"code": issues[0].code, "issues": issues_to_payload(issues)}
        self.store.append_event(run_id, {"type": "invalid_output", "error": error})
        metadata = self.store.update_metadata(run_id, state="failed", status="failed", last_error=error)
        return self._outcome(run_id, metadata, "invalid_output", error=error)

    def _fail(self, run_id: str, code: str, message: str) -> DispatchOutcome:
        error = {"code": code, "message": message}
        self.store.append_event(run_id, {"type": "failed", "error": error})
        metadata = self.store.update_metadata(run_id, state="failed", status="failed", last_error=error)
        return self._outcome(run_id, metadata, "failed", error=error)

    @staticmethod
    def _outcome(
        run_id: str,
        metadata: dict[str, Any],
        event: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> DispatchOutcome:
        return DispatchOutcome(
            run_id=run_id,
            state=str(metadata.get("state")),
            status=str(metadata.get("status")),
            owner=metadata.get("current_owner"),
            event=event,
            error=error,
        )


def _state_for_owner(owner: str) -> str:
    return {
        "planner": "planning",
        "generator": "generating",
        "evaluator": "evaluating_milestone",
    }[owner]


def _has_checkpoint_semantics(envelope: dict[str, Any] | None) -> bool:
    return isinstance(envelope, dict) and envelope.get("completion_scope") == "checkpoint"


def _upgrades_to_final_completion(envelope: dict[str, Any] | None) -> bool:
    return isinstance(envelope, dict) and envelope.get("completion_scope") == "final"
