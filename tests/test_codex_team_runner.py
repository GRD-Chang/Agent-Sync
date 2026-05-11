from __future__ import annotations

from pathlib import Path

import fcntl
import pytest

from task_bridge.codex_team.runner import (
    CaptureCodexRunner,
    FakeCodexRunner,
    RealCodexRunner,
    RunnerResult,
    _looks_like_auth_failure,
)
from task_bridge.codex_team.schemas import schema_for_role


def test_fake_runner_returns_queued_envelope(tmp_path: Path) -> None:
    envelope = {
        "schema_version": 1,
        "summary": "ok",
        "status": "completed",
        "action": "stop",
        "target": "system",
        "reason": "done",
        "artifacts": [],
    }
    runner = FakeCodexRunner([envelope])

    result = runner.run(role="planner", prompt="p", repo_root=tmp_path, run_home=tmp_path)

    assert result.ok
    assert result.envelope == envelope
    assert runner.calls[0]["role"] == "planner"


def test_fake_runner_can_return_runner_error(tmp_path: Path) -> None:
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="planner",
                returncode=124,
                duration_seconds=1.0,
                error={"code": "RunnerTimeout", "message": "timed out"},
            )
        ]
    )

    result = runner.run(role="planner", prompt="p", repo_root=tmp_path, run_home=tmp_path)

    assert result.error["code"] == "RunnerTimeout"


def test_capture_runner_writes_prompt_log(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run_home = tmp_path / "run"
    repo.mkdir()
    run_home.mkdir()

    result = CaptureCodexRunner().run(role="planner", prompt="hello", repo_root=repo, run_home=run_home)

    assert result.ok
    assert (run_home / "artifacts" / "logs" / "planner-001.prompt.txt").read_text() == "hello"


def test_real_runner_command_builder_uses_stdin_schema_and_last_message(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    schema = tmp_path / "schema.json"
    last = tmp_path / "last.json"

    cmd = RealCodexRunner().build_command(repo_root=repo, schema_path=schema, output_last_message_path=last)

    assert cmd == [
        "codex",
        "exec",
        "--cd",
        str(repo),
        "--dangerously-bypass-approvals-and-sandbox",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(last),
        "--json",
        "-",
    ]


def test_real_runner_resume_command_does_not_use_output_schema_or_cd(tmp_path: Path) -> None:
    last = tmp_path / "last.json"

    cmd = RealCodexRunner().build_resume_command(session_id="session-1", output_last_message_path=last)

    assert "--output-schema" not in cmd
    assert "--cd" not in cmd
    assert "--disable" not in cmd
    assert cmd[:4] == ["codex", "exec", "resume", "session-1"]


def test_real_runner_can_disable_features_when_explicitly_requested(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    schema = tmp_path / "schema.json"
    last = tmp_path / "last.json"

    cmd = RealCodexRunner(disabled_features=("plugins",)).build_command(
        repo_root=repo,
        schema_path=schema,
        output_last_message_path=last,
    )

    assert "--disable" in cmd
    assert "plugins" in cmd


def test_real_runner_holds_global_and_run_locks_while_process_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    run_home = tmp_path / "run"
    schema = tmp_path / "schema.json"
    last = tmp_path / "last.json"
    repo.mkdir()
    run_home.mkdir()
    schema.write_text("{}")
    monkeypatch.setattr("task_bridge.codex_team.runner.shutil.which", lambda name: "/usr/bin/codex")
    observed: dict[str, bool] = {}

    class FakeProcess:
        pid = 123
        returncode = 0

        def communicate(self, input: str | None = None, timeout: int | None = None):  # noqa: A002
            observed["global_lock_exists"] = (run_home.parent / ".codex-team-runner.lock").exists()
            observed["run_lock_exists"] = (run_home / ".runner.lock").exists()
            last.write_text(
                '{"schema_version":1,"summary":"ok","status":"completed","action":"stop","target":"system","reason":"done","artifacts":[]}'
            )
            return "", ""

    monkeypatch.setattr("task_bridge.codex_team.runner.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    result = RealCodexRunner().run(
        role="planner",
        prompt="p",
        repo_root=repo,
        run_home=run_home,
        schema_path=schema,
        output_last_message_path=last,
    )

    assert result.ok
    assert observed == {"global_lock_exists": True, "run_lock_exists": True}


def test_real_runner_returns_lock_busy_without_blocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    run_home = tmp_path / "run"
    schema = tmp_path / "schema.json"
    last = tmp_path / "last.json"
    repo.mkdir()
    run_home.mkdir()
    schema.write_text("{}")
    lock_path = run_home.parent / ".codex-team-runner.lock"
    lock_path.touch()
    monkeypatch.setattr("task_bridge.codex_team.runner.shutil.which", lambda name: "/usr/bin/codex")

    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        result = RealCodexRunner().run(
            role="planner",
            prompt="p",
            repo_root=repo,
            run_home=run_home,
            schema_path=schema,
            output_last_message_path=last,
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert result.returncode == 75
    assert result.error["code"] == "RunnerLockBusy"


def test_real_runner_persists_stdout_and_stderr_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    run_home = tmp_path / "run"
    schema = tmp_path / "schema.json"
    last = tmp_path / "last.json"
    repo.mkdir()
    run_home.mkdir()
    schema.write_text("{}")
    monkeypatch.setattr("task_bridge.codex_team.runner.shutil.which", lambda name: "/usr/bin/codex")

    class FakeProcess:
        pid = 123
        returncode = 9

        def communicate(self, input: str | None = None, timeout: int | None = None):  # noqa: A002
            return "stdout details", "stderr details"

    monkeypatch.setattr("task_bridge.codex_team.runner.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    result = RealCodexRunner().run(
        role="planner",
        prompt="p",
        repo_root=repo,
        run_home=run_home,
        schema_path=schema,
        output_last_message_path=last,
    )

    assert result.error["code"] == "RunnerFailed"
    details = result.error["details"]
    assert Path(details["stdout_log"]).read_text() == "stdout details"
    assert Path(details["stderr_log"]).read_text() == "stderr details"
    assert details["stdout_tail"] == "stdout details"
    assert details["stderr_tail"] == "stderr details"


def test_real_runner_detects_auth_failure_markers() -> None:
    assert _looks_like_auth_failure("HTTP error: 401 Unauthorized")
    assert _looks_like_auth_failure("No access token was provided")


def test_output_schema_is_strict_for_codex_structured_output() -> None:
    schema = schema_for_role("planner")

    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(schema["properties"])
    assert schema["properties"]["artifacts"]["description"]


def test_output_schema_is_role_specific() -> None:
    assert "ready_for_review" not in schema_for_role("evaluator")["properties"]["action"]["enum"]
    assert "stop" not in schema_for_role("generator")["properties"]["action"]["enum"]
    assert "ready_for_review" in schema_for_role("generator")["properties"]["action"]["enum"]
