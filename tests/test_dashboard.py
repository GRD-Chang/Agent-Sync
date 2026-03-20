from __future__ import annotations

import re
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


def test_dashboard_help_describes_read_only_shell(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["dashboard", "-h"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "启动 task-bridge 的只读 dashboard" in help_text
    assert "Overview / Jobs / Tasks / Worker & Queue / Alerts / Health 为只读 MVP 页面" in help_text
    assert "支持通过页面内切换器在 en / zh-CN 之间切换界面语言" in help_text
    assert "Worker & Queue / Alerts / Health 保持基础只读范围" in help_text
    assert "--host" in help_text
    assert "--port" in help_text


def test_dashboard_default_ui_language_stays_single_locale(home: Path) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get("/overview")

    assert response.status_code == 200
    body = response.text
    assert "<html lang=\"en\">" in body
    assert "Live dispatch posture for the current task bridge." in body
    assert "Recent updates" in body
    assert "MVP scope" in body
    assert "Task status summary" in body
    assert "Dashboard foundation" in body
    assert "All six primary pages are live and read-only." in body
    assert 'data-testid="dashboard-locale-switch"' in body
    assert 'data-testid="dashboard-locale-en"' in body
    assert 'data-testid="dashboard-locale-zh-cn"' in body


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
    assert "带详情预览的只读任务登记。" in zh_body
    assert "进行中" in zh_body
    assert re.search(
        rf'data-testid="dashboard-locale-en"[^>]*href="/tasks\?job={seeded["job_a"]["id"]}&amp;task={seeded["task_a2"]["id"]}"',
        zh_body,
    )
    assert f"/jobs?job={seeded['job_a']['id']}&amp;lang=zh-CN" in zh_body


def test_dashboard_chinese_locale_renders_all_live_pages(home: Path) -> None:
    seeded = seed_operational_dashboard_store(home)
    page_specs = [
        ("/overview?lang=zh-CN", "dashboard-overview-hero", "任务状态汇总"),
        (f"/jobs?job={seeded['job_a']['id']}&lang=zh-CN", "dashboard-jobs-page", "作业列表"),
        (
            f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}&lang=zh-CN",
            "dashboard-tasks-page",
            "时间线框架",
        ),
        ("/worker-queue?lang=zh-CN", "dashboard-worker-queue-hero", "代理占用与队列深度"),
        ("/alerts?lang=zh-CN", "dashboard-alerts-hero", "终态与跟进汇总"),
        ("/health?lang=zh-CN", "dashboard-health-hero", "存储与 daemon 摘要"),
    ]

    with TestClient(create_dashboard_app(home)) as client:
        for path, testid, expected_copy in page_specs:
            response = client.get(path)
            body = response.text

            assert response.status_code == 200
            assert "<html lang=\"zh-CN\">" in body
            assert 'data-testid="dashboard-locale-switch"' in body
            assert re.search(r'data-testid="dashboard-locale-zh-cn"[^>]*aria-current="page"', body)
            assert "六个主页面都已上线且保持只读。" in body
            assert "总览" in body
            assert "作业" in body
            assert "任务" in body
            assert "代理与队列" in body
            assert "告警" in body
            assert "健康" in body
            assert f'data-testid="{testid}"' in body
            assert expected_copy in body


@pytest.mark.parametrize(
    ("path", "testid", "expected_copy"),
    [
        ("/overview?lang=zh-CN", "dashboard-overview-empty-state", "还没有作业或任务"),
        ("/jobs?lang=zh-CN", "dashboard-jobs-empty-state", "还没有作业"),
        ("/tasks?lang=zh-CN", "dashboard-tasks-empty-state", "还没有任务"),
        ("/worker-queue?lang=zh-CN", "dashboard-worker-queue-empty-state", "还没有代理或队列活动"),
        ("/alerts?lang=zh-CN", "dashboard-alerts-empty-state", "当前没有告警态势"),
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
    assert jobs.is_empty is False
    assert jobs.selection_missing is False
    assert jobs.selected_job is not None
    assert jobs.selected_job.job_id == seeded["job_a"]["id"]
    assert jobs.selected_job.task_count == 2
    assert jobs.selected_job.active_task_count == 2
    assert jobs.selected_job.terminal_task_count == 0
    assert [item.task_id for item in jobs.selected_job.task_previews] == [
        seeded["task_a2"]["id"],
        seeded["task_a1"]["id"],
    ]
    assert jobs.selected_job.task_previews[0].detail_href.endswith(
        f"/tasks?job={seeded['job_a']['id']}&task={seeded['task_a2']['id']}"
    )


def test_dashboard_tasks_query_builds_preview_and_timeline(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    tasks = DashboardQueryService(home).tasks(
        selected_job_id=seeded["job_a"]["id"],
        selected_task_id=seeded["task_a2"]["id"],
    )

    assert tasks.tasks_count == 3
    assert tasks.is_empty is False
    assert tasks.selection_missing is False
    assert tasks.selected_task is not None
    assert tasks.selected_task.task_id == seeded["task_a2"]["id"]
    assert tasks.selected_task.detail_preview.status == "rendered"
    assert [block.kind for block in tasks.selected_task.detail_preview.blocks] == ["heading", "list"]
    assert [event.key for event in tasks.selected_task.timeline] == ["created", "updated", "dispatch"]
    assert tasks.selected_task.result == "actively working"


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


def test_dashboard_jobs_route_renders_live_list_and_detail(home: Path) -> None:
    seeded = seed_dashboard_store(home)

    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(f"/jobs?job={seeded['job_a']['id']}")

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-jobs-page"' in body
    assert 'data-testid="dashboard-jobs-list"' in body
    assert 'data-testid="dashboard-jobs-detail"' in body
    assert seeded["job_a"]["id"] in body
    assert seeded["job_b"]["id"] in body
    assert "job-a" in body
    assert "queued req" in body
    assert f"/tasks?job={seeded['job_a']['id']}&amp;task={seeded['task_a2']['id']}" in body
    assert 'data-testid="dashboard-jobs-empty-state"' not in body


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
    assert 'data-testid="dashboard-tasks-list"' in body
    assert 'data-testid="dashboard-tasks-detail"' in body
    assert 'data-testid="dashboard-tasks-detail-preview"' in body
    assert 'data-testid="dashboard-tasks-timeline"' in body
    assert seeded["task_a2"]["id"] in body
    assert "Runbook" in body
    assert "capture logs" in body
    assert "Task created" in body
    assert "Last dispatch recorded" in body
    assert f"/jobs?job={seeded['job_a']['id']}" in body
    assert 'data-testid="dashboard-tasks-empty-state"' not in body


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
    assert re.search(r'data-testid="dashboard-nav-alerts"[^>]*aria-current="page"', body)
    assert "<form" not in body
    assert "<button" not in body
    assert "<input" not in body
    assert "<textarea" not in body
    assert "<select" not in body


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
