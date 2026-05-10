from __future__ import annotations

import json
from pathlib import Path

from task_bridge.codex_team.store import CodexTeamStore


def test_create_run_uses_task_bridge_home_layout(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    metadata = store.create_run(repo_root=repo, input_text="Build the thing", run_id="run-1")

    run_home = tmp_path / "codex-team" / "runs" / "run-1"
    assert metadata["run_home"] == str(run_home.resolve())
    assert (run_home / "input.md").read_text() == "Build the thing"
    assert (run_home / "metadata.json").exists()
    assert (run_home / "events.jsonl").exists()
    assert (run_home / "attempts").is_dir()
    assert (run_home / "artifacts" / "logs").is_dir()
    assert (run_home / "schemas").is_dir()


def test_event_log_is_append_only(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    store.create_run(repo_root=repo, input_text="x", run_id="run-1")

    store.append_event("run-1", {"type": "first"})
    store.append_event("run-1", {"type": "second"})

    events = store.read_events("run-1")
    assert [event["type"] for event in events] == ["run_created", "first", "second"]


def test_attempt_dirs_are_three_digit(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    store.create_run(repo_root=repo, input_text="x", run_id="run-1")

    assert store.create_attempt_dir("run-1", 1).name == "001"
    assert store.create_attempt_dir("run-1", 12).name == "012"


def test_path_containment_rejects_parent_and_symlink_escape(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    run_home = store.run_home("run-1")

    external = tmp_path / "external.txt"
    external.write_text("outside")
    symlink = run_home / "artifacts" / "logs" / "outside-link"
    symlink.symlink_to(external)

    assert store.is_inside_run_home("run-1", run_home / "input.md")
    assert not store.is_inside_run_home("run-1", run_home / ".." / "escape.md")
    assert not store.is_inside_run_home("run-1", symlink)


def test_pending_question_and_answers_are_durable(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    store.create_run(repo_root=repo, input_text="x", run_id="run-1")

    question = store.write_pending_question("run-1", "Which scope?")
    answer = store.append_answer("run-1", "CLI only")

    assert question["schema_version"] == 1
    assert json.loads(store.pending_question_path("run-1").read_text())["question"] == "Which scope?"
    assert json.loads(store.answers_path("run-1").read_text().splitlines()[0])["answer"] == answer["answer"]
