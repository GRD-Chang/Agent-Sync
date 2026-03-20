from __future__ import annotations

import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from task_bridge.config import resolve_user_chat_id
from task_bridge.prompts import PROMPT_TEMPLATE_FILES, load_prompts, prompt_template_path
from task_bridge.runtime import (
    BridgeRuntime,
    default_openclaw_reset_sender,
    default_openclaw_sender,
)
from task_bridge.store import TaskStore, infer_worker_status, queue_for_agent, resolve_home


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(tmp_path))
    return tmp_path


def test_resolve_home_prefers_explicit_and_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    explicit = tmp_path / "explicit-home"
    assert resolve_home(explicit) == explicit

    env_home = tmp_path / "env-home"
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(env_home))
    assert resolve_home() == env_home.resolve()


def test_resolve_user_chat_id_prefers_env_then_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text('TASK_BRIDGE_USER_CHAT_ID="chat-from-dotenv"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TASK_BRIDGE_USER_CHAT_ID", raising=False)

    assert resolve_user_chat_id(cwd=tmp_path) == "chat-from-dotenv"

    monkeypatch.setenv("TASK_BRIDGE_USER_CHAT_ID", "chat-from-env")
    assert resolve_user_chat_id(cwd=tmp_path) == "chat-from-env"


def test_resolve_user_chat_id_does_not_fall_back_to_feishu_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TASK_BRIDGE_USER_CHAT_ID", raising=False)
    monkeypatch.setenv("TASK_BRIDGE_USER_FEISHU_ID", "feishu-user-123")

    assert resolve_user_chat_id(cwd=tmp_path) is None


def test_bridge_runtime_home_and_queue_helpers(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="helper-test")
    task = store.create_task(job_id=job["id"], requirement="req", assigned_agent="review-agent")

    runtime = BridgeRuntime(home=home, sender=lambda *_: None)
    assert runtime.home == home
    assert task["detail_path"] == str(store.detail_path(job["id"], task["id"]))
    assert store.task_artifacts_dir(job["id"], task["id"]).is_dir()

    queue = runtime.queue_for_agent("review-agent")
    assert queue["running_task_id"] is None
    assert [item["id"] for item in queue["queued_tasks"]] == [task["id"]]

    workers = infer_worker_status(store.list_tasks(all_jobs=True))
    review_agent = next(item for item in workers if item["agent"] == "review-agent")
    assert review_agent["queued"] == 1
    assert review_agent["status"] == "idle"


def test_notify_updates_only_for_terminal_tasks_and_only_once(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TaskStore(home)
    job = store.create_job(title="notify-skip")
    task = store.create_task(job_id=job["id"], requirement="req", assigned_agent="code-agent")
    (home / ".env").write_text("TASK_BRIDGE_USER_CHAT_ID=chat-id-123\n", encoding="utf-8")
    monkeypatch.delenv("TASK_BRIDGE_USER_CHAT_ID", raising=False)
    monkeypatch.chdir(home)

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    outcome = runtime.notify_updates()
    assert outcome.notified == []
    assert calls == []

    store.update_task(task["id"], job_id=job["id"], state="running", result="step-1")
    running = runtime.notify_updates()
    assert running.notified == []
    assert calls == []

    store.update_task(task["id"], job_id=job["id"], state="done", result="")
    terminal = runtime.notify_updates()
    repeated = runtime.notify_updates()
    persisted = store.load_task(task["id"], job_id=job["id"])
    assert terminal.notified == [task["id"]]
    assert repeated.notified == []
    assert len(calls) == 1
    assert calls[0][0] == "team-leader"
    assert "user_chat_id=chat-id-123" in calls[0][1]
    assert "detail_path=" not in calls[0][1]
    assert "(empty result)" in calls[0][1]
    assert "(empty result)\n请基于以上状态立即做编排动作" in calls[0][1]
    assert "请基于以上状态立即做编排动作" in calls[0][1]
    assert "最后一步，必须通过上面的飞书 chat_id 向用户发送消息" in calls[0][1]
    assert persisted["_scheduler"]["final_notified_at"] is not None
    assert persisted["_scheduler"]["leader_followup_due_at"] is not None
    assert persisted["_scheduler"]["leader_followup_sent_at"] is None


def test_default_openclaw_sender_spawns_openclaw_detached_with_no_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(args: list[str], **kwargs: object) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.delenv("TASK_BRIDGE_CAPTURE_FILE", raising=False)
    monkeypatch.setattr("task_bridge.runtime.subprocess.Popen", fake_popen)

    default_openclaw_sender("code-agent", "hello")

    assert captured["args"] == [
        "openclaw",
        "agent",
        "--agent",
        "code-agent",
        "-m",
        "hello",
        "--timeout",
        "0",
    ]
    assert captured["kwargs"] == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }


def test_default_openclaw_reset_sender_runs_blocking_until_reset_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.delenv("TASK_BRIDGE_CAPTURE_FILE", raising=False)
    monkeypatch.setattr("task_bridge.runtime.subprocess.run", fake_run)

    default_openclaw_reset_sender("code-agent", "/reset")

    assert captured["args"] == [
        "openclaw",
        "agent",
        "--agent",
        "code-agent",
        "-m",
        "/reset",
    ]
    assert captured["kwargs"] == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "check": True,
    }


