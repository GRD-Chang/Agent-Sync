from __future__ import annotations

import json
from pathlib import Path

import pytest

from task_bridge.cli import main
from task_bridge.runtime import BridgeRuntime
from task_bridge.store import TaskStore


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_job(home: Path, job_id: str) -> dict:
    return read_json(home / "jobs" / job_id / "job.json")


def read_task(home: Path, job_id: str, task_id: str) -> dict:
    return read_json(home / "jobs" / job_id / "tasks" / f"{task_id}.json")


def parse_last_json(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("argv", [["-h"], ["--help"]])
def test_top_level_help_lists_command_summaries(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "本地任务桥：管理 job/task，分发任务给 worker，并回收终态结果。" in help_text
    assert "create-job" in help_text and "创建新 job，并自动设为当前 job" in help_text
    assert "create-task" in help_text and "创建 task，可选分配给 worker" in help_text
    assert "dispatch-once" in help_text and "执行一轮派发扫描" in help_text
    assert "daemon" in help_text and "循环执行派发与通知" in help_text


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["create-task", "-h"], "创建一个新 task。若提供 --assign，则 bridge 后续可以把它派发给对应 worker。"),
        (["create-task", "-h"], "--requirement"),
        (["create-task", "-h"], "任务要求，建议写成自包含说明"),
        (["update-task", "-h"], "仅允许在 queued 状态下修改 requirement 或 assigned_agent。"),
        (["update-task", "-h"], "--requirement"),
        (["update-task", "-h"], "--assign"),
        (["delete-task", "-h"], "仅允许删除 queued 或 done task。"),
        (["complete", "--help"], "把任务状态更新为 done，并写入最终结果。"),
        (["complete", "--help"], "--result"),
        (["daemon", "-h"], "以轮询方式持续运行 bridge：每轮先 dispatch，再发送周期提醒、终态 notify，以及未收口 follow-up。"),
        (["daemon", "-h"], "--poll-seconds"),
        (["daemon", "-h"], "--worker-reminder-seconds"),
        (["daemon", "-h"], "--leader-reminder-seconds"),
    ],
)
def test_subcommand_help_describes_usage_and_arguments(
    argv: list[str],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 0
    assert expected in capsys.readouterr().out


def test_assign_task_command_is_removed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["assign-task", "-h"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_create_job_auto_generates_id_and_sets_current_job(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["create-job", "--title", "开发模块 A"]) == 0
    payload = parse_last_json(capsys)
    job_id = payload["id"]

    assert job_id.startswith("job-")
    assert (home / "jobs" / job_id / "job.json").exists()
    assert read_job(home, job_id)["title"] == "开发模块 A"

    assert main(["current-job", "--json"]) == 0
    current = parse_last_json(capsys)
    assert current["id"] == job_id


def test_create_task_defaults_to_current_job_and_task_id_is_generated(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "优化仓库"])
    job = parse_last_json(capsys)

    assert main(["create-task", "--requirement", "优化核心模块", "--assign", "code-agent"]) == 0
    task = parse_last_json(capsys)

    assert task["id"].startswith("task-")
    assert task["job_id"] == job["id"]
    assert task["assigned_agent"] == "code-agent"
    assert task["state"] == "queued"
    assert task["detail_path"] == str(TaskStore(home).detail_path(job["id"], task["id"]))
    assert read_task(home, job["id"], task["id"])["requirement"] == "优化核心模块"


def test_multiple_jobs_are_isolated_in_separate_directories(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "开发模块"])
    job_a = parse_last_json(capsys)
    main(["create-task", "--requirement", "实现接口 A", "--assign", "code-agent"])
    task_a = parse_last_json(capsys)

    main(["create-job", "--title", "代码优化"])
    job_b = parse_last_json(capsys)
    main(["create-task", "--requirement", "清理死代码", "--assign", "quality-agent"])
    task_b = parse_last_json(capsys)

    assert (home / "jobs" / job_a["id"] / "tasks" / f"{task_a['id']}.json").exists()
    assert (home / "jobs" / job_b["id"] / "tasks" / f"{task_b['id']}.json").exists()
    assert read_task(home, job_a["id"], task_a["id"])["job_id"] == job_a["id"]
    assert read_task(home, job_b["id"], task_b["id"])["job_id"] == job_b["id"]


