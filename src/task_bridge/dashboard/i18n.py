from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE = "en"

_CATALOGS: dict[str, dict[str, Any]] = {
    "en": {
        "html_lang": "en",
        "nav": {
            "overview": "Overview",
            "jobs": "Jobs",
            "tasks": "Tasks",
            "worker-queue": "Worker & Queue",
            "alerts": "Alerts",
            "health": "Health",
        },
        "shell": {
            "skip_link": "Skip to content",
            "eyebrow": "task-bridge / read-only dispatch wall",
            "title": "Dashboard foundation",
            "note": "Built on the existing job/task JSON store, worker queue semantics, and daemon state model.",
            "scope_label": "MVP scope",
            "scope_note": "Overview is live. The other primary destinations are shell-ready and intentionally read-only.",
            "primary_nav_label": "Primary",
        },
        "common": {
            "unknown": "Unknown",
            "none": "None",
        },
        "overview": {
            "eyebrow": "Overview",
            "title": "Live dispatch posture for the current task bridge.",
            "intro": "This page stays read-only and reports only what already exists in the local task-bridge store: task states, worker utilization, queue depth, and recent task updates.",
            "stats_label": "Overview framing",
            "current_job": "Current job",
            "current_job_empty": "None selected",
            "jobs_tracked": "Jobs tracked",
            "tasks_tracked": "Tasks tracked",
            "generated_at": "Generated",
            "store_home": "Store home",
            "task_states_eyebrow": "Task states",
            "task_states_title": "Task status summary",
            "workers_eyebrow": "Workers",
            "workers_title": "Worker utilization summary",
            "busy_total": "Busy / total",
            "busy_note": "{idle_workers} idle workers remain available.",
            "queued_tasks": "Queued tasks",
            "queued_note": "Counted from existing per-agent queue semantics.",
            "terminal_tasks": "Terminal tasks",
            "terminal_note": "Derived from done / blocked / failed task states.",
            "worker_list_label": "Worker lanes",
            "worker_running": "Running",
            "worker_queued": "Queued",
            "worker_head_of_line": "Head of line",
            "no_workers_title": "No worker lanes yet",
            "no_workers_body": "Worker snapshots will appear after tasks are assigned to agents in the existing store.",
            "activity_eyebrow": "Activity",
            "activity_title": "Recent updates",
            "empty_title": "No jobs or tasks yet",
            "empty_body": "The dashboard is connected and readable, but the store is currently empty. Create a job and tasks through `task-bridge` to populate the dispatch wall.",
            "no_recent_title": "No recent updates available",
            "no_recent_body": "Tasks exist, but none expose a recent update summary yet.",
            "error_title": "Overview unavailable",
            "error_body": "The navigation shell is still available, but the Overview payload could not be built from the local store.",
            "error_label": "Store read failed",
        },
        "placeholder": {
            "shell_heading": "{page_title} shell is ready.",
            "boundary_eyebrow": "Read-only boundary",
            "boundary_title": "MVP boundary",
            "boundary_body": "No write controls, no speculative metrics, and no extra domain fields are introduced in this slice.",
            "copy": {
                "jobs": "Job browsing is deferred. Any later live data must remain read-only and tied to the existing job.json records.",
                "tasks": "Task browsing is deferred. Any later live data must remain read-only and tied to the existing task JSON contract.",
                "worker-queue": "Worker lanes and queue drill-down are deferred. Any later live data must remain tied to the existing per-agent queue semantics.",
                "alerts": "Alert summaries are deferred. Current MVP only exposes terminal-state and follow-up semantics indirectly through Overview facts.",
                "health": "Health drill-down is deferred. Current MVP health evidence is limited to successful Overview rendering versus unreadable-store failure handling.",
            },
        },
        "status": {
            "queued": {"label": "Queued", "description": "Awaiting dispatch"},
            "running": {"label": "Running", "description": "Currently in progress"},
            "done": {"label": "Done", "description": "Closed successfully"},
            "blocked": {"label": "Blocked", "description": "Needs intervention"},
            "failed": {"label": "Failed", "description": "Closed with failure"},
        },
        "recent_update": {
            "result": "Result",
            "requirement": "Requirement",
            "update": "Update",
            "no_detail": "No detail recorded yet.",
            "unassigned": "unassigned",
        },
    }
}


def get_messages(locale: str = DEFAULT_LOCALE) -> Mapping[str, Any]:
    return _CATALOGS.get(locale, _CATALOGS[DEFAULT_LOCALE])