def test_runtime_loads_repo_prompt_templates(home: Path) -> None:
    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)

    for name in PROMPT_TEMPLATE_FILES:
        assert prompt_template_path(name).is_file()

    assert runtime.prompts.dispatch == prompt_template_path("dispatch").read_text(encoding="utf-8")
    assert runtime.prompts.notify == prompt_template_path("notify").read_text(encoding="utf-8")
    assert runtime.prompts.worker_reminder == prompt_template_path("worker_reminder").read_text(encoding="utf-8")
    assert "skill:coding-agent" in runtime.prompts.worker_reminder
    assert "通过 Codex 持续推进当前任务" in runtime.prompts.worker_reminder


def test_load_prompts_reads_template_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    templates_dir = tmp_path / "prompt_templates"
    templates_dir.mkdir()
    for name in PROMPT_TEMPLATE_FILES:
        (templates_dir / PROMPT_TEMPLATE_FILES[name]).write_text(f"{name.upper()} {{{name}}}", encoding="utf-8")

    monkeypatch.setattr("task_bridge.prompts.prompt_templates_dir", lambda: templates_dir)

    prompts = load_prompts()

    assert prompts.dispatch == "DISPATCH {dispatch}"
    assert prompts.notify == "NOTIFY {notify}"
    assert prompts.notify_team_leader_follow_up == "NOTIFY_TEAM_LEADER_FOLLOW_UP {notify_team_leader_follow_up}"
    assert prompts.worker_reminder == "WORKER_REMINDER {worker_reminder}"
    assert prompts.running_summary == "RUNNING_SUMMARY {running_summary}"
    assert prompts.leader_unresolved_followup == "LEADER_UNRESOLVED_FOLLOWUP {leader_unresolved_followup}"


def test_dispatch_message_uses_template_files(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    templates_dir = tmp_path / "prompt_templates"
    templates_dir.mkdir()
    (templates_dir / PROMPT_TEMPLATE_FILES["dispatch"]).write_text("CUSTOM {task_id} {requirement}", encoding="utf-8")
    (templates_dir / PROMPT_TEMPLATE_FILES["notify"]).write_text("[TASK_UPDATE]\n{task_id}\n{result}{follow_up}", encoding="utf-8")
    (templates_dir / PROMPT_TEMPLATE_FILES["notify_team_leader_follow_up"]).write_text(
        "\nFOLLOWUP {user_chat_id}",
        encoding="utf-8",
    )
    (templates_dir / PROMPT_TEMPLATE_FILES["worker_reminder"]).write_text("REMIND {task_id} {task_path}", encoding="utf-8")
    (templates_dir / PROMPT_TEMPLATE_FILES["running_summary"]).write_text(
        "SUMMARY {running_tasks_count}\n{task_summaries}",
        encoding="utf-8",
    )
    (templates_dir / PROMPT_TEMPLATE_FILES["leader_unresolved_followup"]).write_text(
        "FOLLOWUP {job_id}\n{source_task_summaries}",
        encoding="utf-8",
    )

    monkeypatch.setattr("task_bridge.prompts.prompt_templates_dir", lambda: templates_dir)

    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)
    store = TaskStore(home)
    job = store.create_job(title="custom-prompts")
    task = store.create_task(job_id=job["id"], requirement="自定义 prompt", assigned_agent="code-agent")

    task_path = store.task_path(task["job_id"], task["id"])

    assert runtime._build_dispatch_message(task, task_path) == f"CUSTOM {task['id']} 自定义 prompt"
    notify_message = runtime._build_notify_message(task | {"state": "done", "result": "OK"}, "team-leader")
    assert notify_message.startswith(f"[TASK_UPDATE]\n{task['id']}\nOK")
    assert "\nFOLLOWUP " in notify_message


