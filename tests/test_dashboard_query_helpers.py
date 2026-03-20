from __future__ import annotations

from pathlib import Path

from task_bridge.dashboard import DashboardQueryService
from task_bridge.dashboard.detail_preview import load_detail_preview
from task_bridge.dashboard.formatting import (
    format_timestamp,
    is_overdue,
    optional_display_text,
    parse_timestamp,
)
from task_bridge.dashboard.pagination import page_for_task, paginate_items, parse_page_number
from task_bridge.dashboard.snapshots import DetailBackLink
from task_bridge.dashboard.task_display_queries import TaskDisplayQueryAssembler
from task_bridge.store import TaskStore


def test_dashboard_detail_preview_loads_structured_markdown_blocks(tmp_path: Path) -> None:
    detail_path = tmp_path / "detail.md"
    detail_path.write_text(
        "# Runbook\n\n- capture logs\n- compare outputs\n\n> note for handoff\n\n```text\nhello\nworld\n```\n",
        encoding="utf-8",
    )

    preview = load_detail_preview(str(detail_path))

    assert preview.status == "rendered"
    assert [block.kind for block in preview.blocks] == ["heading", "list", "quote", "code"]
    assert preview.blocks[0].text == "Runbook"
    assert preview.blocks[1].items == ("capture logs", "compare outputs")
    assert preview.blocks[2].text == "note for handoff"
    assert preview.blocks[3].text == "hello\nworld"


def test_dashboard_pagination_helpers_clamp_inputs_and_build_gap_links() -> None:
    tasks = [{"id": f"task-{index}"} for index in range(25)]

    assert parse_page_number(None) == 1
    assert parse_page_number("0") == 1
    assert parse_page_number("bad-input") == 1
    assert page_for_task(tasks, "task-14", per_page=12) == 2

    paged, snapshot = paginate_items(
        list(range(25)),
        page=5,
        per_page=2,
        href_builder=lambda page_number: f"/tasks?page={page_number}",
    )

    assert paged == [8, 9]
    assert snapshot.page == 5
    assert snapshot.page_count == 13
    assert snapshot.prev_href == "/tasks?page=4"
    assert snapshot.next_href == "/tasks?page=6"
    assert [link.label for link in snapshot.page_links] == ["1", "2", "...", "4", "5", "6", "...", "12", "13"]
    assert snapshot.page_links[4].is_current is True


def test_dashboard_formatting_helpers_preserve_dashboard_copy_contract() -> None:
    now_value = parse_timestamp("2026-03-20T12:00:00Z")

    assert optional_display_text("line one\\nline two") == "line one\nline two"
    assert optional_display_text("line one\r\nline two") == "line one\nline two"
    assert format_timestamp("2026-03-20T12:00:00Z", fallback="unknown") == "2026-03-20 12:00 UTC"
    assert format_timestamp("", fallback="unknown") == "unknown"
    assert is_overdue("2026-03-19T10:00:00Z", now_value) is True
    assert is_overdue("2026-03-21T10:00:00Z", now_value) is False


def test_dashboard_task_display_helpers_preserve_locale_detail_and_timeline_contract(
    tmp_path: Path,
) -> None:
    store = TaskStore(tmp_path)
    store.ensure_dirs()

    job = store.create_job(title="job-a")
    task = store.create_task(
        job_id=job["id"],
        requirement="line one\\nline two",
        assigned_agent="quality-agent",
    )
    store.update_task(
        task["id"],
        job_id=job["id"],
        state="blocked",
        result="result line 1\\nresult line 2",
    )

    detail_path = Path(task["detail_path"])
    detail_path.write_text("# 细节\n\n- 第一项\n", encoding="utf-8")

    record = store.load_task(task["id"], job_id=job["id"])
    record["createdAt"] = "2026-03-20T12:00:00Z"
    record["updatedAt"] = "2026-03-20T12:05:00Z"
    record["_scheduler"]["last_dispatch_at"] = "2026-03-20T12:10:00Z"
    record["_scheduler"]["final_notified_at"] = "2026-03-20T12:20:00Z"
    record["_scheduler"]["leader_followup_due_at"] = "2026-03-20T12:30:00Z"
    record["_scheduler"]["leader_followup_sent_at"] = "2026-03-20T12:40:00Z"
    store.save_task(record)

    service = DashboardQueryService(tmp_path, locale="zh-CN")
    assembler = TaskDisplayQueryAssembler(service)
    loaded = service.store.load_task(task["id"], job_id=job["id"])

    recent = assembler.build_recent_update(loaded)
    detail = assembler.build_task_detail(
        loaded,
        selected_job_id=job["id"],
        back_links=[DetailBackLink(label="返回", href="/tasks#tasks-registry")],
        job_href=f"/jobs?job={job['id']}&task={task['id']}#job-task-detail",
    )

    assert recent.summary_label == "结果"
    assert recent.summary_text == "result line 1\nresult line 2"
    assert recent.detail_href == f"/jobs?job={job['id']}&task={task['id']}&lang=zh-CN#job-task-detail"
    assert detail.detail_status_label == "预览可用"
    assert detail.requirement == "line one\nline two"
    assert detail.result == "result line 1\nresult line 2"
    assert [event.key for event in detail.timeline] == [
        "created",
        "updated",
        "dispatch",
        "final-notified",
        "followup-due",
        "followup-sent",
    ]
    assert detail.timeline[0].title == "Task 已创建"
    assert "结果：result line 1\nresult line 2" in detail.timeline[1].note
    assert detail.back_links[0].href == "/tasks#tasks-registry"


def test_dashboard_jobs_query_derives_read_only_timeline_from_existing_job_task_facts(
    tmp_path: Path,
) -> None:
    store = TaskStore(tmp_path)
    store.ensure_dirs()

    job = store.create_job(title="timeline-job")
    task = store.create_task(
        job_id=job["id"],
        requirement="timeline requirement",
        assigned_agent="quality-agent",
    )
    store.update_task(
        task["id"],
        job_id=job["id"],
        state="blocked",
        result="waiting on external input",
    )

    job_record = store.load_job(job["id"])
    job_record["createdAt"] = "2026-03-20T12:00:00Z"
    job_record["updatedAt"] = "2026-03-20T12:45:00Z"
    store.save_job(job_record)

    task_record = store.load_task(task["id"], job_id=job["id"])
    task_record["createdAt"] = "2026-03-20T12:05:00Z"
    task_record["updatedAt"] = "2026-03-20T12:15:00Z"
    task_record["_scheduler"]["last_dispatch_at"] = "2026-03-20T12:20:00Z"
    task_record["_scheduler"]["final_notified_at"] = "2026-03-20T12:30:00Z"
    task_record["_scheduler"]["leader_followup_due_at"] = "2026-03-20T12:40:00Z"
    task_record["_scheduler"]["leader_followup_sent_at"] = "2026-03-20T12:50:00Z"
    store.save_task(task_record)

    snapshot = DashboardQueryService(tmp_path).jobs(selected_job_id=job["id"])

    assert snapshot.selected_job is not None
    assert [event.key for event in snapshot.selected_job.timeline] == [
        "created",
        "task-activity",
        "dispatch",
        "final-notified",
        "followup-due",
        "followup-sent",
    ]
    assert snapshot.selected_job.timeline[0].title == "Job created"
    assert snapshot.selected_job.timeline[1].title == "Latest task activity"
    assert task["id"] in snapshot.selected_job.timeline[1].note
    assert "quality-agent" in snapshot.selected_job.timeline[2].note
    assert "team-leader" in snapshot.selected_job.timeline[3].note
    assert task["id"] in snapshot.selected_job.timeline[4].note
