from __future__ import annotations

from pathlib import Path

from task_bridge.dashboard.detail_preview import load_detail_preview
from task_bridge.dashboard.formatting import (
    format_timestamp,
    is_overdue,
    optional_display_text,
    parse_timestamp,
)
from task_bridge.dashboard.pagination import page_for_task, paginate_items, parse_page_number


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
