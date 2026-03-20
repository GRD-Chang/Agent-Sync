from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from task_bridge.cli import main
from task_bridge.dashboard import DashboardQueryService, create_dashboard_app
from task_bridge.dashboard.i18n import get_messages
from task_bridge.store import TaskStore


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TASK_BRIDGE_HOME", str(tmp_path))
    return tmp_path


def seed_dashboard_store(home: Path) -> dict[str, dict[str, str]]:
    store = TaskStore(home)
    store.ensure_dirs()

    job_a = store.create_job(title="job-a")
    task_a1 = store.create_task(job_id=job_a["id"], requirement="queued req", assigned_agent="code-agent")
    task_a2 = store.create_task(job_id=job_a["id"], requirement="running req", assigned_agent="quality-agent")
    store.update_task(task_a2["id"], job_id=job_a["id"], state="running", result="actively working")
    Path(task_a2["detail_path"]).write_text("# Runbook\n\n- capture logs\n- compare outputs\n", encoding="utf-8")
    task_a2_record = store.load_task(task_a2["id"], job_id=job_a["id"])
    task_a2_record["_scheduler"]["last_dispatch_at"] = task_a2_record["updatedAt"]
    store.save_task(task_a2_record)

    job_b = store.create_job(title="job-b")
    task_b1 = store.create_task(job_id=job_b["id"], requirement="blocked req", assigned_agent="review-agent")
    store.update_task(task_b1["id"], job_id=job_b["id"], state="blocked", result="waiting on input")
    task_b1_record = store.load_task(task_b1["id"], job_id=job_b["id"])
    task_b1_record["_scheduler"]["final_notified_at"] = task_b1_record["updatedAt"]
    store.save_task(task_b1_record)

    return {
        "job_a": job_a,
        "job_b": job_b,
        "task_a1": task_a1,
        "task_a2": task_a2,
        "task_b1": task_b1,
    }


