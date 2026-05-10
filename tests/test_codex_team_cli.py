from __future__ import annotations

import json
from pathlib import Path

import pytest

from task_bridge.cli import main
from task_bridge.codex_team.runner import RunnerResult
from task_bridge.codex_team.store import CodexTeamStore


def parse_output(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(tmp_path))
    return tmp_path


def test_codex_team_help_is_discoverable(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["codex-team", "-h"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "start" in help_text
    assert "status" in help_text
    assert "answer" in help_text


def test_codex_team_start_and_status_json(home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["codex-team", "start", "--repo-root", str(repo), "--input", "build", "--no-run", "--json"]) == 0
    payload = parse_output(capsys)

    assert payload["state"] == "planning"
    assert payload["current_owner"] == "planner"
    run_id = payload["run_id"]
    assert (home / "codex-team" / "runs" / run_id / "input.md").read_text() == "build"

    assert main(["codex-team", "status", run_id, "--json"]) == 0
    status = parse_output(capsys)
    assert status["run_id"] == run_id
    assert status["state"] == "planning"


def test_codex_team_start_failed_run_returns_nonzero(home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["codex-team", "start", "--repo-root", str(repo), "--input", "build", "--runner", "capture", "--json"]) == 5
    payload = parse_output(capsys)

    assert payload["outcome"]["state"] == "failed"
    assert payload["metadata"]["status"] == "failed"
    assert payload["metadata"]["last_error"]["code"] == "InvalidFixedArtifact"


def test_codex_team_start_max_steps_zero_does_not_run_agent(
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    calls: list[str] = []

    class CountingRunner:
        def run(self, *, role: str, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(role)
            return RunnerResult(role=role, returncode=1, duration_seconds=0.0, error={"code": "ShouldNotRun"})

    monkeypatch.setattr("task_bridge.codex_team.cli._runner_from_name", lambda name: CountingRunner())

    assert (
        main(
            [
                "codex-team",
                "start",
                "--repo-root",
                str(repo),
                "--input",
                "build",
                "--runner",
                "real",
                "--max-steps",
                "0",
                "--json",
            ]
        )
        == 5
    )
    payload = parse_output(capsys)

    assert calls == []
    assert payload["metadata"]["last_error"]["code"] == "MaxStepsExceeded"


def test_codex_team_runner_lock_busy_returns_exit_code_4(
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    class LockBusyRunner:
        def run(self, *, role: str, **kwargs):  # type: ignore[no-untyped-def]
            return RunnerResult(
                role=role,
                returncode=75,
                duration_seconds=0.0,
                error={"code": "RunnerLockBusy", "message": "busy"},
            )

    monkeypatch.setattr("task_bridge.codex_team.cli._runner_from_name", lambda name: LockBusyRunner())

    assert (
        main(
            [
                "codex-team",
                "start",
                "--repo-root",
                str(repo),
                "--input",
                "build",
                "--runner",
                "real",
                "--max-steps",
                "1",
                "--json",
            ]
        )
        == 4
    )
    payload = parse_output(capsys)

    assert payload["metadata"]["last_error"]["code"] == "RunnerLockBusy"


def test_codex_team_answer_requires_paused_run(home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = CodexTeamStore(home=home)
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="paused", current_owner="user")
    store.write_pending_question("run-1", "Which scope?")

    assert main(["codex-team", "answer", "run-1", "--text", "CLI only", "--no-run", "--json"]) == 0
    payload = parse_output(capsys)

    assert payload["state"] == "planning"
    assert json.loads((home / "codex-team" / "runs" / "run-1" / "answers.jsonl").read_text())["answer"] == "CLI only"


def test_existing_top_level_help_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["-h"])

    assert exc.value.code == 0
    assert "codex-team" in capsys.readouterr().out
