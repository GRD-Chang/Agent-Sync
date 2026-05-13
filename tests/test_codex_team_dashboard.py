from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from task_bridge.codex_team.dispatcher import CodexTeamDispatcher
from task_bridge.codex_team.runner import RunnerResult
from task_bridge.codex_team.store import CodexTeamStore
from task_bridge.dashboard.codex_team_queries import CodexTeamDashboardQueryService
from task_bridge.dashboard import create_dashboard_app


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TASK_BRIDGE_DASHBOARD_NOW", "2026-03-20T12:00:00Z")
    return tmp_path


def _envelope(summary: str, *, action: str, target: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "summary": summary,
        "status": "completed",
        "action": action,
        "target": target,
        "reason": reason,
        "artifacts": [],
    }


class DashboardCodexRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(
        self,
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        run_home: Path,
        schema_path: Path | None = None,
        output_last_message_path: Path | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> RunnerResult:
        self.calls.append(role)
        if role == "planner":
            (run_home / "plan.md").write_text("# Plan\n\n- build dashboard\n", encoding="utf-8")
            envelope = _envelope("planned", action="continue", target="evaluator", reason="plan ready for evaluation")
        elif role == "evaluator" and self.calls.count("evaluator") == 1:
            (run_home / "plan_evaluation.md").write_text("# Plan evaluation\n\npass\n", encoding="utf-8")
            envelope = _envelope("plan reviewed", action="continue", target="generator", reason="implementation may start")
        elif role == "generator":
            impl = run_home / "attempts" / "001" / "implementation.md"
            impl.parent.mkdir(parents=True, exist_ok=True)
            impl.write_text("# Implementation\n\n- read model\n- templates\n", encoding="utf-8")
            envelope = _envelope("implemented", action="ready_for_review", target="evaluator", reason="dashboard ready")
        else:
            evaluation = run_home / "attempts" / "001" / "evaluation.md"
            evaluation.write_text("# Evaluation\n\npass\n", encoding="utf-8")
            envelope = _envelope("accepted", action="pass", target="system", reason="final condition met")

        if output_last_message_path:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
            output_last_message_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            prefix = output_last_message_path.name.removesuffix(".last-message.json")
            (output_last_message_path.parent / f"{prefix}.stdout.log").write_text(f"{role} stdout\n", encoding="utf-8")
            (output_last_message_path.parent / f"{prefix}.stderr.log").write_text("", encoding="utf-8")
        return RunnerResult(
            role=role,
            returncode=0,
            duration_seconds=1.25,
            stdout_tail=f"{role} stdout\n",
            envelope=envelope,
            last_message_path=output_last_message_path,
        )


def seed_codex_team_run(home: Path) -> str:
    store = CodexTeamStore(home)
    repo = home / "repo"
    repo.mkdir()
    dispatcher = CodexTeamDispatcher(store=store, runner=DashboardCodexRunner())
    outcome = dispatcher.start_run(repo_root=repo, input_text="build a dashboard")
    dispatcher.run_until_idle(outcome.run_id)
    return outcome.run_id


def test_codex_team_read_model_builds_run_list_and_detail(home: Path) -> None:
    run_id = seed_codex_team_run(home)

    service = CodexTeamDashboardQueryService(home, now_provider=lambda: "2026-03-20T12:00:00Z")
    runs = service.runs()
    detail = service.run_detail(run_id)

    assert runs.run_count == 1
    assert runs.completed_count == 1
    assert runs.runs[0].run_id == run_id
    assert runs.runs[0].last_action == "pass"
    assert detail is not None
    assert detail.state == "completed"
    assert [node.role for node in detail.flow_nodes] == ["planner", "evaluator", "generator", "evaluator"]
    assert all(node.duration_label == "1.2s" for node in detail.flow_nodes)
    assert detail.flow_nodes[2].action == "ready_for_review"
    assert detail.flow_nodes[2].artifact_href is not None
    assert {artifact.key for artifact in detail.artifacts} >= {
        "input",
        "plan",
        "plan_evaluation",
        "implementation_001",
        "evaluation_001",
        "next_action",
        "metadata",
    }
    assert any(log.label.endswith(".stdout.log") for log in detail.logs)


def test_codex_team_dashboard_routes_render_full_chain_read_only(home: Path) -> None:
    run_id = seed_codex_team_run(home)
    store = CodexTeamStore(home)
    before_metadata = store.load_metadata(run_id)

    with TestClient(create_dashboard_app(home)) as client:
        list_response = client.get("/codex-team")
        detail_response = client.get(f"/codex-team/{run_id}")

    after_metadata = store.load_metadata(run_id)
    assert after_metadata == before_metadata
    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    list_body = list_response.text
    detail_body = detail_response.text
    assert 'data-testid="dashboard-nav-codex-team"' in list_body
    assert 'data-testid="dashboard-codex-team-run-list"' in list_body
    assert run_id in list_body
    assert 'data-testid="dashboard-codex-team-flow"' in detail_body
    assert 'data-testid="dashboard-codex-team-flow-node-planner-1"' in detail_body
    assert 'data-testid="dashboard-codex-team-flow-node-generator-3"' in detail_body
    assert 'data-testid="dashboard-codex-team-artifact-implementation_001"' in detail_body
    assert "ready_for_review" in detail_body
    assert "resume" not in detail_body.lower()
    assert "cancel" not in detail_body.lower()


def test_codex_team_artifact_preview_degrades_for_bad_json_and_unsafe_path(home: Path) -> None:
    store = CodexTeamStore(home)
    repo = home / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-bad")
    run_home = store.run_home("run-bad")
    (run_home / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (run_home / "next_action.json").write_text("{bad json", encoding="utf-8")
    outside = home / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    unsafe_link = run_home / "attempts" / "001" / "implementation.md"
    unsafe_link.parent.mkdir(parents=True, exist_ok=True)
    unsafe_link.symlink_to(outside)
    store.update_metadata(metadata["run_id"], state="generating", current_owner="generator")

    detail = CodexTeamDashboardQueryService(home, now_provider=lambda: "2026-03-20T12:00:00Z").run_detail("run-bad")

    assert detail is not None
    by_key = {artifact.key: artifact for artifact in detail.artifacts}
    assert by_key["next_action"].status == "error"
    assert by_key["implementation_001"].status == "unsafe"