def test_unassigned_tasks_are_not_dispatched(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "任务分配测试"])
    job = parse_last_json(capsys)
    main(["create-task", "--requirement", "先不分配"])
    unassigned = parse_last_json(capsys)
    main(["create-task", "--requirement", "立即开发", "--assign", "code-agent"])
    assigned = parse_last_json(capsys)

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(
        home=home,
        sender=lambda agent, message: calls.append((agent, message)),
        reset_sender=lambda agent, message: calls.append((agent, message)),
    )
    outcome = runtime.dispatch_once()

    assert outcome.dispatched == [assigned["id"]]
    assert len(calls) == 2
    assert calls[0] == ("code-agent", "/reset")
    assert calls[1][0] == "code-agent"
    assert f"job_id={job['id']}" in calls[1][1]
    assert f"task_id={assigned['id']}" in calls[1][1]

    task = read_task(home, job["id"], unassigned["id"])
    assert task["assigned_agent"] == ""
    assert task["_scheduler"]["awaiting_claim"] is False
    assert task["_scheduler"]["last_dispatch_at"] is None
    assert task["_scheduler"]["final_notified_at"] is None


def test_worker_status_and_queue_are_derived_across_all_jobs(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "job-a"])
    job_a = parse_last_json(capsys)
    main(["create-task", "--requirement", "req-a1", "--assign", "code-agent"])
    task_a1 = parse_last_json(capsys)
    main(["create-task", "--requirement", "req-a2", "--assign", "code-agent"])
    parse_last_json(capsys)

    main(["create-job", "--title", "job-b"])
    job_b = parse_last_json(capsys)
    main(["create-task", "--requirement", "req-b1", "--assign", "quality-agent"])
    task_b1 = parse_last_json(capsys)
    main(["start", task_b1["id"], "--job", job_b["id"], "--result", "running"])
    capsys.readouterr()

    assert main(["worker-status", "--json"]) == 0
    status_payload = parse_last_json(capsys)
    by_agent = {item["agent"]: item for item in status_payload["workers"]}

    assert by_agent["code-agent"]["status"] == "idle"
    assert by_agent["code-agent"]["queued"] == 2
    assert by_agent["quality-agent"]["status"] == "busy"
    assert by_agent["quality-agent"]["running_task_id"] == task_b1["id"]

    assert main(["queue", "code-agent", "--json"]) == 0
    queue_payload = parse_last_json(capsys)
    assert queue_payload["agent"] == "code-agent"
    assert queue_payload["running_task_id"] is None
    assert [item["id"] for item in queue_payload["queued_tasks"]] == [task_a1["id"], queue_payload["queued_tasks"][1]["id"]]
    assert all(item["job_id"] == job_a["id"] for item in queue_payload["queued_tasks"])


