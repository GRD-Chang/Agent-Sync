## Execution Spec Patch: Agent-Sync dashboard MVP（只读版）

This reconciliation patch is anchored to the current dashboard evidence in `src/task_bridge/dashboard/app.py`, `src/task_bridge/dashboard/templates/`, `src/task_bridge/dashboard/queries.py`, `tests/test_dashboard.py`, and `tests/playwright/dashboard.smoke.spec.js`.

### Frozen Scope
- Dashboard MVP remains a read-only web surface over the existing local `task-bridge` store and queue semantics. It may only read facts already represented by `job.json`, task JSON, worker queue derivation, and daemon-readable state; it must not add new persistence, mutation endpoints, background jobs, or daemon control paths.
- Primary routes are frozen for MVP: `/overview`, `/jobs`, `/tasks`, `/worker-queue`, `/alerts`, `/health`.
- All six primary routes are live read-only pages in the reconciled MVP.
- `/worker-queue`, `/alerts`, and `/health` are live only within their base scope: summary + evidence views derived from existing store / queue / daemon facts, with no new models or write controls.
- Overview data is limited to facts already derivable from the current query layer: current job id, job count, task count, generated timestamp, store home path, core task-state counts (`queued`, `running`, `done`, `blocked`, `failed`), worker utilization / queue snapshots, and recent task updates derived from existing task fields.
- Read-only error handling is in scope. If store or daemon data is unreadable, the dashboard keeps the navigation shell and renders an explicit live-page error or warning state instead of failing CLI startup or hiding the shell.
- Out of scope unless a future spec explicitly reopens scope: create/update/delete actions, status transitions, claim/start/complete/block/fail controls, queue reordering, bulk actions, search/sort/pagination, auth, per-user settings, live push/polling, charts, exports, alert rule configuration, and daemon lifecycle controls.
- Read-only query-string filter / view chips are allowed on `/jobs` and `/tasks` only when they are derived entirely from existing store facts and do not introduce mutation paths, new persistence, or background refresh behavior.

### Per-page Boundary Table
- Overview
  - Must include: a read-only overview shell; current job id, jobs tracked, tasks tracked, generated timestamp, and store home; task status summary for `queued`, `running`, `done`, `blocked`, `failed`; worker utilization summary; per-worker lane snapshot; recent updates; explicit empty state; explicit unreadable-store error state that preserves primary navigation.
  - Must not include: any write control; job/task edit or transition actions; drill-down that invents new detail models; metrics not derivable from the existing store; auto-refresh, websocket streaming, charts, or speculative KPIs.
- Jobs
  - Must include: mounted route at `/jobs`; page identity and active-nav state; read-only job list/detail skeletons tied only to existing `job.json` records and task JSON facts; a query-string detail entry path; optional read-only job-slice chips limited to existing current/open/terminal facts; explicit empty state; stable selectors for list/detail coverage; task preview links that remain read-only; a focused job-context task-detail transition that replaces, rather than stacks under, the selected job detail when `task=<task_id>` is present; and, for the selected current job only, a read-only in-page subview switch between grouped task cards and the existing `~/.openclaw/agents/team-leader/memory/work-plan.md` preview.
  - Must not include: current-job switching, create/edit/delete actions, queue or priority mutation, progress formulas not already defined in repo code, search/sort/pagination controls, or export.
- Tasks
  - Must include: mounted route at `/tasks`; page identity and active-nav state; read-only task list/detail skeletons tied only to the existing task JSON contract; a query-string detail entry path; optional read-only filter chips limited to existing `job_id`, task state, and `assigned_agent` facts; read-only `detail.md` preview placeholder / controlled rendering; a minimal timeline framework derived only from existing task timestamps and `_scheduler` timestamps; explicit empty state; and stable selectors for list/detail/preview/timeline coverage.
  - Must not include: task detail editor, status transition buttons, result or `detail_path` editing, reassignment, bulk actions, search/sort/pagination controls, log tailing, or any new event/state model beyond existing store facts.