def test_notify_message_includes_detail_path_only_when_detail_file_exists(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="detail-path-notify")
    task = store.create_task(job_id=job["id"], requirement="A", assigned_agent="code-agent")
    runtime = BridgeRuntime(home=home, sender=lambda *_: None, reset_sender=lambda *_: None)

    without_detail = runtime._build_notify_message(task | {"state": "done", "result": "OK"}, "team-leader")
    assert "detail_path=" not in without_detail

    detail_path = Path(task["detail_path"])
    detail_path.write_text("# details\n\nworker trace\n", encoding="utf-8")

    with_detail = runtime._build_notify_message(task | {"state": "done", "result": "OK"}, "team-leader")
    assert f"detail_path={detail_path}" in with_detail


def test_send_due_leader_unresolved_followups_groups_by_job(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="leader-followup")
    task_a = store.create_task(job_id=job["id"], requirement="A", assigned_agent="code-agent")
    task_b = store.create_task(job_id=job["id"], requirement="B", assigned_agent="quality-agent")

    for task in (task_a, task_b):
        payload = store.load_task(task["id"], job_id=job["id"])
        payload["state"] = "done"
        payload["createdAt"] = "2026-03-10T23:50:00Z"
        payload["_scheduler"]["final_notified_at"] = "2026-03-11T00:00:00Z"
        payload["_scheduler"]["leader_followup_due_at"] = "2026-03-11T00:05:00Z"
        payload["_scheduler"]["leader_followup_sent_at"] = None
        store.save_task(payload)
    Path(task_a["detail_path"]).write_text("detail", encoding="utf-8")

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    outcome = runtime.send_due_leader_unresolved_followups(
        current_time=datetime(2026, 3, 11, 0, 5, 1, tzinfo=timezone.utc),
    )

    assert sorted(outcome.followed_up) == sorted([task_a["id"], task_b["id"]])
    assert len(calls) == 1
    assert calls[0][0] == "team-leader"
    message = calls[0][1]
    assert message.startswith("[TASK_FOLLOWUP_REQUIRED]\n")
    assert f"job_id={job['id']}" in message
    assert "user_chat_id=" in message
    assert f"- task_id={task_a['id']} worker_agent=code-agent state=done detail_path={task_a['detail_path']}" in message
    assert f"- task_id={task_b['id']} worker_agent=quality-agent state=done" in message
    assert "以下终态结果在 5 分钟前已通知给你" in message
    assert "当前 task-bridge 中仍没有观察到该 job 下的新 task" in message
    assert "请立即执行以下之一：" in message
    assert "1. 创建下一步 task；" in message
    assert "2. 明确判断该 job 已完成，并向用户收口；" in message
    assert "3. 若你决定先等待其他 running task" in message
    assert "不要只复述旧结果，不要只回复 NO_REPLY" in message
    persisted_a = store.load_task(task_a["id"], job_id=job["id"])
    persisted_b = store.load_task(task_b["id"], job_id=job["id"])
    assert persisted_a["_scheduler"]["leader_followup_due_at"] is None
    assert persisted_b["_scheduler"]["leader_followup_due_at"] is None
    assert persisted_a["_scheduler"]["leader_followup_sent_at"] == "2026-03-11T00:05:01Z"
    assert persisted_b["_scheduler"]["leader_followup_sent_at"] == "2026-03-11T00:05:01Z"