def test_notify_only_sends_once_after_terminal_state(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "通知测试"])
    job = parse_last_json(capsys)
    main(["create-task", "--requirement", "实现功能", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    main(["start", task["id"], "--job", job["id"], "--result", "step-1"])
    capsys.readouterr()

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    first = runtime.notify_updates()
    main(["update-result", task["id"], "--job", job["id"], "--result", "step-2"])
    capsys.readouterr()
    second = runtime.notify_updates()
    main(["complete", task["id"], "--job", job["id"], "--result", "step-3"])
    capsys.readouterr()
    third = runtime.notify_updates()
    fourth = runtime.notify_updates()

    assert first.notified == []
    assert second.notified == []
    assert third.notified == [task["id"]]
    assert fourth.notified == []
    assert len(calls) == 1
    assert calls[0][0] == "team-leader"
    assert f"job_id={job['id']}" in calls[0][1]
    assert f"task_id={task['id']}" in calls[0][1]
    assert "state=done" in calls[0][1]
    assert "detail_path=" not in calls[0][1]
    assert "step-3" in calls[0][1]
    assert "请基于以上状态立即做编排动作" in calls[0][1]


def test_notify_includes_detail_path_when_detail_file_exists(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "detail notify"])
    job = parse_last_json(capsys)
    main(["create-task", "--requirement", "实现功能", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    detail_path = Path(task["detail_path"])
    detail_path.write_text("worker detail", encoding="utf-8")
    main(["complete", task["id"], "--job", job["id"], "--result", "step-3"])
    capsys.readouterr()

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    outcome = runtime.notify_updates()

    assert outcome.notified == [task["id"]]
    assert len(calls) == 1
    assert f"detail_path={detail_path}" in calls[0][1]


def test_show_job_and_list_tasks_default_to_current_job(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "当前 job 测试"])
    job = parse_last_json(capsys)
    main(["create-task", "--requirement", "task-1"])
    task = parse_last_json(capsys)
    capsys.readouterr()

    assert main(["show-job", "--json"]) == 0
    shown_job = parse_last_json(capsys)
    assert shown_job["id"] == job["id"]

    assert main(["list-tasks", "--json"]) == 0
    tasks = parse_last_json(capsys)
    assert [item["id"] for item in tasks] == [task["id"]]


def test_list_jobs_use_job_update_show_task_and_filters(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "job-a"])
    job_a = parse_last_json(capsys)
    main(["create-task", "--requirement", "实现 A", "--assign", "code-agent"])
    task_a = parse_last_json(capsys)

    main(["create-job", "--title", "job-b"])
    job_b = parse_last_json(capsys)
    main(["create-task", "--requirement", "校验 B", "--assign", "quality-agent"])
    parse_last_json(capsys)

    assert main(["list-jobs", "--json"]) == 0
    jobs = parse_last_json(capsys)
    by_id = {job["id"]: job for job in jobs}
    assert by_id[job_a["id"]]["is_current"] is False
    assert by_id[job_b["id"]]["is_current"] is True

    assert main(["use-job", job_a["id"]]) == 0
    used_job = parse_last_json(capsys)
    assert used_job["id"] == job_a["id"]

    assert main(["show-task", task_a["id"], "--json"]) == 0
    shown_task = parse_last_json(capsys)
    assert shown_task["id"] == task_a["id"]
    assert shown_task["assigned_agent"] == "code-agent"

    assert main(["update-task", task_a["id"], "--assign", "quality-agent"]) == 0
    reassigned = parse_last_json(capsys)
    assert reassigned["assigned_agent"] == "quality-agent"

    assert main(["list-tasks", "--agent", "quality-agent", "--json"]) == 0
    quality_tasks = parse_last_json(capsys)
    assert [item["id"] for item in quality_tasks] == [task_a["id"]]

    assert main(["block", task_a["id"], "--result", "等待依赖"]) == 0
    blocked = parse_last_json(capsys)
    assert blocked["state"] == "blocked"

    assert main(["list-tasks", "--state", "blocked", "--json"]) == 0
    blocked_tasks = parse_last_json(capsys)
    assert [item["id"] for item in blocked_tasks] == [task_a["id"]]


def test_update_task_can_change_requirement_and_assigned_agent_when_queued(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "编辑与删除 task"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "旧 requirement", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    original_updated_at = task["updatedAt"]

    assert main(["update-task", task["id"], "--requirement", "新 requirement"]) == 0
    updated = parse_last_json(capsys)
    assert updated["id"] == task["id"]
    assert updated["requirement"] == "新 requirement"
    assert updated["assigned_agent"] == "code-agent"
    assert updated["state"] == "queued"
    assert updated["updatedAt"] >= original_updated_at
    assert read_task(home, job["id"], task["id"])["requirement"] == "新 requirement"

    assert main(["update-task", task["id"], "--assign", "quality-agent"]) == 0
    reassigned = parse_last_json(capsys)
    assert reassigned["assigned_agent"] == "quality-agent"
    assert reassigned["state"] == "queued"
    assert read_task(home, job["id"], task["id"])["assigned_agent"] == "quality-agent"

    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)
    code_agent_queue = runtime.queue_for_agent("code-agent")
    assert code_agent_queue["running_task_id"] is None
    assert code_agent_queue["queued_tasks"] == []

    quality_agent_queue = runtime.queue_for_agent("quality-agent")
    assert quality_agent_queue["running_task_id"] is None
    assert [item["id"] for item in quality_agent_queue["queued_tasks"]] == [task["id"]]


def test_update_task_rejects_assigned_agent_change_when_task_is_not_queued(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "限制修改 worker"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "处理中任务", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    main(["start", task["id"], "--job", job["id"], "--result", "running"])
    started = parse_last_json(capsys)

    assert main(["update-task", task["id"], "--assign", "quality-agent"]) == 2
    assert "assigned_agent can only be updated when task is queued" in capsys.readouterr().err

    current = read_task(home, job["id"], task["id"])
    assert current["assigned_agent"] == "code-agent"
    assert current["state"] == started["state"]


def test_update_task_rejects_requirement_change_when_task_is_not_queued(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "限制修改 requirement"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "旧 requirement", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    main(["start", task["id"], "--job", job["id"], "--result", "running"])
    parse_last_json(capsys)

    assert main(["update-task", task["id"], "--requirement", "新 requirement"]) == 2
    assert "requirement can only be updated when task is queued" in capsys.readouterr().err

    current = read_task(home, job["id"], task["id"])
    assert current["requirement"] == "旧 requirement"
    assert current["state"] == "running"


def test_delete_task_remove_queued_task_from_store_and_queue(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "删除 task"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "待删除 requirement", "--assign", "code-agent"])
    task = parse_last_json(capsys)

    assert main(["delete-task", task["id"]]) == 0
    deleted = parse_last_json(capsys)
    assert deleted == {"task_id": task["id"], "deleted": True}
    assert not (home / "jobs" / job["id"] / "tasks" / f"{task['id']}.json").exists()

    assert main(["list-tasks", "--json"]) == 0
    assert parse_last_json(capsys) == []

    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)
    queue = runtime.queue_for_agent("code-agent")
    assert queue["running_task_id"] is None
    assert queue["queued_tasks"] == []


def test_delete_task_rejects_non_terminal_task_and_allows_done_task(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "删除状态限制"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "处理中", "--assign", "code-agent"])
    task = parse_last_json(capsys)
    main(["start", task["id"], "--job", job["id"], "--result", "running"])
    parse_last_json(capsys)

    assert main(["delete-task", task["id"]]) == 2
    assert "task can only be deleted when state is queued or done" in capsys.readouterr().err
    assert (home / "jobs" / job["id"] / "tasks" / f"{task['id']}.json").exists()

    assert main(["complete", task["id"], "--job", job["id"], "--result", "done"]) == 0
    parse_last_json(capsys)

    assert main(["delete-task", task["id"]]) == 0
    deleted = parse_last_json(capsys)
    assert deleted == {"task_id": task["id"], "deleted": True}
    assert not (home / "jobs" / job["id"] / "tasks" / f"{task['id']}.json").exists()


