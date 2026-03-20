from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from task_bridge.cli import main
from task_bridge.dashboard import DashboardQueryService, create_dashboard_app
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


def test_dashboard_help_describes_read_only_shell(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["dashboard", "-h"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "启动 task-bridge 的只读 dashboard" in help_text
    assert "Overview / Jobs / Tasks 为只读 MVP 页面" in help_text
    assert "Worker & Queue / Alerts / Health 仍保留壳层" in help_text
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
    assert "Overview, Jobs, and Tasks are live." in body


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


@pytest.mark.parametrize(
    ("route", "page_key"),
    [
        ("/worker-queue", "worker-queue"),
        ("/alerts", "alerts"),
        ("/health", "health"),
    ],
)
def test_dashboard_placeholder_routes_keep_shell_only_contract(
    home: Path,
    route: str,
    page_key: str,
) -> None:
    with TestClient(create_dashboard_app(home)) as client:
        response = client.get(route)

    assert response.status_code == 200
    body = response.text
    assert 'data-testid="dashboard-shell"' in body
    assert 'data-testid="dashboard-primary-nav"' in body
    assert 'data-testid="dashboard-page-title"' in body
    assert 'data-testid="dashboard-boundary-note"' in body
    assert f'data-testid="dashboard-{page_key}-shell"' in body
    assert re.search(
        rf'data-testid="dashboard-nav-{re.escape(page_key)}"[^>]*aria-current="page"',
        body,
    )
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