def flatten_message_keys(value: object, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys.update(flatten_message_keys(nested, path))
        return keys
    return set()


def test_dashboard_help_describes_access_and_launch_guidance(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["dashboard", "-h"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "启动 task-bridge dashboard，集中查看 Overview / Jobs / Tasks / Worker Queue / Alerts / Health。" in help_text
    assert "支持通过页面内切换器在 en / zh-CN 之间切换界面语言" in help_text
    assert "启动后会输出访问地址、数据目录和远程 SSH 端口转发提示" in help_text
    assert "--host" in help_text
    assert "--port" in help_text


def test_dashboard_command_prints_actionable_launch_output(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import task_bridge.cli as cli_module
    import task_bridge.dashboard as dashboard_package

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        dashboard_package,
        "run_dashboard",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(cli_module, "_dashboard_ssh_target", lambda: "dev@10.10.0.8")

    assert main(["dashboard", "--host", "127.0.0.1", "--port", str(port)]) == 0
    output = capsys.readouterr().out

    assert "Dashboard 启动中" in output
    assert "监听地址: 127.0.0.1" in output
    assert f"监听端口: {port}" in output
    assert f"本机访问: http://127.0.0.1:{port}/overview" in output
    assert f"数据目录: {home}" in output
    assert f"ssh -L {port}:127.0.0.1:{port} dev@10.10.0.8" in output
    assert "当前命令不会自动打开浏览器" in output
    assert "Ctrl+C" in output
    assert captured == {"home": home, "host": "127.0.0.1", "port": port}


def test_dashboard_command_reports_occupied_port(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]

        assert main(["dashboard", "--host", "127.0.0.1", "--port", str(port)]) == 2

    error_text = capsys.readouterr().err
    assert f"127.0.0.1:{port}" in error_text
    assert "已被占用" in error_text
    assert re.search(r"task-bridge dashboard --host 127\.0\.0\.1 --port \d+", error_text)


def test_dashboard_default_ui_language_stays_single_locale(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 200
    body = response.text
    assert "<html lang=\"en\">" in body
    assert "Live dispatch posture for the current task bridge" in body
    assert "Recent updates" in body
    assert "Current view" in body
    assert "Task status summary" in body
    assert "Dispatch dashboard" in body
    assert "A single place to review the live picture across jobs, tasks, queues, alerts, and health." in body
    assert 'data-testid="dashboard-locale-switch"' in body
    assert 'data-testid="dashboard-page-chrome"' in body
    assert 'data-testid="dashboard-breadcrumbs"' in body
    assert 'data-testid="dashboard-locale-en"' in body
    assert 'data-testid="dashboard-locale-zh-cn"' in body
    assert 'data-testid="dashboard-font-switch"' in body
    assert 'data-testid="dashboard-font-editorial"' in body
    assert "MVP scope" not in body
    assert "read-only" not in body


def test_dashboard_i18n_catalogs_cover_same_surface() -> None:
    english_keys = flatten_message_keys(dict(get_messages("en")))
    chinese_keys = flatten_message_keys(dict(get_messages("zh-CN")))

    assert chinese_keys == english_keys


def test_dashboard_locale_switch_preserves_selected_task_context(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}")
        zh_response = client.get(f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}&lang=zh-CN")

    assert response.status_code == 200
    body = response.text
    assert re.search(
        rf'data-testid="dashboard-locale-zh-cn"[^>]*href="/tasks\?job={seeded["job_a"]["id"]}&amp;task={seeded["task_a2"]["id"]}&amp;lang=zh-CN"',
        body,
    )

    assert zh_response.status_code == 200
    zh_body = zh_response.text
    assert "<html lang=\"zh-CN\">" in zh_body
    assert "任务总表与详情预览" in zh_body
    assert "进行中" in zh_body
    assert 'data-testid="dashboard-back-link"' in zh_body
    assert re.search(
        rf'data-testid="dashboard-locale-en"[^>]*href="/tasks\?job={seeded["job_a"]["id"]}&amp;task={seeded["task_a2"]["id"]}"',
        zh_body,
    )
    assert (
        f"/jobs?job={seeded['job_a']['id']}&amp;task={seeded['task_a2']['id']}&amp;lang=zh-CN#job-task-detail"
        in zh_body
    )


def test_dashboard_chinese_locale_renders_all_live_pages(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)
    page_specs = [
        ("/overview?lang=zh-CN", "dashboard-overview-hero", "任务状态汇总"),
        (f"/jobs?job={seeded['job_a']['id']}&lang=zh-CN", "dashboard-jobs-page", "作业详情"),
        (
            f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}&lang=zh-CN",
            "dashboard-tasks-page",
            "时间线",
        ),
        ("/worker-queue?lang=zh-CN", "dashboard-worker-queue-hero", "当前负载与队列深度"),
        ("/alerts?lang=zh-CN", "dashboard-alerts-hero", "当前需要处理的事项"),
        ("/health?lang=zh-CN", "dashboard-health-hero", "关键运行摘要"),
    ]

    with TestClient(create_dashboard_app(home)) as client:
        for path, testid, expected_copy in page_specs:
            response = client.get(path)
            body = response.text

            assert response.status_code == 200
            assert "<html lang=\"zh-CN\">" in body
            assert 'data-testid="dashboard-locale-switch"' in body
            assert 'data-testid="dashboard-page-chrome"' in body
            assert re.search(r'data-testid="dashboard-locale-zh-cn"[^>]*aria-current="page"', body)
            assert "集中浏览现有存储中的作业、任务、队列、告警与健康信息。" in body
            assert "总览" in body
            assert "作业" in body
            assert "任务" in body
            assert "代理与队列" in body
            assert "告警" in body
            assert "健康" in body
            assert f'data-testid="{testid}"' in body
            assert expected_copy in body
            assert "只读" not in body


@pytest.mark.parametrize(
    ("path", "testid", "expected_copy"),
    [
        ("/overview?lang=zh-CN", "dashboard-overview-empty-state", "还没有作业或任务"),
        ("/jobs?lang=zh-CN", "dashboard-jobs-empty-state", "还没有作业"),
        ("/tasks?lang=zh-CN", "dashboard-tasks-empty-state", "还没有任务"),
        ("/worker-queue?lang=zh-CN", "dashboard-worker-queue-empty-state", "还没有 agent 活动"),
        ("/alerts?lang=zh-CN", "dashboard-alerts-empty-state", "当前没有需要处理的风险"),
    ],
)
def test_dashboard_chinese_locale_renders_empty_states(
    home: Path,
    path: str,
    testid: str,
    expected_copy: str,
) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(path)

    assert response.status_code == 200
    body = response.text
    assert "<html lang=\"zh-CN\">" in body
    assert f'data-testid="{testid}"' in body
    assert expected_copy in body


def test_dashboard_overview_query_summarizes_existing_task_contract(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="dashboard-summary")
    queued = store.create_task(job_id=job["id"], requirement="queued req", assigned_agent="code-agent")
    running = store.create_task(job_id=job["id"], requirement="running req", assigned_agent="quality-agent")
    done = store.create_task(job_id=job["id"], requirement="done req", assigned_agent="code-agent")
    blocked = store.create_task(job_id=job["id"], requirement="blocked req", assigned_agent="review-agent")

    store.update_task(running["id"], job_id=job["id"], state="running", result="actively working")
    store.update_task(done["id"], job_id=job["id"], state="done", result="implemented")
    store.update_task(blocked["id"], job_id=job["id"], state="blocked", result="waiting on input")

    overview = DashboardQueryService(home).overview()

    assert overview.current_job_id == job["id"]
    assert overview.jobs_count == 1
    assert overview.tasks_count == 4
    assert overview.terminal_count == 2
    assert overview.queued_tasks == 1
    assert overview.worker_count == 3
    assert overview.busy_workers == 1
    assert overview.idle_workers == 2

    metrics = {metric.state: metric.count for metric in overview.task_status_metrics}
    assert metrics == {
        "queued": 1,
        "running": 1,
        "done": 1,
        "blocked": 1,
        "failed": 0,
    }

    by_agent = {worker.agent: worker for worker in overview.workers}
    assert by_agent["quality-agent"].status == "busy"
    assert by_agent["quality-agent"].running_task_id == running["id"]
    assert by_agent["code-agent"].queued == 1
    assert by_agent["code-agent"].next_queued_task_id == queued["id"]
    assert by_agent["review-agent"].next_queued_task_id is None

    assert overview.recent_updates[0].task_id == blocked["id"]
    assert overview.recent_updates[0].summary_label == "Result"
    assert overview.recent_updates[-1].task_id == queued["id"]
    assert overview.recent_updates[-1].summary_label == "Requirement"


def test_dashboard_jobs_query_builds_live_read_only_snapshot(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    jobs = DashboardQueryService(home).jobs(selected_job_id=seeded["job_a"]["id"])

    assert jobs.jobs_count == 2
    assert jobs.tasks_count == 3
    assert jobs.visible_jobs_count == 2
    assert jobs.active_view == "all"
    assert jobs.is_empty is False
    assert jobs.filtered_empty is False
    assert jobs.selection_missing is False
    assert jobs.selected_job is not None
    assert jobs.selected_task is None
    assert jobs.selected_job.job_id == seeded["job_a"]["id"]
    assert jobs.detail_back_link is not None
    assert jobs.detail_back_link.href == "/jobs#jobs-registry"
    assert jobs.selected_job.task_count == 2
    assert jobs.selected_job.active_task_count == 2
    assert jobs.selected_job.terminal_task_count == 0
    assert jobs.selected_job.tasks_href.endswith(f"/tasks?job={seeded['job_a']['id']}#tasks-registry")
    assert jobs.selected_job.latest_task_href is not None
    assert [item.task_id for item in jobs.selected_job.task_previews] == [
        seeded["task_a2"]["id"],
        seeded["task_a1"]["id"],
    ]
    assert [group.state for group in jobs.selected_job.task_groups] == ["running", "queued"]
    assert jobs.selected_job.task_previews[0].detail_href.endswith(
        f"/jobs?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}#job-task-detail"
    )


def test_dashboard_jobs_query_filters_by_active_view(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    jobs = DashboardQueryService(home).jobs(selected_view="active")

    assert jobs.visible_jobs_count == 1
    assert jobs.filtered_empty is False
    assert [item.job_id for item in jobs.jobs] == [seeded["job_a"]["id"]]
    assert jobs.selected_job is None
    assert jobs.detail_back_link is None


def test_dashboard_jobs_query_surfaces_all_tasks_in_status_groups_and_inline_task_detail(home: Path) -> None:
    seeded = seed_dashboard_store_with_many_job_tasks(home)
    selected_task = str(seeded["tasks"][1]["id"])

    jobs = DashboardQueryService(home).jobs(
        selected_job_id=str(seeded["job"]["id"]),
        selected_task_id=selected_task,
    )

    assert jobs.selected_job is not None
    assert jobs.selected_task is not None
    assert jobs.selected_job.task_count == 8
    assert len(jobs.selected_job.task_previews) == 8
    assert [group.state for group in jobs.selected_job.task_groups] == ["running", "blocked", "failed", "queued", "done"]
    assert [group.count for group in jobs.selected_job.task_groups] == [2, 1, 1, 2, 2]
    assert jobs.selected_task.task_id == selected_task
    assert jobs.selected_task.back_links[0].href.endswith("#job-task-groups")
    assert jobs.selected_task.back_links[1].href.endswith("#tasks-detail")


def test_dashboard_tasks_query_builds_preview_and_timeline(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    tasks = DashboardQueryService(home).tasks(
        selected_job_id=seeded["job_a"]["id"],
        selected_task_id=seeded["task_a2"]["id"],
    )

    assert tasks.tasks_count == 3
    assert tasks.visible_tasks_count == 2
    assert tasks.is_empty is False
    assert tasks.filtered_empty is False
    assert tasks.selection_missing is False
    assert tasks.selected_task is not None
    assert tasks.selected_task.task_id == seeded["task_a2"]["id"]
    assert tasks.detail_back_link is not None
    assert tasks.detail_back_link.href == f"/tasks?job={seeded['job_a']['id']}#tasks-registry"
    assert [item.label for item in tasks.selected_task.back_links] == ["Back to filtered task cards", "Back to job detail"]
    assert tasks.selected_task.back_links[1].href == (
        f"/jobs?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}#job-task-detail"
    )
    assert tasks.selected_task.detail_status_label == "Preview ready"
    assert tasks.selected_task.detail_preview.status == "rendered"
    assert [block.kind for block in tasks.selected_task.detail_preview.blocks] == ["heading", "list"]
    assert [event.key for event in tasks.selected_task.timeline] == ["created", "updated", "dispatch"]
    assert tasks.selected_task.result == "actively working"


def test_dashboard_jobs_page_chrome_exposes_breadcrumbs_and_back_link(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/jobs?view=active&job={seeded['job_a']['id']}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-page-chrome"' in body
    assert 'data-testid="dashboard-breadcrumbs"' in body
    assert 'data-testid="dashboard-back-link"' in body
    assert "Back to Jobs" in body
    assert "job-a" in body
    assert "Back to job cards" in body
    assert re.search(r'data-testid="dashboard-back-link"[^>]*href="/jobs\?view=active"', body)


def test_dashboard_tasks_page_chrome_preserves_filters_in_back_link(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(
            f"/tasks?job={seeded['job_a']['id']}&state=running&agent=quality-agent&task={seeded['task_a2']['id']}"
        )

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-page-chrome"' in body
    assert 'data-testid="dashboard-breadcrumbs"' in body
    assert 'data-testid="dashboard-back-link"' in body
    assert "Back to Tasks" in body
    assert "Back to filtered task cards" in body
    assert "Back to job detail" in body
    assert seeded["task_a2"]["id"] in body
    assert re.search(
        rf'data-testid="dashboard-back-link"[^>]*href="/tasks\?job={seeded["job_a"]["id"]}&amp;state=running&amp;agent=quality-agent"',
        body,
    )


def test_dashboard_tasks_query_normalizes_escaped_newlines(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="multiline")
    task = store.create_task(job_id=job["id"], requirement="line one\\nline two", assigned_agent="code-agent")
    store.update_task(task["id"], job_id=job["id"], state="done", result="alpha\\n beta")

    snapshot = DashboardQueryService(home).tasks(selected_job_id=job["id"], selected_task_id=task["id"])

    assert snapshot.selected_task is not None
    assert snapshot.selected_task.requirement == "line one\nline two"
    assert snapshot.selected_task.result == "alpha\n beta"
    assert snapshot.tasks[0].summary_text == "alpha\n beta"

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/tasks?job={job['id']}&task={task['id']}")

    assert response.status_code == 200
    body = response.text
    assert "line one\nline two" in body
    assert "alpha\n beta" in body
    assert "line one\\nline two" not in body
    assert "alpha\\n beta" not in body


def test_dashboard_tasks_query_filters_by_job_state_and_agent(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    tasks = DashboardQueryService(home).tasks(
        selected_job_id=seeded["job_a"]["id"],
        selected_state="running",
        selected_agent="quality-agent",
    )

    assert tasks.visible_tasks_count == 1
    assert tasks.filtered_empty is False
    assert [item.task_id for item in tasks.tasks] == [seeded["task_a2"]["id"]]
    assert tasks.selected_task is None
    assert tasks.detail_back_link is None
    assert {item.label: item.value for item in tasks.applied_filters} == {
        "Job": "job-a",
        "State": "Running",
        "Assigned agent": "quality-agent",
    }


def test_dashboard_tasks_query_groups_statuses_and_paginates(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="paged-tasks")
    state_cycle = ["running", "blocked", "failed", "queued", "done"]
    for index in range(14):
        task = store.create_task(
            job_id=job["id"],
            requirement=f"task {index}",
            assigned_agent=f"agent-{index % 3}",
        )
        state = state_cycle[index % len(state_cycle)]
        if state != "queued":
            store.update_task(task["id"], job_id=job["id"], state=state, result=f"result {index}")

    snapshot = DashboardQueryService(home).tasks(selected_job_id=job["id"])

    assert snapshot.visible_tasks_count == 14
    assert snapshot.pagination.page == 1
    assert snapshot.pagination.page_count == 2
    assert len(snapshot.tasks) == 12
    assert [group.state for group in snapshot.task_groups][:3] == ["running", "blocked", "failed"]

    second_page = DashboardQueryService(home).tasks(selected_job_id=job["id"], selected_page="2")

    assert second_page.pagination.page == 2
    assert second_page.pagination.page_count == 2
    assert len(second_page.tasks) == 2


def seed_operational_dashboard_store(home: Path) -> dict[str, dict[str, str]]:
    seeded = seed_dashboard_store(home)
    store = TaskStore(home)

    task_a3 = store.create_task(job_id=seeded["job_a"]["id"], requirement="triage backlog")
    task_b2 = store.create_task(job_id=seeded["job_b"]["id"], requirement="failed req", assigned_agent="ops-agent")
    store.update_task(task_b2["id"], job_id=seeded["job_b"]["id"], state="failed", result="worker crashed")

    task_b1_record = store.load_task(seeded["task_b1"]["id"], job_id=seeded["job_b"]["id"])
    task_b1_record["_scheduler"]["final_notified_at"] = "2026-03-19T09:00:00Z"
    task_b1_record["_scheduler"]["leader_followup_due_at"] = "2026-03-19T10:00:00Z"
    store.save_task(task_b1_record)

    task_b2_record = store.load_task(task_b2["id"], job_id=seeded["job_b"]["id"])
    task_b2_record["_scheduler"]["final_notified_at"] = "2026-03-20T08:00:00Z"
    store.save_task(task_b2_record)

    store.save_daemon_state(
        {
            "worker_last_prompt_at": {
                "code-agent": "2026-03-20T09:15:00Z",
                "quality-agent": "2026-03-20T09:20:00Z",
                "review-agent": "2026-03-20T09:30:00Z",
            },
            "leader_last_running_notice_at": "2026-03-20T11:45:00Z",
        }
    )

    return {
        **seeded,
        "task_a3": task_a3,
        "task_b2": task_b2,
    }


def seed_dashboard_store_with_many_job_tasks(home: Path) -> dict[str, object]:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="status-stack")
    seeded_tasks: list[dict[str, str]] = []
    task_specs = [
        ("running req 1", "code-agent", "running", "shipping"),
        ("blocked req 1", "review-agent", "blocked", "waiting"),
        ("failed req 1", "ops-agent", "failed", "failed once"),
        ("queued req 1", "qa-agent", None, None),
        ("done req 1", "code-agent", "done", "complete"),
        ("running req 2", "quality-agent", "running", "verifying"),
        ("queued req 2", "review-agent", None, None),
        ("done req 2", "ops-agent", "done", "closed"),
    ]
    for requirement, agent, state, result in task_specs:
        task = store.create_task(job_id=job["id"], requirement=requirement, assigned_agent=agent)
        if state is not None:
            store.update_task(task["id"], job_id=job["id"], state=state, result=result)
        seeded_tasks.append(store.load_task(task["id"], job_id=job["id"]))

    return {"job": job, "tasks": seeded_tasks}


def test_dashboard_worker_queue_query_builds_live_base_snapshot(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)

    worker_queue = DashboardQueryService(home).worker_queue()

    assert worker_queue.worker_count == 4
    assert worker_queue.busy_workers == 1
    assert worker_queue.idle_workers == 3
    assert worker_queue.running_tasks == 1
    assert worker_queue.assigned_queue_depth == 1
    assert worker_queue.unassigned_queue_depth == 1
    assert worker_queue.has_activity is True
    lanes = {lane.agent: lane for lane in worker_queue.lanes}
    assert lanes["quality-agent"].running_task_id == seeded["task_a2"]["id"]
    assert [task.task_id for task in lanes["code-agent"].queued_tasks] == [seeded["task_a1"]["id"]]
    assert [task.task_id for task in worker_queue.unassigned_queued_tasks] == [seeded["task_a3"]["id"]]


def test_dashboard_alerts_query_builds_live_base_snapshot(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)

    alerts = DashboardQueryService(home, now_provider=lambda: "2026-03-20T12:00:00Z").alerts()

    assert alerts.blocked_count == 1
    assert alerts.failed_count == 1
    assert alerts.pending_followups_count == 1
    assert alerts.overdue_followups_count == 1
    assert alerts.has_alerts is True
    assert {task.task_id for task in alerts.risk_tasks} == {seeded["task_b1"]["id"], seeded["task_b2"]["id"]}
    assert alerts.followup_tasks[0].task_id == seeded["task_b1"]["id"]
    assert alerts.followup_tasks[0].is_overdue is True


def test_dashboard_health_query_builds_live_base_snapshot(home: Path) -> None:
    seed_operational_dashboard_store(home)

    health = DashboardQueryService(home).health()

    assert health.jobs_count == 2
    assert health.tasks_count == 5
    assert health.worker_prompt_entries == 3
    assert health.leader_last_running_notice_at == "2026-03-20 11:45 UTC"
    assert {check.key: check.status for check in health.checks} == {
        "store-home": "ok",
        "records": "ok",
        "daemon-state": "ok",
        "prompt-cache": "ok",
    }


def test_dashboard_overview_query_empty_state_is_explicit(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()

    overview = DashboardQueryService(home).overview()

    assert overview.is_empty is True
    assert overview.jobs_count == 0
    assert overview.tasks_count == 0
    assert overview.terminal_count == 0
    assert overview.busy_workers == 0
    assert overview.queued_tasks == 0
    assert overview.recent_updates == []
    assert [metric.count for metric in overview.task_status_metrics] == [0, 0, 0, 0, 0]


def test_dashboard_root_redirects_to_overview(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/overview")


def test_dashboard_overview_route_exposes_frozen_read_only_selectors(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-shell"' in body
    assert 'data-testid="dashboard-primary-nav"' in body
    assert 'data-testid="dashboard-page-chrome"' in body
    assert 'data-testid="dashboard-breadcrumbs"' in body
    assert body.count('data-testid="dashboard-nav-') == 6
    assert 'data-testid="dashboard-page-title"' in body
    assert 'data-testid="dashboard-overview-hero"' in body
    assert 'data-testid="dashboard-overview-task-status"' in body
    assert 'data-testid="dashboard-overview-worker-utilization"' in body
    assert 'data-testid="dashboard-overview-worker-list"' in body
    assert 'data-testid="dashboard-overview-recent-updates"' in body
    assert 'data-testid="dashboard-overview-empty-state"' in body
    assert 'data-testid="dashboard-overview-error-state"' not in body


def test_dashboard_overview_route_renders_live_facts_for_existing_store(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="dashboard-summary")
    queued = store.create_task(job_id=job["id"], requirement="queued req", assigned_agent="code-agent")
    running = store.create_task(job_id=job["id"], requirement="running req", assigned_agent="quality-agent")
    blocked = store.create_task(job_id=job["id"], requirement="blocked req", assigned_agent="review-agent")

    store.update_task(running["id"], job_id=job["id"], state="running", result="actively working")
    store.update_task(blocked["id"], job_id=job["id"], state="blocked", result="waiting on input")

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 200
    body = response.text
    assert job["id"] in body
    assert queued["id"] in body
    assert "quality-agent" in body
    assert "waiting on input" in body
    assert 'data-testid="dashboard-overview-empty-state"' not in body


def test_dashboard_overview_recent_updates_link_into_job_task_detail(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 200
    body = response.text
    assert (
        f'data-testid="dashboard-overview-recent-task-{seeded["task_a2"]["id"]}"'
        f' href="/jobs?job={seeded["job_a"]["id"]}&amp;task={seeded["task_a2"]["id"]}#job-task-detail"'
    ) in body


def test_dashboard_jobs_route_renders_live_list_and_detail(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/jobs?job={seeded['job_a']['id']}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-jobs-page"' in body
    assert 'data-testid="dashboard-jobs-filters"' in body
    assert 'data-testid="dashboard-jobs-list"' in body
    assert 'data-testid="dashboard-jobs-detail-shell"' in body
    assert 'data-testid="dashboard-jobs-detail"' in body
    assert 'data-testid="dashboard-jobs-task-groups"' in body
    assert seeded["job_a"]["id"] in body
    assert seeded["job_b"]["id"] in body
    assert "job-a" in body
    assert "queued req" in body
    assert f"/tasks?job={seeded['job_a']['id']}#tasks-registry" in body
    assert f"/jobs?job={seeded['job_a']['id']}&amp;task={seeded['task_a2']['id']}#job-task-detail" in body
    assert 'data-testid="dashboard-jobs-empty-state"' not in body


def test_dashboard_jobs_route_keeps_task_drilldown_on_jobs_page_and_shows_all_cards(home: Path) -> None:
    seeded = seed_dashboard_store_with_many_job_tasks(home)
    selected_task = str(seeded["tasks"][1]["id"])

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/jobs?job={seeded['job']['id']}&task={selected_task}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-jobs-detail-shell"' in body
    assert 'data-testid="dashboard-jobs-task-detail"' in body
    assert 'data-testid="dashboard-jobs-task-groups"' in body
    assert body.count('data-testid="dashboard-jobs-task-card-') == 8
    assert f"/jobs?job={seeded['job']['id']}&amp;task={selected_task}#job-task-detail" in body
    assert f"/tasks?job={seeded['job']['id']}&amp;task={selected_task}#tasks-detail" in body


def test_dashboard_jobs_route_filters_existing_records_by_view(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/jobs?view=active")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-jobs-view-active"' in body
    assert 'data-testid="dashboard-jobs-list-card-{}"'.format(seeded["job_a"]["id"]) in body
    assert 'data-testid="dashboard-jobs-list-card-{}"'.format(seeded["job_b"]["id"]) not in body
    assert 'data-testid="dashboard-jobs-detail"' not in body


def test_dashboard_jobs_route_explicit_empty_state(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/jobs")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-jobs-page"' in body
    assert 'data-testid="dashboard-jobs-empty-state"' in body
    assert "No jobs yet" in body


def test_dashboard_tasks_route_renders_live_list_detail_preview_and_timeline(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-tasks-page"' in body
    assert 'data-testid="dashboard-tasks-filters"' in body
    assert 'data-testid="dashboard-tasks-detail-shell"' in body
    assert 'data-testid="dashboard-tasks-detail"' in body
    assert 'data-testid="dashboard-tasks-detail-preview"' in body
    assert 'data-testid="dashboard-tasks-detail-preview-rendered"' in body
    assert 'data-testid="dashboard-tasks-timeline"' in body
    assert seeded["task_a2"]["id"] in body
    assert "Preview ready" in body
    assert "Runbook" in body
    assert "capture logs" in body
    assert "Task created" in body
    assert "Last dispatch recorded" in body
    assert f"/jobs?job={seeded['job_a']['id']}" in body
    assert 'data-testid="dashboard-tasks-empty-state"' not in body


def test_dashboard_tasks_route_filters_and_handles_missing_detail(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(
            f"/tasks?job={seeded['job_a']['id']}&state=queued&agent=code-agent&task={seeded['task_a1']['id']}"
        )

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-tasks-detail-shell"' in body
    assert seeded["task_a1"]["id"] in body
    assert seeded["task_a2"]["id"] not in body
    assert 'data-testid="dashboard-tasks-detail-preview-missing"' in body
    assert "File missing" in body


def test_dashboard_tasks_route_shows_filter_empty_state(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/tasks?job={seeded['job_a']['id']}&state=done")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-tasks-filter-empty"' in body
    assert 'data-testid="dashboard-tasks-detail"' not in body
    assert "No tasks match these filters" in body


def test_dashboard_tasks_route_renders_status_groups_and_pagination(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="paged-route")
    state_cycle = ["running", "blocked", "failed", "queued", "done"]
    for index in range(14):
        task = store.create_task(job_id=job["id"], requirement=f"task {index}", assigned_agent="agent")
        state = state_cycle[index % len(state_cycle)]
        if state != "queued":
            store.update_task(task["id"], job_id=job["id"], state=state, result=f"result {index}")

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/tasks?job={job['id']}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-tasks-group-running"' in body
    assert 'data-testid="dashboard-tasks-group-blocked"' in body
    assert 'data-testid="dashboard-tasks-pagination"' in body
    assert "#tasks-registry" in body


def test_dashboard_tasks_route_explicit_empty_state(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/tasks")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-tasks-page"' in body
    assert 'data-testid="dashboard-tasks-empty-state"' in body
    assert "No tasks yet" in body


def test_dashboard_worker_queue_route_renders_live_base_page(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/worker-queue")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-worker-queue-hero"' in body
    assert 'data-testid="dashboard-worker-queue-summary"' in body
    assert 'data-testid="dashboard-worker-queue-lanes"' in body
    assert 'data-testid="dashboard-worker-queue-unassigned"' in body
    assert seeded["task_a1"]["id"] in body
    assert seeded["task_a3"]["id"] in body
    assert "quality-agent" in body
    assert "Worker queue across agents" in body
    assert 'class="queue-layout"' in body
    assert "browse-layout" not in body
    assert "Each card shows the task in progress plus queued work for that agent." in body
    assert 'data-testid="dashboard-worker-queue-empty-state"' not in body
    assert re.search(r'data-testid="dashboard-nav-worker-queue"[^>]*aria-current="page"', body)
    assert "<form" not in body
    assert "<button" not in body
    assert "<input" not in body
    assert "<textarea" not in body
    assert "<select" not in body


def test_dashboard_alerts_route_renders_live_base_page(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/alerts")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-alerts-hero"' in body
    assert 'data-testid="dashboard-alerts-summary"' in body
    assert 'data-testid="dashboard-alerts-risk-list"' in body
    assert 'data-testid="dashboard-alerts-followups"' in body
    assert seeded["task_b1"]["id"] in body
    assert seeded["task_b2"]["id"] in body
    assert "worker crashed" in body
    assert 'class="alerts-layout"' in body
    assert "browse-layout" not in body
    assert "Review the latest task summary before deciding the next action." in body
    assert re.search(r'data-testid="dashboard-nav-alerts"[^>]*aria-current="page"', body)
    assert "<form" not in body
    assert "<button" not in body
    assert "<input" not in body
    assert "<textarea" not in body
    assert "<select" not in body


def test_dashboard_alerts_route_paginates_large_card_sets(home: Path) -> None:
    store = TaskStore(home)
    store.ensure_dirs()
    job = store.create_job(title="alert-stack")
    for index in range(10):
        blocked = store.create_task(job_id=job["id"], requirement=f"blocked {index}", assigned_agent="ops-agent")
        store.update_task(blocked["id"], job_id=job["id"], state="blocked", result=f"waiting {index}")
        blocked_record = store.load_task(blocked["id"], job_id=job["id"])
        blocked_record["_scheduler"]["final_notified_at"] = f"2026-03-19T0{index % 9}:00:00Z"
        blocked_record["_scheduler"]["leader_followup_due_at"] = f"2026-03-19T1{index % 9}:00:00Z"
        store.save_task(blocked_record)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/alerts")
        second_page = client.get("/alerts?risk_page=2&followup_page=2")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-alerts-risk-pagination"' in body
    assert 'data-testid="dashboard-alerts-followup-pagination"' in body
    assert "#alerts-risk-list" in body
    assert "#alerts-followups" in body

    assert second_page.status_code == 200
    assert 'data-testid="dashboard-alerts-risk-pagination"' in second_page.text


def test_dashboard_health_route_renders_live_base_page(home: Path) -> None:
    seed_operational_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-health-hero"' in body
    assert 'data-testid="dashboard-health-summary"' in body
    assert 'data-testid="dashboard-health-checks"' in body
    assert "daemon_state.json" in body
    assert "2026-03-20 11:45 UTC" in body
    assert "Readability checks" in body
    assert "Warnings here come only from readable local files." in body
    assert re.search(r'data-testid="dashboard-nav-health"[^>]*aria-current="page"', body)
    assert "<form" not in body
    assert "<button" not in body
    assert "<input" not in body
    assert "<textarea" not in body
    assert "<select" not in body


def test_dashboard_overview_error_state_preserves_shell(home: Path) -> None:
    job_dir = home / "jobs" / "job-broken"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text("{broken", encoding="utf-8")

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 500
    body = response.text
    assert 'data-testid="dashboard-shell"' in body
    assert 'data-testid="dashboard-primary-nav"' in body
    assert 'data-testid="dashboard-page-title"' in body
    assert 'data-testid="dashboard-overview-error-state"' in body
    assert "Overview unavailable" in body
    assert "Store read failed" in body


def test_dashboard_overview_error_state_localizes_to_chinese(home: Path) -> None:
    job_dir = home / "jobs" / "job-broken"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text("{broken", encoding="utf-8")

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview?lang=zh-CN")

    assert response.status_code == 500
    body = response.text
    assert "<html lang=\"zh-CN\">" in body
    assert 'data-testid="dashboard-shell"' in body
    assert 'data-testid="dashboard-overview-error-state"' in body
    assert "总览暂不可用" in body
    assert "读取存储失败" in body