def test_claim_complete_block_and_fail_commands_update_task_state(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["create-job", "--title", "状态流转"])
    job = parse_last_json(capsys)
    task_store = TaskStore(home)

    main(["create-task", "--requirement", "待认领", "--assign", "code-agent"])
    claim_task = parse_last_json(capsys)
    task_store.update_task(
        claim_task["id"],
        job_id=job["id"],
        result="已派发",
    )
    payload = task_store.load_task(claim_task["id"], job_id=job["id"])
    payload["_scheduler"]["awaiting_claim"] = True
    task_store.save_task(payload)

    assert main(["claim", claim_task["id"], "--result", "开始处理"]) == 0
    claimed = parse_last_json(capsys)
    assert claimed["state"] == "running"
    assert claimed["result"] == "开始处理"
    assert claimed["_scheduler"]["awaiting_claim"] is False

    main(["create-task", "--requirement", "可完成", "--assign", "code-agent"])
    done_task = parse_last_json(capsys)
    assert main(["complete", done_task["id"], "--result", "已完成"]) == 0
    completed = parse_last_json(capsys)
    assert completed["state"] == "done"
    assert completed["result"] == "已完成"

    main(["create-task", "--requirement", "被阻塞", "--assign", "quality-agent"])
    blocked_task = parse_last_json(capsys)
    assert main(["block", blocked_task["id"], "--result", "缺少输入"]) == 0
    blocked = parse_last_json(capsys)
    assert blocked["state"] == "blocked"

    main(["create-task", "--requirement", "执行失败", "--assign", "quality-agent"])
    failed_task = parse_last_json(capsys)
    assert main(["fail", failed_task["id"], "--result", "测试失败"]) == 0
    failed = parse_last_json(capsys)
    assert failed["state"] == "failed"


