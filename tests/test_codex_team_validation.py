from __future__ import annotations

from pathlib import Path

from task_bridge.codex_team.validation import (
    filter_supplemental_artifacts,
    is_repairable_invalid_envelope,
    validate_fixed_artifact,
    validate_next_action_envelope,
)


def _valid_envelope() -> dict:
    return {
        "schema_version": 1,
        "summary": "ok",
        "status": "completed",
        "action": "continue",
        "target": "generator",
        "reason": "continue",
        "artifacts": [],
    }


def test_missing_schema_version_is_repairable(tmp_path: Path) -> None:
    envelope = _valid_envelope()
    envelope.pop("schema_version")

    issues = validate_next_action_envelope(envelope, role="planner", run_home=tmp_path, repo_root=tmp_path)

    assert [issue.code for issue in issues] == ["MissingSchemaVersion"]
    assert is_repairable_invalid_envelope(issues)


def test_generator_direct_stop_is_rejected_as_repairable_protocol_error(tmp_path: Path) -> None:
    envelope = _valid_envelope()
    envelope["action"] = "stop"
    envelope["target"] = "system"

    issues = validate_next_action_envelope(envelope, role="generator", run_home=tmp_path, repo_root=tmp_path)

    assert issues[0].code == "InvalidNextAction"
    assert is_repairable_invalid_envelope(issues)


def test_legacy_completion_scope_is_ignored_by_protocol_validator(tmp_path: Path) -> None:
    envelope = _valid_envelope()
    envelope["completion_scope"] = "checkpoint"

    issues = validate_next_action_envelope(envelope, role="planner", run_home=tmp_path, repo_root=tmp_path)

    assert issues == []


def test_fixed_artifact_requires_existing_non_empty_file_inside_run_home(tmp_path: Path) -> None:
    artifact = tmp_path / "attempts" / "001" / "implementation.md"
    artifact.parent.mkdir(parents=True)

    issues = validate_fixed_artifact(artifact, run_home=tmp_path, field_path="generator.fixed_artifact")
    assert issues[0].code == "InvalidFixedArtifact"
    assert issues[0].repairable

    artifact.write_text("implemented")
    assert validate_fixed_artifact(artifact, run_home=tmp_path, field_path="generator.fixed_artifact") == []


def test_supplemental_artifact_filter_retains_allowed_roots_and_drops_others(tmp_path: Path) -> None:
    run_home = tmp_path / "run"
    repo = tmp_path / "repo"
    run_home.mkdir()
    repo.mkdir()
    kept_run = run_home / "notes.md"
    kept_repo = repo / "docs.md"
    kept_run.write_text("notes")
    kept_repo.write_text("docs")

    result = filter_supplemental_artifacts(
        [str(kept_run), str(kept_repo), "relative.md", str(tmp_path / "other.md")],
        run_home=run_home,
        repo_root=repo,
    )

    assert result.retained == [str(kept_run), str(kept_repo)]
    assert [item["reason"] for item in result.dropped] == ["not_absolute", "outside_allowed_roots"]
