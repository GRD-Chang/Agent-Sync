from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import ACTIONS, AGENT_STATUSES, SCHEMA_VERSION, TARGETS


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    repairable: bool = False


@dataclass(frozen=True)
class ArtifactFilterResult:
    retained: list[str]
    dropped: list[dict[str, str]]


class CodexTeamValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.code}: {issue.message}" for issue in issues))


def validate_next_action_envelope(
    envelope: Any,
    *,
    role: str | None = None,
    run_home: Path | None = None,
    repo_root: Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(envelope, dict):
        return [_issue("InvalidNextAction", "envelope must be an object", repairable=True)]

    if envelope.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue("MissingSchemaVersion", "schema_version must be 1", "schema_version", True))
    if envelope.get("status") not in AGENT_STATUSES:
        issues.append(_issue("InvalidStatus", "status is not allowed", "status", True))
    if not _non_empty_str(envelope.get("summary")):
        issues.append(_issue("InvalidSummary", "summary must be a non-empty string", "summary", True))

    action = envelope.get("action")
    target = envelope.get("target")
    if action not in ACTIONS:
        issues.append(_issue("InvalidNextAction", "action is not allowed", "action", True))
    if target not in TARGETS:
        issues.append(_issue("InvalidNextAction", "target is not allowed", "target", True))
    if not _non_empty_str(envelope.get("reason")):
        issues.append(_issue("InvalidNextAction", "reason must be non-empty", "reason", True))

    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        issues.append(_issue("InvalidArtifacts", "artifacts must be a list of strings", "artifacts", True))

    if action in ACTIONS and target in TARGETS:
        issues.extend(validate_role_action_target(role=role, action=str(action), target=str(target)))

    return issues


def validate_role_action_target(*, role: str | None, action: str, target: str) -> list[ValidationIssue]:
    if role == "planner":
        allowed = {
            ("continue", "generator"),
            ("continue", "evaluator"),
            ("ask_user", "user"),
            ("stop", "system"),
        }
    elif role == "generator":
        allowed = {
            ("ready_for_review", "evaluator"),
            ("needs_design", "planner"),
        }
    elif role == "evaluator":
        allowed = {
            ("continue", "generator"),
            ("pass", "system"),
            ("needs_fix", "generator"),
            ("needs_design", "planner"),
            ("stop", "system"),
        }
    else:
        allowed = {(action, target)}

    if (action, target) not in allowed:
        return [
            _issue(
                "InvalidNextAction",
                f"role {role!r} cannot route {action!r}->{target!r}",
                "action",
                repairable=True,
            )
        ]
    return []


def validate_fixed_artifact(path: Path, *, run_home: Path, field_path: str) -> list[ValidationIssue]:
    issues = _validate_inside(path, run_home, field_path)
    if issues:
        return issues
    try:
        if not path.exists():
            return [_issue("InvalidFixedArtifact", f"required artifact does not exist: {path}", field_path, True)]
        if not path.is_file():
            return [_issue("InvalidFixedArtifact", f"required artifact is not a file: {path}", field_path, True)]
        if not path.read_text(encoding="utf-8").strip():
            return [_issue("InvalidFixedArtifact", f"required artifact is empty: {path}", field_path, True)]
    except OSError as exc:
        return [_issue("InvalidFixedArtifact", f"cannot read required artifact: {exc}", field_path, True)]
    return []


def filter_supplemental_artifacts(
    artifacts: list[str],
    *,
    run_home: Path,
    repo_root: Path,
) -> ArtifactFilterResult:
    retained: list[str] = []
    dropped: list[dict[str, str]] = []
    roots = (run_home.resolve(), repo_root.resolve())
    for value in artifacts:
        path = Path(value).expanduser()
        if not path.is_absolute():
            dropped.append({"path": value, "reason": "not_absolute"})
            continue
        try:
            resolved = path.resolve()
        except OSError as exc:
            dropped.append({"path": value, "reason": f"resolve_failed:{exc}"})
            continue
        if not any(_is_relative_to(resolved, root) for root in roots):
            dropped.append({"path": value, "reason": "outside_allowed_roots"})
            continue
        if not resolved.exists():
            dropped.append({"path": value, "reason": "missing"})
            continue
        retained.append(str(resolved))
    return ArtifactFilterResult(retained=retained, dropped=dropped)


def is_repairable_invalid_envelope(issues: list[ValidationIssue]) -> bool:
    return bool(issues) and all(issue.repairable for issue in issues)


def raise_if_issues(issues: list[ValidationIssue]) -> None:
    if issues:
        raise CodexTeamValidationError(issues)


def issues_to_payload(issues: list[ValidationIssue]) -> list[dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "path": issue.path,
            "repairable": issue.repairable,
        }
        for issue in issues
    ]


def _validate_inside(path: Path, root: Path, field_path: str) -> list[ValidationIssue]:
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return [_issue("InvalidFixedArtifact", "required artifact path must be inside expected root", field_path, True)]
    return []


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, message: str, path: str = "", repairable: bool = False) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path, repairable=repairable)