def test_dispatch_once_notify_force_and_daemon_single_round(
    home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_file = home / "messages.jsonl"
    monkeypatch.setenv("TASK_BRIDGE_CAPTURE_FILE", str(capture_file))

    main(["create-job", "--title", "调度与通知"])
    job = parse_last_json(capsys)

    main(["create-task", "--requirement", "正在运行", "--assign", "code-agent"])
    busy_task = parse_last_json(capsys)
    main(["start", busy_task["id"], "--job", job["id"], "--result", "处理中"])
    capsys.readouterr()

    main(["create-task", "--requirement", "待认领", "--assign", "quality-agent"])
    pending_task = parse_last_json(capsys)
    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)
    runtime.dispatch_once()

    main(["create-task", "--requirement", "未通知任务"])
    quiet_task = parse_last_json(capsys)

    assert main(["dispatch-once", "--json"]) == 0
    dispatch = parse_last_json(capsys)
    assert dispatch["dispatched"] == []
    assert dispatch["skipped_busy"] == {"code-agent": busy_task["id"]}
    assert dispatch["skipped_pending_claim"] == {"quality-agent": pending_task["id"]}

    assert main(["notify", quiet_task["id"]]) == 0
    quiet_notify = parse_last_json(capsys)
    assert quiet_notify == {"task_id": quiet_task["id"], "notified": False}

    assert main(["notify", quiet_task["id"], "--force"]) == 0
    forced_notify = parse_last_json(capsys)
    assert forced_notify == {"task_id": quiet_task["id"], "notified": True}

    main(["create-task", "--requirement", "daemon 派发", "--assign", "review-agent"])
    daemon_task = parse_last_json(capsys)
    main(["create-task", "--requirement", "daemon 完成通知", "--assign", "quality-agent"])
    terminal_task = parse_last_json(capsys)
    main(["complete", terminal_task["id"], "--job", job["id"], "--result", "已完成"])
    capsys.readouterr()
    assert main(["daemon", "--poll-seconds", "0", "--iterations", "1"]) == 0
    daemon_payload = parse_last_json(capsys)
    assert daemon_task["id"] in daemon_payload["dispatched"]
    assert terminal_task["id"] in daemon_payload["notified"]
    assert daemon_payload["worker_reminded"] == []
    assert daemon_payload["leader_pinged"] is False
    assert daemon_payload["leader_followed_up"] == []


def test_daemon_sends_due_worker_and_team_leader_reminders_with_custom_intervals(
    home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_file = home / "messages.jsonl"
    monkeypatch.setenv("TASK_BRIDGE_CAPTURE_FILE", str(capture_file))

    main(["create-job", "--title", "daemon reminders"])
    job = parse_last_json(capsys)
    main(["create-task", "--requirement", "持续推进", "--assign", "code-agent"])
    task = parse_last_json(capsys)

    assert main(["dispatch-once", "--json"]) == 0
    parse_last_json(capsys)
    assert main(["start", task["id"], "--job", job["id"], "--result", "running"]) == 0
    parse_last_json(capsys)
    capture_file.write_text("", encoding="utf-8")

    assert (
        main(
            [
                "daemon",
                "--poll-seconds",
                "0",
                "--iterations",
                "1",
                "--worker-reminder-seconds",
                "0",
                "--leader-reminder-seconds",
                "0",
            ]
        )
        == 0
    )
    daemon_payload = parse_last_json(capsys)
    messages = [json.loads(line) for line in capture_file.read_text().splitlines() if line.strip()]

    assert daemon_payload["dispatched"] == []
    assert daemon_payload["notified"] == []
    assert daemon_payload["worker_reminded"] == [task["id"]]
    assert daemon_payload["leader_pinged"] is True
    assert daemon_payload["leader_followed_up"] == []
    assert any(msg["agent"] == "code-agent" and msg["message"].startswith("/coding-agent [TASK_REMINDER]\n") for msg in messages)
    assert any(msg["agent"] == "team-leader" and "通过上面的飞书 chat_id 给我发送总结" in msg["message"] for msg in messages)


def test_cli_returns_expected_error_codes_for_missing_and_ambiguous_targets(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["current-job", "--json"]) == 3
    assert "no job found" in capsys.readouterr().err

    main(["create-job", "--title", "job-a"])
    job_a = parse_last_json(capsys)
    main(["create-job", "--title", "job-b"])
    job_b = parse_last_json(capsys)

    current_job_file = home / "current_job"
    current_job_file.unlink()

    assert main(["list-tasks", "--json"]) == 2
    assert "multiple jobs exist; use --job or use-job" in capsys.readouterr().err

    assert main(["use-job", "missing-job"]) == 3
    assert "job not found: missing-job" in capsys.readouterr().err

    task_store = TaskStore(home)
    duplicated = task_store.create_task(job_id=job_a["id"], requirement="same-id", assigned_agent="code-agent")
    duplicated_copy = dict(duplicated)
    duplicated_copy["job_id"] = job_b["id"]
    task_store.save_task(duplicated_copy)

    assert main(["show-task", duplicated["id"], "--json"]) == 2
    assert f"task id is ambiguous: {duplicated['id']}; use --job" in capsys.readouterr().err

    assert main(["delete-task", duplicated["id"]]) == 2
    assert f"task id is ambiguous: {duplicated['id']}; use --job" in capsys.readouterr().err
