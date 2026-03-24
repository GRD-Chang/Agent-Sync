from __future__ import annotations

from typing import TYPE_CHECKING

from .formatting import format_timestamp as _format_timestamp
from .formatting import format_timestamp_for_client as _format_timestamp_for_client
from .snapshots import HealthCheck, HealthSnapshot

if TYPE_CHECKING:
    from .queries import DashboardQueryService


class HealthPageQueryAssembler:
    def __init__(self, service: DashboardQueryService) -> None:
        self._service = service
        self._messages = service._messages

    def build(self) -> HealthSnapshot:
        messages = self._messages["health"]
        jobs_count, tasks_count, records_status, records_detail = self._build_records_summary()
        (
            worker_prompt_entries,
            leader_last_running_notice_at,
            daemon_status,
            daemon_detail,
            cache_status,
            cache_detail,
        ) = self._build_daemon_summary()
        checks = [
            HealthCheck("store-home", messages["store_home_check"], "ok", self._service.home_path),
            HealthCheck("records", messages["records_check"], records_status, records_detail),
            HealthCheck("daemon-state", messages["daemon_check"], daemon_status, daemon_detail),
            HealthCheck("prompt-cache", messages["cache_check"], cache_status, cache_detail),
        ]
        generated_at = _format_timestamp_for_client(
            self._service._now_provider(),
            fallback=self._messages["common"]["unknown"],
        )
        leader_notice = _format_timestamp_for_client(
            leader_last_running_notice_at or "",
            fallback=messages["leader_last_running_notice_empty"],
        )
        return HealthSnapshot(
            home_path=self._service.home_path,
            current_job_id=self._service.store.get_current_job_id(),
            generated_at=generated_at.display,
            generated_at_iso=generated_at.raw_iso,
            jobs_count=jobs_count,
            tasks_count=tasks_count,
            worker_prompt_entries=worker_prompt_entries,
            leader_last_running_notice_at=leader_notice.display,
            leader_last_running_notice_at_iso=leader_notice.raw_iso,
            checks=checks,
        )

    def _build_records_summary(self) -> tuple[int, int, str, str]:
        messages = self._messages["health"]
        jobs_count = 0
        tasks_count = 0
        records_status = "ok"
        records_detail = messages["records_ok"].format(jobs_count=jobs_count, tasks_count=tasks_count)
        try:
            jobs = self._service.store.list_jobs()
            tasks = self._service.store.list_tasks(all_jobs=True)
            jobs_count = len(jobs)
            tasks_count = len(tasks)
            records_detail = messages["records_ok"].format(jobs_count=jobs_count, tasks_count=tasks_count)
        except Exception:
            records_status = "warn"
            records_detail = messages["records_warn"]
        return jobs_count, tasks_count, records_status, records_detail

    def _build_daemon_summary(self) -> tuple[int, str | None, str, str, str, str]:
        messages = self._messages["health"]
        worker_prompt_entries = 0
        leader_last_running_notice_at: str | None = None
        daemon_status = "ok"
        daemon_detail = messages["daemon_ok_existing"]
        cache_status = "ok"
        cache_detail = messages["cache_ok"].format(
            worker_prompt_entries=worker_prompt_entries,
            leader_last_running_notice_at=messages["leader_last_running_notice_empty"],
        )
        try:
            daemon_exists = self._service.store.daemon_state_path().exists()
            daemon_state = self._service.store.load_daemon_state()
            worker_prompt_entries = len(daemon_state["worker_last_prompt_at"])
            leader_last_running_notice_at = str(daemon_state.get("leader_last_running_notice_at") or "") or None
            leader_last_running_notice_display = _format_timestamp(
                leader_last_running_notice_at or "",
                fallback=messages["leader_last_running_notice_empty"],
            )
            daemon_detail = messages["daemon_ok_existing"] if daemon_exists else messages["daemon_ok_default"]
            cache_detail = messages["cache_ok"].format(
                worker_prompt_entries=worker_prompt_entries,
                leader_last_running_notice_at=leader_last_running_notice_display,
            )
        except Exception:
            daemon_status = "warn"
            cache_status = "warn"
            daemon_detail = messages["daemon_warn"]
            cache_detail = messages["cache_warn"]
            leader_last_running_notice_at = None
        return (
            worker_prompt_entries,
            leader_last_running_notice_at,
            daemon_status,
            daemon_detail,
            cache_status,
            cache_detail,
        )
