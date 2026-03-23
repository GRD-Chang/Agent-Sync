from __future__ import annotations

from pathlib import Path

from task_bridge.dashboard import DashboardQueryService
from task_bridge.dashboard.agent_presentation import resolve_agent_presentation
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


def test_dashboard_agent_presentation_helper_preserves_raw_identity_and_fallbacks() -> None:
    known = resolve_agent_presentation("planning-agent", empty_label="Unassigned")
    extension = resolve_agent_presentation("extension-agent", empty_label="Unassigned")
    unknown = resolve_agent_presentation("unknown-agent", empty_label="Unassigned")
    unassigned = resolve_agent_presentation("", empty_label="Unassigned")

    assert known.raw_key == "planning-agent"
    assert known.display_label == "planning-agent"
    assert known.fallback_kind == "explicit-theme"
    assert extension.raw_key == "extension-agent"
    assert extension.display_label == "extension-agent"
    assert extension.fallback_kind == "default-theme"
    assert unknown.raw_key == "unknown-agent"
    assert unknown.display_label == "unknown-agent"
    assert unknown.fallback_kind == "default-theme"
    assert unassigned.raw_key is None
    assert unassigned.display_label == "Unassigned"
    assert unassigned.fallback_kind == "unassigned"


def test_dashboard_agent_presentation_helper_keeps_locale_safe_empty_label_out_of_raw_identity() -> None:
    localized_unassigned = resolve_agent_presentation(None, empty_label="未分配")
    extension = resolve_agent_presentation("extension-agent", empty_label="未分配")

    assert localized_unassigned.raw_key is None
    assert localized_unassigned.display_label == "未分配"
    assert localized_unassigned.fallback_kind == "unassigned"
    assert extension.raw_key == "extension-agent"
    assert extension.display_label == "extension-agent"
    assert extension.fallback_kind == "default-theme"


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
    assert detail.assigned_agent_raw == "quality-agent"
    assert detail.assigned_agent_fallback_kind == "explicit-theme"


def test_dashboard_jobs_query_builds_horizontal_dispatch_timeline_nodes_from_scheduler_dispatches(
    tmp_path: Path,
) -> None:
    store = TaskStore(tmp_path)
    store.ensure_dirs()

    job = store.create_job(title="timeline-job")
    older = store.create_task(
        job_id=job["id"],
        requirement="older timeline requirement",
        assigned_agent="quality-agent",
    )
    newer = store.create_task(
        job_id=job["id"],
        requirement="newer timeline requirement",
        assigned_agent="code-agent",
    )

    older_record = store.load_task(older["id"], job_id=job["id"])
    older_record["createdAt"] = "2026-03-20T12:05:00Z"
    older_record["updatedAt"] = "2026-03-20T12:45:00Z"
    older_record["state"] = "blocked"
    older_record["_scheduler"]["last_dispatch_at"] = "2026-03-20T12:20:00Z"
    store.save_task(older_record)

    newer_record = store.load_task(newer["id"], job_id=job["id"])
    newer_record["createdAt"] = "2026-03-20T12:25:00Z"
    newer_record["updatedAt"] = "2026-03-20T13:25:00Z"
    newer_record["state"] = "running"
    newer_record["_scheduler"]["last_dispatch_at"] = "2026-03-20T13:10:00Z"
    store.save_task(newer_record)

    snapshot = DashboardQueryService(tmp_path).jobs(selected_job_id=job["id"], selected_view="active")

    assert snapshot.selected_job is not None
    timeline = snapshot.selected_job.timeline
    assert [node.task_id for node in timeline] == [older["id"], newer["id"]]
    assert timeline[0].task_short_id.startswith("#")
    assert timeline[0].assigned_agent == "quality-agent"
    assert timeline[0].assigned_agent_raw == "quality-agent"
    assert timeline[0].assigned_agent_fallback_kind == "explicit-theme"
    assert timeline[0].state == "blocked"
    assert timeline[0].state_label == "Blocked"
    assert timeline[0].dispatch_at_iso == "2026-03-20T12:20:00Z"
    assert timeline[0].dispatch_date_display == "03-20"
    assert timeline[0].dispatch_time_display == "12:20 UTC"
    assert timeline[0].detail_href.endswith(
        f"/jobs?job={job['id']}&task={older['id']}&view=active#job-task-detail"
    )
    assert timeline[0].is_newest is False
    assert timeline[1].assigned_agent == "code-agent"
    assert timeline[1].assigned_agent_raw == "code-agent"
    assert timeline[1].assigned_agent_fallback_kind == "explicit-theme"
    assert timeline[1].state_label == "Running"
    assert timeline[1].dispatch_at_iso == "2026-03-20T13:10:00Z"
    assert timeline[1].is_newest is True
