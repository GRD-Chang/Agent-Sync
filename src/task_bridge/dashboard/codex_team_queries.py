from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from task_bridge.codex_team.store import CodexTeamStore

from .formatting import format_timestamp_for_client, parse_timestamp, truncate
from .i18n import DEFAULT_LOCALE, get_messages, resolve_locale


ARTIFACT_CHAR_LIMIT = 8000
LOG_CHAR_LIMIT = 6000


@dataclass(frozen=True)
class CodexTeamRunListItem:
    run_id: str
    state: str
    status: str
    repo_root: str
    current_owner: str | None
    current_attempt: int
    created_at: str
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
    duration_label: str
    last_action: str | None
    last_target: str | None
    last_reason: str | None
    last_error_code: str | None
    needs_user_input: bool
    detail_href: str


@dataclass(frozen=True)
class CodexTeamRunsSnapshot:
    home_path: str
    runs_dir: str
    generated_at: str
    generated_at_iso: str | None
    run_count: int
    active_count: int
    completed_count: int
    failed_count: int
    waiting_count: int
    runs: list[CodexTeamRunListItem]
    is_empty: bool


@dataclass(frozen=True)
class CodexTeamFlowNode:
    node_id: str
    role: str
    status: str
    state: str | None
    attempt: int | None
    started_at: str
    started_at_iso: str | None
    ended_at: str
    ended_at_iso: str | None
    duration_label: str
    action: str | None
    target: str | None
    reason: str | None
    returncode: int | None
    last_message_path: str | None
    last_message_href: str | None
    stdout_log: str | None
    stdout_href: str | None
    stderr_log: str | None
    stderr_href: str | None
    artifact_href: str | None
    is_inferred: bool = False


@dataclass(frozen=True)
class CodexTeamPreviewSegment:
    kind: str
    text: str
    level: int = 0


@dataclass(frozen=True)
class CodexTeamPreview:
    key: str
    label: str
    kind: str
    path: str
    status: str
    text: str
    anchor: str
    is_truncated: bool = False
    error_message: str | None = None
    action: str | None = None
    target: str | None = None
    reason: str | None = None
    line_count: int = 0
    size_label: str = "0 B"
    segments: tuple[CodexTeamPreviewSegment, ...] = ()


@dataclass(frozen=True)
class CodexTeamRouteDecision:
    action: str | None
    target: str | None
    reason: str | None
    status: str


@dataclass(frozen=True)
class CodexTeamRunDetailSnapshot:
    run_id: str
    repo_root: str
    run_home: str
    state: str
    status: str
    current_owner: str | None
    current_attempt: int
    created_at: str
    created_at_iso: str | None
    updated_at: str
    updated_at_iso: str | None
    duration_label: str
    needs_user_input: bool
    pending_question: CodexTeamPreview | None
    last_error_code: str | None
    last_error_text: str | None
    route_decision: CodexTeamRouteDecision
    flow_nodes: list[CodexTeamFlowNode]
    artifacts: list[CodexTeamPreview]
    logs: list[CodexTeamPreview]
    events_status: str
    back_href: str