def test_send_due_leader_unresolved_followups_clears_when_new_task_exists(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="leader-followup-resolved")
    source = store.create_task(job_id=job["id"], requirement="source", assigned_agent="code-agent")
    payload = store.load_task(source["id"], job_id=job["id"])
    payload["state"] = "blocked"
    payload["createdAt"] = "2026-03-11T00:00:00Z"
    payload["_scheduler"]["final_notified_at"] = "2026-03-11T00:01:00Z"
    payload["_scheduler"]["leader_followup_due_at"] = "2026-03-11T00:06:00Z"
    payload["_scheduler"]["leader_followup_sent_at"] = None
    store.save_task(payload)

    followup = store.create_task(job_id=job["id"], requirement="repair", assigned_agent="code-agent")
    followup_payload = store.load_task(followup["id"], job_id=job["id"])
    followup_payload["createdAt"] = "2026-03-11T00:02:00Z"
    store.save_task(followup_payload)

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    outcome = runtime.send_due_leader_unresolved_followups(
        current_time=datetime(2026, 3, 11, 0, 6, 1, tzinfo=timezone.utc),
    )

    assert outcome.followed_up == []
    assert calls == []
    persisted = store.load_task(source["id"], job_id=job["id"])
    assert persisted["_scheduler"]["leader_followup_due_at"] is None
    assert persisted["_scheduler"]["leader_followup_sent_at"] is None


def test_module_entry_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_main(argv: list[str] | None = None) -> int:
        captured["argv"] = argv
        return 7

    monkeypatch.setattr("task_bridge.cli.main", fake_main)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("task_bridge", run_name="__main__")

    assert excinfo.value.code == 7
    assert captured["argv"] is None


def test_queue_for_agent_handles_running_and_filters_blank_agents() -> None:
    queue = queue_for_agent(
        [
            {"id": "task-1", "job_id": "job-1", "assigned_agent": "code-agent", "state": "running"},
            {"id": "task-2", "job_id": "job-1", "assigned_agent": "code-agent", "state": "queued"},
            {"id": "task-3", "job_id": "job-1", "assigned_agent": "", "state": "queued"},
        ],
        "code-agent",
    )

    assert queue["running_task_id"] == "task-1"
    assert [item["id"] for item in queue["queued_tasks"]] == ["task-2"]


def test_build_dispatch_message_includes_requirement_and_status_ordering(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="dispatch-message")
    task = store.create_task(
        job_id=job["id"],
        requirement="实现并验证功能",
        assigned_agent="code-agent",
    )

    runtime = BridgeRuntime(home=home, sender=lambda *_: None)
    task_path = store.task_path(task["job_id"], task["id"])

    message = runtime._build_dispatch_message(task, task_path)

    assert message.startswith("/coding-agent [TASK_DISPATCH]\n")
    assert f"job_id={job['id']}" in message
    assert f"task_id={task['id']}" in message
    assert f"task_path={task_path}" in message
    assert "任务 requirement:" in message
    assert "实现并验证功能" in message
    assert "完全自主推进" in message
    assert "读取 task.json" in message
    assert "必须先通过 task-bridge 将 task 标记为 running" in message
    assert "使用 task-bridge 持续写回 result" in message
    assert "必须对照 requirement 验收结果" in message
    assert "继续修改并再次验证" in message
    assert "如果当前工作目录位于 Git 仓库" in message
    assert "commit 完成后，才可以通过 task-bridge 将任务标记为 complete" in message
    assert "修改 task 状态必须是最后一步" in message
    assert "是否已 commit" in message
    assert f"detail_path={task['detail_path']}" in message
    assert "detail.md" in message


