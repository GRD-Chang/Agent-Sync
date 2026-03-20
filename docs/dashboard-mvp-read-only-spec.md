## Execution Spec Patch: Agent-Sync dashboard MVP（只读版）

This freeze is anchored to the current dashboard evidence in `src/task_bridge/dashboard/app.py`, `src/task_bridge/dashboard/templates/`, `src/task_bridge/dashboard/queries.py`, `tests/test_dashboard.py`, and `tests/playwright/dashboard.smoke.spec.js`.

### Frozen Scope
- Dashboard MVP remains a read-only web surface over the existing local `task-bridge` store and queue semantics. It may only read facts already represented by `job.json`, task JSON, worker queue derivation, and daemon-readable state; it must not add new persistence, mutation endpoints, background jobs, or daemon control paths.
- Primary routes are frozen for MVP: `/overview`, `/jobs`, `/tasks`, `/worker-queue`, `/alerts`, `/health`.
- `/overview` is the only live data page in MVP v1. `/jobs`, `/tasks`, `/worker-queue`, `/alerts`, and `/health` stay shell-only until a later spec update explicitly promotes them.
- Overview data is limited to facts already derivable from the current query layer: current job id, job count, task count, generated timestamp, store home path, core task-state counts (`queued`, `running`, `done`, `blocked`, `failed`), worker utilization / queue snapshots, and recent task updates derived from existing task fields.
- Read-only error handling is in scope. If the store is unreadable, the dashboard keeps the navigation shell and renders an explicit overview error state instead of failing CLI startup or hiding the shell.
- Out of scope unless a future spec explicitly reopens scope: create/update/delete actions, status transitions, claim/start/complete/block/fail controls, queue reordering, bulk actions, search/filter/sort/pagination, auth, per-user settings, live push/polling, charts, exports, alert rule configuration, and daemon lifecycle controls.

### Per-page Boundary Table
- Overview
  - Must include: a read-only overview shell; current job id, jobs tracked, tasks tracked, generated timestamp, and store home; task status summary for `queued`, `running`, `done`, `blocked`, `failed`; worker utilization summary; per-worker lane snapshot; recent updates; explicit empty state; explicit unreadable-store error state that preserves primary navigation.
  - Must not include: any write control; job/task edit or transition actions; drill-down that invents new detail models; metrics not derivable from the existing store; auto-refresh, websocket streaming, charts, or speculative KPIs.
- Jobs
  - Must include: mounted route at `/jobs`; page identity and active-nav state; explicit boundary copy that job browsing is deferred and any later live data must stay read-only and tied to existing `job.json` records.
  - Must not include: job table, job detail drawer, current-job switching, create/edit/delete actions, progress formulas not already defined in repo code, filters/search/sort/pagination, or export.
- Tasks
  - Must include: mounted route at `/tasks`; page identity and active-nav state; explicit boundary copy that task browsing is deferred and any later live data must stay read-only and tied to the existing task JSON contract.
  - Must not include: task detail editor, status transition buttons, result or `detail_path` editing, reassignment, bulk actions, filters/search/sort/pagination, or log tailing.
- Worker & Queue
  - Must include: mounted route at `/worker-queue`; page identity and active-nav state; explicit boundary copy that worker lanes and queue drill-down are deferred and any later live data must stay tied to existing per-agent queue semantics.
  - Must not include: dispatch/reset buttons, queue reordering, worker claim/reassign controls, daemon controls, throughput/SLA charts, or any synthetic capacity metric not already derivable from current store state.
- Alerts
  - Must include: mounted route at `/alerts`; page identity and active-nav state; explicit boundary copy that alert summaries are deferred and current MVP only exposes terminal-state / follow-up semantics indirectly through overview facts.
  - Must not include: alert inbox, notification replay, acknowledge/snooze flows, rule configuration, badge counters backed by new data sources, websockets, or toast centers.