- Worker & Queue
  - Must include: mounted route at `/worker-queue`; page identity and active-nav state; current job id, generated timestamp, workers tracked, and store home; worker occupancy summary (`running_tasks`, `busy_workers`, `assigned_queue_depth`, `unassigned_queue_depth`); per-agent lane snapshots derived only from existing queue semantics; queued-task coverage for unassigned tasks; an explicit no-activity empty state; and stable selectors for hero/summary/lane/unassigned coverage.
  - Must not include: dispatch/reset buttons, queue reordering, worker claim/reassign controls, daemon controls, throughput/SLA charts, or any synthetic capacity metric not already derivable from current store state.
- Alerts
  - Must include: mounted route at `/alerts`; page identity and active-nav state; current job id, generated timestamp, pending follow-up count, and store home; blocked / failed / overdue follow-up summary derived from existing task JSON and `_scheduler` fields; a blocked/failed risk list; an unresolved leader follow-up list that mirrors runtime gating for the current job's latest terminal task only; an explicit no-alert empty state; and stable selectors for hero/summary/risk/follow-up coverage.
  - Must not include: alert inbox, notification replay, acknowledge/snooze flows, rule configuration, badge counters backed by new data sources, websockets, or toast centers.
- Health
  - Must include: mounted route at `/health`; page identity and active-nav state; current job id, generated timestamp, `daemon_state.json` path, and store home; a summary of jobs tracked, tasks tracked, worker prompt cache entries, and last leader running notice; readable checks derived from existing store / daemon facts; warning states when daemon or record data cannot be read; and stable selectors for hero/summary/check coverage.
  - Must not include: daemon start/stop/restart, filesystem repair tools, arbitrary host metrics, log viewers, or write-side diagnostics.

### i18n MVP Contract
- MVP keeps one consistent UI locale per rendered page across nav labels, page titles, boundary copy, empty states, error states, summary labels, and browser assertions. Mixed-language top-level UI on the same page is a reject unless the text is a literal CLI command, route, field name, file name, agent name, or stable identifier shown from existing data.
- Dashboard now supports explicit read-only bilingual UI switching between English (`en`) and Simplified Chinese (`zh-CN`) through a visible in-page locale switcher backed by the `lang` query parameter. Default routing stays English unless `lang=zh-CN` is requested.
- Any localization slice must convert all shipped dashboard pages and browser assertions together in the same change; partial translation is not acceptable.
- Browser-language negotiation, persisted per-user locale preference, and pluralization infrastructure remain out of scope for the read-only MVP.
- Internal identifiers stay stable and untranslated: route paths, JSON keys, CLI command names, task state ids, and stable selectors.

### Selector / Playwright Contract
- Any future slice that touches dashboard templates must add and preserve stable `data-testid` hooks. Do not rely only on visible text or CSS classes for smoke coverage, except when the test is explicitly verifying copy or locale behavior.
- Selector naming scheme is frozen as `dashboard-<page>-<element>`.
- Minimum cross-page stable hooks: `dashboard-shell`, `dashboard-primary-nav`, `dashboard-nav-overview`, `dashboard-nav-jobs`, `dashboard-nav-tasks`, `dashboard-nav-worker-queue`, `dashboard-nav-alerts`, `dashboard-nav-health`, `dashboard-page-title`, `dashboard-boundary-note`, `dashboard-locale-switch`, `dashboard-locale-en`, and `dashboard-locale-zh-cn`.
- Minimum overview hooks: `dashboard-overview-hero`, `dashboard-overview-task-status`, `dashboard-overview-worker-utilization`, `dashboard-overview-worker-list`, `dashboard-overview-recent-updates`, `dashboard-overview-empty-state`, and `dashboard-overview-error-state`.
- Minimum jobs hooks: `dashboard-jobs-page`, `dashboard-jobs-list`, `dashboard-jobs-detail`, `dashboard-jobs-detail-view-switch`, `dashboard-jobs-work-plan`, and `dashboard-jobs-empty-state`.
- Minimum tasks hooks: `dashboard-tasks-page`, `dashboard-tasks-list`, `dashboard-tasks-detail`, `dashboard-tasks-detail-preview`, `dashboard-tasks-timeline`, and `dashboard-tasks-empty-state`.
- Minimum worker & queue hooks: `dashboard-worker-queue-hero`, `dashboard-worker-queue-summary`, `dashboard-worker-queue-lanes`, `dashboard-worker-queue-unassigned`, and `dashboard-worker-queue-empty-state`.
- Minimum alerts hooks: `dashboard-alerts-hero`, `dashboard-alerts-summary`, `dashboard-alerts-risk-list`, `dashboard-alerts-followups`, and `dashboard-alerts-empty-state`.
- Minimum health hooks: `dashboard-health-hero`, `dashboard-health-summary`, and `dashboard-health-checks`.
- Read-only smoke matrix is frozen as follows: `/` redirects to `/overview`; primary nav renders all six destinations; overview covers the happy path, empty-store state, and unreadable-store `500` shell; jobs covers the live list/detail shell, the job-task-card to focused task-detail transition, the current-job task-card/work-plan subview toggle, and explicit empty-store state; tasks covers the live list/detail shell plus `detail.md` preview / timeline presence and explicit empty-store state; worker & queue covers the live hero/summary/lane/unassigned base page with no write controls; alerts covers the live hero/summary/risk/follow-up base page with no write controls; health covers the live hero/summary/check base page with no write controls.