def test_dispatch_once_resets_worker_before_sending_task(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="dispatch-reset-order")
    task = store.create_task(
        job_id=job["id"],
        requirement="派发前先 reset",
        assigned_agent="code-agent",
    )

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(
        home=home,
        sender=lambda agent, message: calls.append((agent, message)),
        reset_sender=lambda agent, message: calls.append((agent, message)),
    )

    outcome = runtime.dispatch_once()

    assert outcome.dispatched == [task["id"]]
    assert calls[0] == ("code-agent", "/reset")
    assert calls[1][0] == "code-agent"
    assert calls[1][1].startswith("/coding-agent [TASK_DISPATCH]\n")
    assert f"task_id={task['id']}" in calls[1][1]


def test_dispatch_once_does_not_overwrite_worker_updates_during_send(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="dispatch-race")
    task = store.create_task(
        job_id=job["id"],
        requirement="修复竞态",
        assigned_agent="code-agent",
    )

    def sender(_agent: str, _message: str) -> None:
        store.update_task(
            task["id"],
            job_id=job["id"],
            state="running",
            result="worker started",
            clear_awaiting_claim=True,
        )
        store.update_task(
            task["id"],
            job_id=job["id"],
            state="done",
            result="worker finished",
        )

    runtime = BridgeRuntime(home=home, sender=sender, reset_sender=lambda *_: None)
    outcome = runtime.dispatch_once()
    persisted = store.load_task(task["id"], job_id=job["id"])
    daemon_state = store.load_daemon_state()
    task_key = f"{job['id']}:{task['id']}"

    assert outcome.dispatched == [task["id"]]
    assert persisted["state"] == "done"
    assert persisted["result"] == "worker finished"
    assert persisted["_scheduler"]["awaiting_claim"] is False
    assert persisted["_scheduler"]["last_dispatch_at"] is not None
    assert daemon_state["worker_last_prompt_at"][task_key] is not None


def test_dispatch_once_rolls_back_pending_claim_when_send_fails(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="dispatch-failure")
    task = store.create_task(
        job_id=job["id"],
        requirement="发送失败回滚",
        assigned_agent="code-agent",
    )

    runtime = BridgeRuntime(
        home=home,
        sender=lambda _agent, _message: (_ for _ in ()).throw(RuntimeError("send failed")),
        reset_sender=lambda *_: None,
    )

    with pytest.raises(RuntimeError, match="send failed"):
        runtime.dispatch_once()

    persisted = store.load_task(task["id"], job_id=job["id"])
    daemon_state = store.load_daemon_state()
    task_key = f"{job['id']}:{task['id']}"
    assert persisted["state"] == "queued"
    assert persisted["result"] == ""
    assert persisted["_scheduler"]["awaiting_claim"] is False
    assert persisted["_scheduler"]["last_dispatch_at"] is not None
    assert task_key not in daemon_state["worker_last_prompt_at"]


def test_dispatch_once_rolls_back_pending_claim_when_reset_fails(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="dispatch-reset-failure")
    task = store.create_task(
        job_id=job["id"],
        requirement="reset 失败回滚",
        assigned_agent="code-agent",
    )

    runtime = BridgeRuntime(
        home=home,
        sender=lambda *_: None,
        reset_sender=lambda _agent, _message: (_ for _ in ()).throw(RuntimeError("reset failed")),
    )

    with pytest.raises(RuntimeError, match="reset failed"):
        runtime.dispatch_once()

    persisted = store.load_task(task["id"], job_id=job["id"])
    daemon_state = store.load_daemon_state()
    task_key = f"{job['id']}:{task['id']}"
    assert persisted["state"] == "queued"
    assert persisted["result"] == ""
    assert persisted["_scheduler"]["awaiting_claim"] is False
    assert persisted["_scheduler"]["last_dispatch_at"] is None
    assert task_key not in daemon_state["worker_last_prompt_at"]


