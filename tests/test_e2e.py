from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(home: Path, *args: str) -> dict | list | str:
    env = os.environ.copy()
    env["TASK_BRIDGE_HOME"] = str(home)
    env["PYTHONPATH"] = "src"
    proc = subprocess.run(
        [sys.executable, "-m", "task_bridge", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = proc.stdout.strip()
    return json.loads(stdout) if stdout.startswith("{") or stdout.startswith("[") else stdout


def test_cli_end_to_end_job_task_dispatch_notify(tmp_path: Path) -> None:
    capture_file = tmp_path / "messages.jsonl"
    os.environ["TASK_BRIDGE_CAPTURE_FILE"] = str(capture_file)
    try:
        job = run_cli(tmp_path, "create-job", "--title", "E2E 开发任务")
        assert isinstance(job, dict)

        task_1 = run_cli(tmp_path, "create-task", "--requirement", "未分配任务")
        task_2 = run_cli(tmp_path, "create-task", "--requirement", "已分配任务", "--assign", "code-agent")
        assert isinstance(task_1, dict) and isinstance(task_2, dict)

        dispatched = run_cli(tmp_path, "dispatch-once", "--json")
        assert dispatched["dispatched"] == [task_2["id"]]

        run_cli(tmp_path, "start", task_2["id"], "--job", job["id"], "--result", "正在开发")
        notified = run_cli(tmp_path, "notify", task_2["id"])
        assert notified["notified"] is False

        worker_status = run_cli(tmp_path, "worker-status", "--json")
        code_agent = next(item for item in worker_status["workers"] if item["agent"] == "code-agent")
        assert code_agent["status"] == "busy"

        queue = run_cli(tmp_path, "queue", "code-agent", "--json")
        assert queue["running_task_id"] == task_2["id"]

        run_cli(tmp_path, "complete", task_2["id"], "--job", job["id"], "--result", "开发完成")
        notified_final = run_cli(tmp_path, "notify", task_2["id"])
        assert notified_final["notified"] is True

        messages = [json.loads(line) for line in capture_file.read_text().splitlines() if line.strip()]
        assert len(messages) >= 3
        reset_index = next(
            index for index, msg in enumerate(messages) if msg["agent"] == "code-agent" and msg["message"] == "/reset"
        )
        dispatch_index = next(
            index
            for index, msg in enumerate(messages)
            if msg["agent"] == "code-agent" and task_2["id"] in msg["message"] and msg["message"] != "/reset"
        )
        notify_index = next(
            index
            for index, msg in enumerate(messages)
            if msg["agent"] == "team-leader" and "开发完成" in msg["message"]
        )
        assert reset_index < dispatch_index < notify_index
        assert messages[notify_index]["agent"] == "team-leader"
        assert "请基于以上状态立即做编排动作" in messages[notify_index]["message"]
    finally:
        os.environ.pop("TASK_BRIDGE_CAPTURE_FILE", None)


def test_cli_end_to_end_update_and_delete_task(tmp_path: Path) -> None:
    job = run_cli(tmp_path, "create-job", "--title", "E2E 编辑删除任务")
    assert isinstance(job, dict)

    task = run_cli(tmp_path, "create-task", "--requirement", "初始 requirement", "--assign", "code-agent")
    assert isinstance(task, dict)

    updated = run_cli(tmp_path, "update-task", task["id"], "--requirement", "已更新 requirement")
    assert isinstance(updated, dict)
    assert updated["requirement"] == "已更新 requirement"
    assert updated["assigned_agent"] == "code-agent"

    reassigned = run_cli(tmp_path, "update-task", task["id"], "--assign", "quality-agent")
    assert isinstance(reassigned, dict)
    assert reassigned["assigned_agent"] == "quality-agent"

    shown = run_cli(tmp_path, "show-task", task["id"], "--json")
    assert isinstance(shown, dict)
    assert shown["requirement"] == "已更新 requirement"
    assert shown["assigned_agent"] == "quality-agent"

    deleted = run_cli(tmp_path, "delete-task", task["id"])
    assert deleted == {"task_id": task["id"], "deleted": True}

    tasks = run_cli(tmp_path, "list-tasks", "--json")
    assert tasks == []
