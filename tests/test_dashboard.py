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


def test_dashboard_help_describes_read_only_shell(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["dashboard", "-h"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "启动 task-bridge 的只读 dashboard" in help_text
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
    assert "Overview, Worker &amp; Queue, Alerts, and Health are live." in body


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