### Regression Gate Contract
- A dashboard-affecting slice is not done until `task-bridge -h` succeeds and still lists the baseline CLI commands without pulling dashboard web dependencies into plain CLI startup.
- Lazy import protection stays mandatory: `tests/test_cli.py` must continue proving that importing `task_bridge.cli` or `task_bridge.dashboard` does not eagerly load `task_bridge.dashboard.app`.
- Isolated-home smoke stays mandatory: `TASK_BRIDGE_HOME=/tmp/task-bridge-smoke-<marker> task-bridge create-job --title "smoke test"` must succeed without touching the default task-bridge home.
- Dashboard help/query expectations stay mandatory: `task-bridge dashboard -h` and `tests/test_dashboard.py` must continue to pass for the read-only dashboard surface.
- Python regression gate for dashboard slices: `python -m pytest -q` is the preferred full gate; at minimum, the slice owner must run and pass `python -m pytest -q tests/test_cli.py tests/test_dashboard.py`.
- Browser regression gate for dashboard slices: `npx playwright test tests/playwright/dashboard.smoke.spec.js` must pass in a prepared environment. If the browser stack is unavailable locally, the slice is not done until that smoke runs in CI or an equivalent prepared environment.
- Any change that widens dashboard behavior without simultaneously updating the relevant tests, selectors, and this spec is incomplete.

### Repo Hygiene Contract
- Each dashboard slice must end with `.gitignore` reviewed against any new local artifacts it introduced. Existing ignores already cover `.task-bridge/`, `.playwright-browsers/`, `.tmp/`, `node_modules/`, and `test-results/`; new cache or output paths must be added in the same slice before commit.
- Before commit, run `git status --short` and confirm only task-related source, test, doc, or ignore-file changes are present. Unrelated worktree changes must stay untouched and uncommitted.
- Do not commit temporary `TASK_BRIDGE_HOME` directories, Playwright downloads, screenshots, logs, captured notifications, browser traces, or local debug files.
- If validation creates local artifacts, delete them or ensure they are ignored before the slice is considered done.
- Repo hygiene is an acceptance item for every slice, not optional cleanup after the fact.

### Suggested insertion into future task requirements
- Use the following requirement rider in future dashboard slices:

```text
This dashboard slice must comply with docs/dashboard-mvp-read-only-spec.md. State explicitly which page(s) from the Per-page Boundary Table are in scope, keep every other page within its documented read-only boundary, and do not add write actions, new persistence, or background refresh behavior unless this spec is updated in the same change. Keep the shipped UI locale consistent per the i18n MVP Contract, add or preserve stable dashboard data-testid selectors for any touched template, update Playwright smoke coverage in the same slice when a page boundary changes, pass the Regression Gate Contract, and end with clean git status plus .gitignore coverage for any new local artifacts.
```