def test_send_due_reminders_respects_intervals_and_updates_state(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TaskStore(home)
    job = store.create_job(title="reminders")
    task = store.create_task(
        job_id=job["id"],
        requirement="持续推进实现",
        assigned_agent="code-agent",
    )
    (home / ".env").write_text("TASK_BRIDGE_USER_CHAT_ID=chat-id-123\n", encoding="utf-8")
    monkeypatch.delenv("TASK_BRIDGE_USER_CHAT_ID", raising=False)
    monkeypatch.chdir(home)
    payload = store.load_task(task["id"], job_id=job["id"])
    payload["state"] = "running"
    payload["_scheduler"]["last_dispatch_at"] = "2026-03-11T00:00:00Z"
    store.save_task(payload)
    store.save_daemon_state(
        {
            "worker_last_prompt_at": {f"{job['id']}:{task['id']}": "2026-03-11T00:00:00Z"},
            "leader_last_running_notice_at": "2026-03-11T00:00:00Z",
        }
    )

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    early = runtime.send_due_reminders(
        worker_interval_seconds=900,
        leader_interval_seconds=3600,
        current_time=datetime(2026, 3, 11, 0, 14, 59, tzinfo=timezone.utc),
    )
    assert early.worker_reminded == []
    assert early.leader_pinged is False
    assert calls == []

    due = runtime.send_due_reminders(
        worker_interval_seconds=900,
        leader_interval_seconds=3600,
        current_time=datetime(2026, 3, 11, 1, 0, 1, tzinfo=timezone.utc),
    )
    daemon_state = store.load_daemon_state()

    assert due.worker_reminded == [task["id"]]
    assert due.leader_pinged is True
    assert calls[0][0] == "code-agent"
    assert calls[0][1].startswith("/coding-agent [TASK_REMINDER]\n")
    assert task["id"] in calls[0][1]
    assert "task_path=" in calls[0][1]
    assert "skill:coding-agent" in calls[0][1]
    assert "通过 Codex 持续推进当前任务" in calls[0][1]
    assert "持续推进实现" not in calls[0][1]
    assert "不要等待" in calls[0][1]
    assert "不要暂停" in calls[0][1]
    assert calls[1][0] == "team-leader"
    assert "user_chat_id=chat-id-123" in calls[1][1]
    assert "通过上面的飞书 chat_id 给我发送总结" in calls[1][1]
    assert daemon_state["worker_last_prompt_at"][f"{job['id']}:{task['id']}"] == "2026-03-11T01:00:01Z"
    assert daemon_state["leader_last_running_notice_at"] == "2026-03-11T01:00:01Z"


def test_send_due_reminders_resets_team_leader_timer_after_idle(home: Path) -> None:
    store = TaskStore(home)
    job = store.create_job(title="leader-reset")
    task = store.create_task(
        job_id=job["id"],
        requirement="运行中任务",
        assigned_agent="code-agent",
    )
    payload = store.load_task(task["id"], job_id=job["id"])
    payload["state"] = "done"
    payload["_scheduler"]["last_dispatch_at"] = "2026-03-11T00:00:00Z"
    store.save_task(payload)
    store.save_daemon_state(
        {
            "worker_last_prompt_at": {},
            "leader_last_running_notice_at": "2026-03-11T00:00:00Z",
        }
    )

    calls: list[tuple[str, str]] = []
    runtime = BridgeRuntime(home=home, sender=lambda agent, message: calls.append((agent, message)))

    idle = runtime.send_due_reminders(
        worker_interval_seconds=900,
        leader_interval_seconds=3600,
        current_time=datetime(2026, 3, 11, 0, 30, 0, tzinfo=timezone.utc),
    )
    assert idle.worker_reminded == []
    assert idle.leader_pinged is False
    assert calls == []
    assert store.load_daemon_state()["leader_last_running_notice_at"] is None

    payload = store.load_task(task["id"], job_id=job["id"])
    payload["state"] = "running"
    payload["_scheduler"]["awaiting_claim"] = False
    store.save_task(payload)

    reminded = runtime.send_due_reminders(
        worker_interval_seconds=900,
        leader_interval_seconds=0,
        current_time=datetime(2026, 3, 11, 0, 31, 0, tzinfo=timezone.utc),
    )
    assert reminded.leader_pinged is True
    assert calls[-1][0] == "team-leader"
