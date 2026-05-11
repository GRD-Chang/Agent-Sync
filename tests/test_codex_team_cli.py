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
    assert "resume" in help_text


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


def test_codex_team_resume_failed_run(
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = CodexTeamStore(home=home)
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    run_home = store.run_home("run-1")
    evaluation = run_home / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("checkpoint ok")
    stdout_log = run_home / "artifacts" / "logs" / "evaluator-001.stdout.log"
    stdout_log.write_text('{"type":"thread.started","thread_id":"thread-1"}\n')
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="evaluator",
        current_attempt=1,
        last_error={"code": "RunnerAuthFailed", "message": "auth failed", "details": {"stdout_log": str(stdout_log)}},
    )

    class ResumeRunner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, *, role: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(role)
            if kwargs.get("resume"):
                assert role == "evaluator"
                assert kwargs["session_id"] == "thread-1"
                return RunnerResult(
                    role=role,
                    returncode=0,
                    duration_seconds=0.0,
                    envelope={
                        "schema_version": 1,
                        "summary": "continue",
                        "status": "completed",
                        "action": "continue",
                        "target": "generator",
                        "completion_scope": "checkpoint",
                        "reason": "ok",
                        "artifacts": [],
                    },
                )
            if role == "generator":
                impl = kwargs["run_home"] / "attempts" / "002" / "implementation.md"
                impl.parent.mkdir(parents=True, exist_ok=True)
                impl.write_text("final impl")
                return RunnerResult(
                    role=role,
                    returncode=0,
                    duration_seconds=0.0,
                    envelope={
                        "schema_version": 1,
                        "summary": "candidate",
                        "status": "completed",
                        "action": "candidate_ready",
                        "target": "evaluator",
                        "completion_scope": "checkpoint",
                        "reason": "ok",
                        "artifacts": [],
                    },
                )
            ev = kwargs["run_home"] / "attempts" / "002" / "evaluation.md"
            ev.write_text("final pass")
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0.0,
                envelope={
                    "schema_version": 1,
                    "summary": "done",
                    "status": "completed",
                    "action": "pass",
                    "target": "system",
                    "completion_scope": "final",
                    "reason": "ok",
                    "artifacts": [],
                },
            )

    monkeypatch.setattr("task_bridge.codex_team.cli._runner_from_name", lambda name: ResumeRunner())

    assert main(["codex-team", "resume", "run-1", "--json"]) == 0
    payload = parse_output(capsys)

    assert payload["outcome"]["state"] == "completed"
    assert payload["metadata"]["status"] == "completed"
    assert payload["metadata"]["last_error"] is None


def test_codex_team_resume_max_steps_zero_does_not_run_agent(
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = CodexTeamStore(home=home)
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    original_error = {
        "code": "RunnerLockBusy",
        "message": "busy",
        "details": {"thread_id": "thread-1"},
    }
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="evaluator",
        current_attempt=1,
        last_error=original_error,
    )
    existing_events = store.read_events("run-1")

    def fail_if_runner_created(name: str):  # type: ignore[no-untyped-def]
        raise AssertionError("resume --max-steps 0 must not create or run a Codex runner")

    monkeypatch.setattr("task_bridge.codex_team.cli._runner_from_name", fail_if_runner_created)

    assert main(["codex-team", "resume", "run-1", "--runner", "real", "--max-steps", "0", "--json"]) == 5
    payload = parse_output(capsys)
    stored = store.load_metadata("run-1")

    assert payload["outcome"]["error"]["code"] == "MaxStepsExceeded"
    assert payload["metadata"]["last_error"] == original_error
    assert stored["last_error"] == original_error
    assert store.read_events("run-1") == existing_events


def test_codex_team_resume_max_steps_one_runs_one_agent(
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = CodexTeamStore(home=home)
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    run_home = store.run_home("run-1")
    evaluation = run_home / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("checkpoint ok")
    stdout_log = run_home / "artifacts" / "logs" / "evaluator-001.stdout.log"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stdout_log.write_text('{"type":"thread.started","thread_id":"thread-1"}\n')
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="evaluator",
        current_attempt=1,
        last_error={"code": "RunnerAuthFailed", "message": "auth failed", "details": {"stdout_log": str(stdout_log)}},
    )

    class OneStepRunner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, *, role: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(role)
            assert kwargs.get("resume") is True
            assert kwargs["session_id"] == "thread-1"
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0.0,
                envelope={
                    "schema_version": 1,
                    "summary": "continue",
                    "status": "completed",
                    "action": "continue",
                    "target": "generator",
                    "completion_scope": "checkpoint",
                    "reason": "ok",
                    "artifacts": [],
                },
            )

    runner = OneStepRunner()
    monkeypatch.setattr("task_bridge.codex_team.cli._runner_from_name", lambda name: runner)

    assert main(["codex-team", "resume", "run-1", "--max-steps", "1", "--json"]) == 5
    payload = parse_output(capsys)
    stored = store.load_metadata("run-1")

    assert runner.calls == ["evaluator"]
    assert payload["outcome"]["error"]["code"] == "MaxStepsExceeded"
    assert stored["last_error"]["code"] == "MaxStepsExceeded"


def test_existing_top_level_help_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["-h"])

    assert exc.value.code == 0
    assert "codex-team" in capsys.readouterr().out