class CodexTeamDashboardQueryService:
    def __init__(
        self,
        home: Path | None = None,
        *,
        now_provider: Any,
        locale: str = DEFAULT_LOCALE,
        timezone: str | None = None,
    ) -> None:
        self.store = CodexTeamStore(home)
        self._now_provider = now_provider
        self._locale = resolve_locale(locale)
        self._timezone = timezone.strip() if timezone else None
        self._messages = get_messages(self._locale)["codex_team"]

    @property
    def home_path(self) -> str:
        return str(self.store.home)

    def runs(self) -> CodexTeamRunsSnapshot:
        runs = [self._run_item(metadata) for metadata in self.store.list_runs()]
        runs.sort(key=lambda item: (item.updated_at_iso or "", item.run_id), reverse=True)
        generated = self._format_time(self._now_provider())
        return CodexTeamRunsSnapshot(
            home_path=self.home_path,
            runs_dir=str(self.store.runs_dir),
            generated_at=generated.display,
            generated_at_iso=generated.raw_iso,
            run_count=len(runs),
            active_count=sum(1 for item in runs if item.status == "running"),
            completed_count=sum(1 for item in runs if item.status == "completed"),
            failed_count=sum(1 for item in runs if item.status == "failed"),
            waiting_count=sum(1 for item in runs if item.needs_user_input),
            runs=runs,
            is_empty=not runs,
        )

    def run_detail(self, run_id: str) -> CodexTeamRunDetailSnapshot | None:
        try:
            metadata = self.store.load_metadata(run_id)
        except FileNotFoundError:
            return None
        events, events_status = self._safe_events(run_id)
        run_home = self.store.run_home(run_id)
        pending_question = self._preview_path(
            run_id,
            "pending_question",
            self._messages["artifact_pending_question"],
            run_home / "pending_question.json",
            "json",
        )
        if pending_question.status == "missing":
            pending_question = None
        route = self._route_decision(run_id)
        created = self._format_time(str(metadata.get("createdAt") or ""))
        updated = self._format_time(str(metadata.get("updatedAt") or ""))
        error = metadata.get("last_error") if isinstance(metadata.get("last_error"), dict) else {}
        return CodexTeamRunDetailSnapshot(
            run_id=run_id,
            repo_root=str(metadata.get("repo_root") or ""),
            run_home=str(metadata.get("run_home") or run_home),
            state=str(metadata.get("state") or "unknown"),
            status=str(metadata.get("status") or "unknown"),
            current_owner=_optional_str(metadata.get("current_owner")),
            current_attempt=_safe_int(metadata.get("current_attempt")),
            created_at=created.display,
            created_at_iso=created.raw_iso,
            updated_at=updated.display,
            updated_at_iso=updated.raw_iso,
            duration_label=_duration_between(str(metadata.get("createdAt") or ""), str(metadata.get("updatedAt") or "")),
            needs_user_input=self._needs_user_input(run_id, metadata),
            pending_question=pending_question,
            last_error_code=_optional_str(error.get("code")),
            last_error_text=_error_text(error),
            route_decision=route,
            flow_nodes=self._flow_nodes(run_id, metadata, events),
            artifacts=self._artifacts(run_id, metadata),
            logs=self._logs(run_id),
            events_status=events_status,
            back_href=self._path_with_locale("/codex-team"),
        )

    def _run_item(self, metadata: dict[str, Any]) -> CodexTeamRunListItem:
        run_id = str(metadata.get("run_id") or "")
        route = self._route_decision(run_id)
        created = self._format_time(str(metadata.get("createdAt") or ""))
        updated = self._format_time(str(metadata.get("updatedAt") or ""))
        error = metadata.get("last_error") if isinstance(metadata.get("last_error"), dict) else {}
        return CodexTeamRunListItem(
            run_id=run_id,
            state=str(metadata.get("state") or "unknown"),
            status=str(metadata.get("status") or "unknown"),
            repo_root=str(metadata.get("repo_root") or ""),
            current_owner=_optional_str(metadata.get("current_owner")),
            current_attempt=_safe_int(metadata.get("current_attempt")),
            created_at=created.display,
            created_at_iso=created.raw_iso,
            updated_at=updated.display,
            updated_at_iso=updated.raw_iso,
            duration_label=_duration_between(str(metadata.get("createdAt") or ""), str(metadata.get("updatedAt") or "")),
            last_action=route.action,
            last_target=route.target,
            last_reason=route.reason,
            last_error_code=_optional_str(error.get("code")),
            needs_user_input=self._needs_user_input(run_id, metadata),
            detail_href=self._path_with_locale(f"/codex-team/{run_id}"),
        )

    def _flow_nodes(
        self,
        run_id: str,
        metadata: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> list[CodexTeamFlowNode]:
        nodes: list[dict[str, Any]] = []
        active: dict[str, dict[str, Any]] = {}

        def add_route_node(event: dict[str, Any]) -> None:
            role = str(event.get("role") or "unknown")
            for node in reversed(nodes):
                if node.get("role") == role and not node.get("action"):
                    node.update(
                        {
                            "action": _optional_str(event.get("action")),
                            "target": _optional_str(event.get("target")),
                            "reason": _optional_str(event.get("reason")),
                        }
                    )
                    return
            nodes.append(
                {
                    "node_id": f"route-{len(nodes) + 1}",
                    "role": role,
                    "status": "completed",
                    "state": None,
                    "attempt": None,
                    "started_at": _optional_str(event.get("at")),
                    "ended_at": _optional_str(event.get("at")),
                    "duration_seconds": None,
                    "action": _optional_str(event.get("action")),
                    "target": _optional_str(event.get("target")),
                    "reason": _optional_str(event.get("reason")),
                    "returncode": None,
                    "last_message_path": None,
                    "stdout_log": None,
                    "stderr_log": None,
                    "is_inferred": True,
                }
            )

        for event in events:
            event_type = event.get("type")
            if event_type == "agent_step_started":
                invocation_id = str(event.get("invocation_id") or f"step-{len(active) + 1}")
                active[invocation_id] = dict(event)
                continue
            if event_type == "agent_step_finished":
                invocation_id = str(event.get("invocation_id") or "")
                started = active.pop(invocation_id, {})
                node = {
                    "node_id": invocation_id or f"step-{len(nodes) + 1}",
                    "role": str(event.get("role") or started.get("role") or "unknown"),
                    "status": str(event.get("status") or "completed"),
                    "state": _optional_str(started.get("state")),
                    "attempt": _optional_int(started.get("attempt")),
                    "started_at": _optional_str(started.get("at")),
                    "ended_at": _optional_str(event.get("at")),
                    "duration_seconds": event.get("duration_seconds"),
                    "action": None,
                    "target": None,
                    "reason": None,
                    "returncode": _optional_int(event.get("returncode")),
                    "last_message_path": _safe_display_path(run_id, event.get("last_message_path"), self.store),
                    "stdout_log": _safe_display_path(run_id, event.get("stdout_log"), self.store),
                    "stderr_log": _safe_display_path(run_id, event.get("stderr_log"), self.store),
                    "is_inferred": False,
                }
                nodes.append(node)
                continue
            if event_type == "route":
                add_route_node(event)
                continue
            if event_type in {"runner_error", "invalid_output"}:
                owner = _error_owner(event.get("error")) or _optional_str(metadata.get("current_owner")) or "unknown"
                error_text = _error_text(event.get("error"))
                error_node = _find_error_node(nodes, owner, event.get("error"))
                if error_node is not None:
                    error_node["status"] = "failed"
                    if error_text:
                        error_node["reason"] = error_text
                else:
                    nodes.append(
                        {
                            "node_id": f"error-{len(nodes) + 1}",
                            "role": owner,
                            "status": "failed",
                            "state": _optional_str(metadata.get("state")),
                            "attempt": _optional_int(metadata.get("current_attempt")),
                            "started_at": _optional_str(event.get("at")),
                            "ended_at": _optional_str(event.get("at")),
                            "duration_seconds": None,
                            "action": None,
                            "target": None,
                            "reason": error_text,
                            "returncode": None,
                            "last_message_path": None,
                            "stdout_log": None,
                            "stderr_log": None,
                            "is_inferred": True,
                        }
                    )

        for invocation_id, started in active.items():
            nodes.append(
                {
                    "node_id": invocation_id,
                    "role": str(started.get("role") or "unknown"),
                    "status": "running",
                    "state": _optional_str(started.get("state")),
                    "attempt": _optional_int(started.get("attempt")),
                    "started_at": _optional_str(started.get("at")),
                    "ended_at": None,
                    "duration_seconds": None,
                    "action": None,
                    "target": None,
                    "reason": None,
                    "returncode": None,
                    "last_message_path": _safe_display_path(run_id, started.get("last_message_path"), self.store),
                    "stdout_log": _safe_display_path(run_id, started.get("stdout_log"), self.store),
                    "stderr_log": _safe_display_path(run_id, started.get("stderr_log"), self.store),
                    "is_inferred": False,
                }
            )

        if not nodes:
            nodes = self._artifact_fallback_nodes(run_id, metadata)

        return [self._node_from_dict(run_id, node) for node in nodes]

    def _node_from_dict(self, run_id: str, node: dict[str, Any]) -> CodexTeamFlowNode:
        started = self._format_time(str(node.get("started_at") or ""))
        ended = self._format_time(str(node.get("ended_at") or ""))
        artifact_href = self._artifact_href_for_role(run_id, str(node.get("role") or ""), node.get("attempt"))
        last_message_path = _optional_str(node.get("last_message_path"))
        stdout_log = _optional_str(node.get("stdout_log"))
        stderr_log = _optional_str(node.get("stderr_log"))
        duration_value = node.get("duration_seconds")
        return CodexTeamFlowNode(
            node_id=str(node.get("node_id") or "node"),
            role=str(node.get("role") or "unknown"),
            status=str(node.get("status") or "unknown"),
            state=_optional_str(node.get("state")),
            attempt=_optional_int(node.get("attempt")),
            started_at=started.display,
            started_at_iso=started.raw_iso,
            ended_at=ended.display,
            ended_at_iso=ended.raw_iso,
            duration_label=_duration_label(duration_value),
            action=_optional_str(node.get("action")),
            target=_optional_str(node.get("target")),
            reason=_optional_str(node.get("reason")),
            returncode=_optional_int(node.get("returncode")),
            last_message_path=last_message_path,
            last_message_href=self._log_href_for_display_path(run_id, last_message_path),
            stdout_log=stdout_log,
            stdout_href=self._log_href_for_display_path(run_id, stdout_log),
            stderr_log=stderr_log,
            stderr_href=self._log_href_for_display_path(run_id, stderr_log),
            artifact_href=artifact_href,
            is_inferred=bool(node.get("is_inferred")),
        )

    def _artifact_fallback_nodes(self, run_id: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        run_home = self.store.run_home(run_id)
        nodes: list[dict[str, Any]] = []
        if (run_home / "plan.md").exists():
            nodes.append({"node_id": "artifact-planner", "role": "planner", "status": "artifact", "attempt": 0})
        if (run_home / "plan_evaluation.md").exists():
            nodes.append({"node_id": "artifact-plan-evaluator", "role": "evaluator", "status": "artifact", "attempt": 0})
        for attempt_dir in sorted((run_home / "attempts").glob("[0-9][0-9][0-9]")):
            attempt = _safe_int(attempt_dir.name)
            if (attempt_dir / "implementation.md").exists():
                nodes.append({"node_id": f"artifact-generator-{attempt}", "role": "generator", "status": "artifact", "attempt": attempt})
            if (attempt_dir / "evaluation.md").exists():
                nodes.append({"node_id": f"artifact-evaluator-{attempt}", "role": "evaluator", "status": "artifact", "attempt": attempt})
        if not nodes:
            nodes.append(
                {
                    "node_id": "metadata-current-owner",
                    "role": str(metadata.get("current_owner") or "planner"),
                    "status": str(metadata.get("status") or "unknown"),
                    "state": str(metadata.get("state") or "unknown"),
                    "attempt": _safe_int(metadata.get("current_attempt")),
                }
            )
        return nodes

    def _artifacts(self, run_id: str, metadata: dict[str, Any]) -> list[CodexTeamPreview]:
        run_home = self.store.run_home(run_id)
        previews = [
            self._preview_path(run_id, "input", self._messages["artifact_input"], run_home / "input.md", "markdown"),
            self._preview_path(run_id, "plan", self._messages["artifact_plan"], run_home / "plan.md", "markdown"),
            self._preview_path(
                run_id,
                "plan_evaluation",
                self._messages["artifact_plan_evaluation"],
                run_home / "plan_evaluation.md",
                "markdown",
            ),
        ]
        for attempt_dir in sorted((run_home / "attempts").glob("[0-9][0-9][0-9]")):
            attempt = attempt_dir.name
            previews.append(
                self._preview_path(
                    run_id,
                    f"implementation_{attempt}",
                    self._messages["artifact_implementation"].format(attempt=attempt),
                    attempt_dir / "implementation.md",
                    "markdown",
                )
            )
            previews.append(
                self._preview_path(
                    run_id,
                    f"evaluation_{attempt}",
                    self._messages["artifact_evaluation"].format(attempt=attempt),
                    attempt_dir / "evaluation.md",
                    "markdown",
                )
            )
        previews.extend(
            [
                self._preview_path(run_id, "next_action", self._messages["artifact_next_action"], run_home / "next_action.json", "json"),
                self._preview_path(run_id, "metadata", self._messages["artifact_metadata"], run_home / "metadata.json", "json"),
                self._preview_path(
                    run_id,
                    "pending_question",
                    self._messages["artifact_pending_question"],
                    run_home / "pending_question.json",
                    "json",
                ),
                self._preview_path(run_id, "answers", self._messages["artifact_answers"], run_home / "answers.jsonl", "jsonl"),
            ]
        )
        return previews

    def _logs(self, run_id: str) -> list[CodexTeamPreview]:
        logs_dir = self.store.run_home(run_id) / "artifacts" / "logs"
        if not logs_dir.exists():
            return []
        logs: list[CodexTeamPreview] = []
        for path in sorted(logs_dir.glob("*")):
            if path.is_file():
                kind = "json" if path.name.endswith(".json") else "log"
                logs.append(self._preview_path(run_id, _log_preview_key(path), path.name, path, kind, char_limit=LOG_CHAR_LIMIT))
        return logs

    def _preview_path(
        self,
        run_id: str,
        key: str,
        label: str,
        path: Path,
        kind: str,
        *,
        char_limit: int = ARTIFACT_CHAR_LIMIT,
    ) -> CodexTeamPreview:
        anchor = f"artifact-{key}"
        path_value = str(path)
        if not self.store.is_inside_run_home(run_id, path):
            return CodexTeamPreview(key, label, kind, path_value, "unsafe", "", anchor, error_message=self._messages["unsafe_path"])
        try:
            real_path = path.resolve()
        except OSError as exc:
            return CodexTeamPreview(key, label, kind, path_value, "error", "", anchor, error_message=str(exc))
        if not real_path.exists():
            return CodexTeamPreview(key, label, kind, path_value, "missing", "", anchor)
        if not real_path.is_file():
            return CodexTeamPreview(key, label, kind, path_value, "error", "", anchor, error_message=self._messages["not_file"])
        try:
            data = real_path.read_bytes()
        except OSError as exc:
            return CodexTeamPreview(key, label, kind, path_value, "error", "", anchor, error_message=str(exc))
        is_truncated = len(data) > char_limit
        text = data[:char_limit].decode("utf-8", errors="replace")
        line_count = text.count("\n") + (1 if text else 0)
        size_label = _format_bytes(len(data))
        if not text.strip():
            return CodexTeamPreview(key, label, kind, path_value, "empty", "", anchor, line_count=0, size_label=size_label)
        action = target = reason = None
        if kind == "json":
            try:
                payload = json.loads(real_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    action = _optional_str(payload.get("action"))
                    target = _optional_str(payload.get("target"))
                    reason = _optional_str(payload.get("reason"))
                text = json.dumps(payload, ensure_ascii=False, indent=2)
                if len(text) > char_limit:
                    text = text[:char_limit]
                    is_truncated = True
                line_count = text.count("\n") + 1
            except (json.JSONDecodeError, OSError) as exc:
                return CodexTeamPreview(
                    key,
                    label,
                    kind,
                    path_value,
                    "error",
                    text,
                    anchor,
                    is_truncated,
                    str(exc),
                    line_count=line_count,
                    size_label=size_label,
                )
        elif kind == "jsonl":
            rows: list[Any] = []
            try:
                for line in real_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
                text = json.dumps(rows, ensure_ascii=False, indent=2)
                if len(text) > char_limit:
                    text = text[:char_limit]
                    is_truncated = True
                line_count = text.count("\n") + 1
            except (json.JSONDecodeError, OSError) as exc:
                return CodexTeamPreview(
                    key,
                    label,
                    kind,
                    path_value,
                    "error",
                    text,
                    anchor,
                    is_truncated,
                    str(exc),
                    line_count=line_count,
                    size_label=size_label,
                )
        segments: tuple[CodexTeamPreviewSegment, ...] = ()
        if kind == "markdown":
            segments = _markdown_segments(text.rstrip())
        return CodexTeamPreview(
            key=key,
            label=label,
            kind=kind,
            path=path_value,
            status="rendered",
            text=text.rstrip(),
            anchor=anchor,
            is_truncated=is_truncated,
            action=action,
            target=target,
            reason=reason,
            line_count=line_count,
            size_label=size_label,
            segments=segments,
        )

    def _route_decision(self, run_id: str) -> CodexTeamRouteDecision:
        try:
            envelope = self.store.load_next_action(run_id)
        except (FileNotFoundError, json.JSONDecodeError):
            return CodexTeamRouteDecision(None, None, None, "missing")
        return CodexTeamRouteDecision(
            _optional_str(envelope.get("action")),
            _optional_str(envelope.get("target")),
            _optional_str(envelope.get("reason")),
            "available",
        )

    def _needs_user_input(self, run_id: str, metadata: dict[str, Any]) -> bool:
        return metadata.get("state") == "paused" or metadata.get("current_owner") == "user" or self.store.pending_question_path(run_id).exists()

    def _safe_events(self, run_id: str) -> tuple[list[dict[str, Any]], str]:
        path = self.store.events_path(run_id)
        if not path.exists():
            return [], "missing"
        events: list[dict[str, Any]] = []
        status = "available"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return [], "error"
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                status = "partial"
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events, status

    def _artifact_href_for_role(self, run_id: str, role: str, attempt: object) -> str | None:
        if role == "planner":
            return self._path_with_locale(f"/codex-team/{run_id}") + "#artifact-plan"
        if role == "generator":
            attempt_id = f"{_safe_int(attempt):03d}"
            return self._path_with_locale(f"/codex-team/{run_id}") + f"#artifact-implementation_{attempt_id}"
        if role == "evaluator":
            attempt_int = _safe_int(attempt)
            anchor = "plan_evaluation" if attempt_int <= 0 else f"evaluation_{attempt_int:03d}"
            return self._path_with_locale(f"/codex-team/{run_id}") + f"#artifact-{anchor}"
        return None

    def _log_href_for_display_path(self, run_id: str, path_value: str | None) -> str | None:
        if not path_value:
            return None
        path = Path(path_value)
        if not self.store.is_inside_run_home(run_id, path):
            return None
        if path.parent != self.store.run_home(run_id) / "artifacts" / "logs":
            return None
        return self._path_with_locale(f"/codex-team/{run_id}") + f"#artifact-{_log_preview_key(path)}"

    def _format_time(self, value: str):
        return format_timestamp_for_client(value, fallback=self._messages["unknown"])

    def _path_with_locale(self, path: str) -> str:
        query_items = []
        if self._timezone:
            query_items.append(("tz", self._timezone))
        if self._locale != DEFAULT_LOCALE:
            query_items.append(("lang", self._locale))
        if not query_items:
            return path
        return f"{path}?{urlencode(query_items)}"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_between(start_value: str, end_value: str) -> str:
    start = parse_timestamp(start_value)
    end = parse_timestamp(end_value)
    if start is None or end is None:
        return "unknown"
    seconds = max((end - start).total_seconds(), 0)
    return _format_seconds(seconds)


def _duration_label(value: object) -> str:
    try:
        return _format_seconds(float(value))
    except (TypeError, ValueError):
        return "unknown"


def _format_seconds(seconds: float) -> str:
    seconds = max(seconds, 0)
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"
    minutes, remainder = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _log_preview_key(path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.name).strip("_").lower()
    return f"log_{slug or 'file'}"


def _markdown_segments(text: str) -> tuple[CodexTeamPreviewSegment, ...]:
    segments: list[CodexTeamPreviewSegment] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            segments.append(CodexTeamPreviewSegment("paragraph", " ".join(paragraph)))
            paragraph.clear()

    def flush_code() -> None:
        if code_lines:
            segments.append(CodexTeamPreviewSegment("code", "\n".join(code_lines).rstrip()))
            code_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                in_code = True
            continue
        if in_code:
            code_lines.append(raw_line)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            segments.append(CodexTeamPreviewSegment("heading", heading.group(2).strip(), len(heading.group(1))))
            continue
        if line.lstrip().startswith(("- ", "* ")):
            flush_paragraph()
            segments.append(CodexTeamPreviewSegment("list_item", line.lstrip()[2:].strip()))
            continue
        paragraph.append(line.strip())
    flush_paragraph()
    flush_code()
    return tuple(segments)


def _error_text(error: object) -> str | None:
    if not isinstance(error, dict):
        return None
    code = _optional_str(error.get("code"))
    message = _optional_str(error.get("message"))
    if message and code:
        return f"{code}: {truncate(message, 180)}"
    return code or message


def _error_owner(error: object) -> str | None:
    if not isinstance(error, dict):
        return None
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    return _optional_str(details.get("failed_owner"))


def _find_error_node(nodes: list[dict[str, Any]], owner: str, error: object) -> dict[str, Any] | None:
    if not isinstance(error, dict):
        details: dict[str, Any] = {}
    else:
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
    failed_attempt = _optional_int(details.get("failed_attempt"))
    failed_state = _optional_str(details.get("failed_state"))
    last_message_path = _optional_str(details.get("last_message_path"))

    def role_matches(node: dict[str, Any]) -> bool:
        return node.get("role") == owner

    def attempt_matches(node: dict[str, Any]) -> bool:
        return failed_attempt is None or _optional_int(node.get("attempt")) == failed_attempt

    def state_matches(node: dict[str, Any]) -> bool:
        return failed_state is None or _optional_str(node.get("state")) == failed_state

    def path_matches(node: dict[str, Any]) -> bool:
        return last_message_path is None or _optional_str(node.get("last_message_path")) == last_message_path

    ranked_checks = (
        lambda node: node.get("status") == "failed" and attempt_matches(node) and state_matches(node) and path_matches(node),
        lambda node: node.get("status") == "failed" and attempt_matches(node) and state_matches(node),
        lambda node: node.get("status") == "failed" and attempt_matches(node),
        lambda node: node.get("status") != "failed" and attempt_matches(node) and state_matches(node) and path_matches(node),
        lambda node: node.get("status") != "failed" and attempt_matches(node) and state_matches(node),
        lambda node: node.get("status") != "failed" and attempt_matches(node),
    )
    for check in ranked_checks:
        for node in reversed(nodes):
            if role_matches(node) and check(node):
                return node
    return None


def _safe_display_path(run_id: str, value: object, store: CodexTeamStore) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    if not store.is_inside_run_home(run_id, text):
        return None
    return text