- Health
  - Must include: mounted route at `/health`; page identity and active-nav state; explicit boundary copy that daemon/store health drill-down is deferred, and current MVP health evidence is limited to successful overview rendering versus unreadable-store failure handling.
  - Must not include: daemon start/stop/restart, filesystem repair tools, arbitrary host metrics, log viewers, or write-side diagnostics.

### i18n MVP Contract
- MVP ships one consistent default UI locale across nav labels, page titles, placeholder copy, empty states, error states, and Playwright assertions. Mixed-language top-level UI on the same page is a reject unless the text is a literal CLI command, route, field name, or state id shown in code formatting.
- Current repo evidence baseline is English-only dashboard templates and browser smoke. A future localization slice may switch the dashboard UI to Simplified Chinese, but it must convert all shipped dashboard pages and browser assertions together in the same change; partial translation is not acceptable.
- Runtime locale switchers, browser-language negotiation, translation catalogs, per-user locale preference, and pluralization infrastructure are out of scope for the read-only MVP.
- Internal identifiers stay stable and untranslated: route paths, JSON keys, CLI command names, task state ids, and stable selectors.

### Selector / Playwright Contract
- Any future slice that touches dashboard templates must add and preserve stable `data-testid` hooks. Do not rely only on visible text or CSS classes for smoke coverage, except when the test is explicitly verifying copy or locale behavior.
- Selector naming scheme is frozen as `dashboard-<page>-<element>`.
- Minimum cross-page stable hooks: `dashboard-shell`, `dashboard-primary-nav`, `dashboard-nav-overview`, `dashboard-nav-jobs`, `dashboard-nav-tasks`, `dashboard-nav-worker-queue`, `dashboard-nav-alerts`, `dashboard-nav-health`, `dashboard-page-title`, and `dashboard-boundary-note`.
- Minimum overview hooks: `dashboard-overview-hero`, `dashboard-overview-task-status`, `dashboard-overview-worker-utilization`, `dashboard-overview-worker-list`, `dashboard-overview-recent-updates`, `dashboard-overview-empty-state`, and `dashboard-overview-error-state`.
- Minimum placeholder hooks while pages remain shell-only: `dashboard-jobs-shell`, `dashboard-tasks-shell`, `dashboard-worker-queue-shell`, `dashboard-alerts-shell`, and `dashboard-health-shell`.
- Read-only smoke matrix is frozen as follows: `/` redirects to `/overview`; primary nav renders all six destinations; overview covers the happy path, empty-store state, and unreadable-store `500` shell; each placeholder route returns `200`, marks the correct nav item active, shows the boundary note, and exposes no write controls.
- When a placeholder page becomes live in a later approved slice, that same change must update selectors, expand Playwright coverage, and amend this spec instead of silently widening behavior.

### Regression Gate Contract
- A dashboard-affecting slice is not done until `task-bridge -h` succeeds and still lists the baseline CLI commands without pulling dashboard web dependencies into plain CLI startup.
- Lazy import protection stays mandatory: `tests/test_cli.py` must continue proving that importing `task_bridge.cli` or `task_bridge.dashboard` does not eagerly load `task_bridge.dashboard.app`.
- Isolated-home smoke stays mandatory: `TASK_BRIDGE_HOME=/tmp/task-bridge-smoke-<marker> task-bridge create-job --title "smoke test"` must succeed without touching the default task-bridge home.
- Dashboard help/query expectations stay mandatory: `task-bridge dashboard -h` and `tests/test_dashboard.py` must continue to pass for the read-only shell.
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
This dashboard slice must comply with docs/dashboard-mvp-read-only-spec.md. State explicitly which page(s) from the Per-page Boundary Table are in scope, keep every other page frozen at its documented boundary, and do not add write actions, new persistence, or background refresh behavior unless this spec is updated in the same change. Keep the shipped UI locale consistent per the i18n MVP Contract, add or preserve stable dashboard data-testid selectors for any touched template, update Playwright smoke coverage in the same slice when a page boundary changes, pass the Regression Gate Contract, and end with clean git status plus .gitignore coverage for any new local artifacts.
```
