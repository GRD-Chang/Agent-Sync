# OpenClaw Multi-Agent Orchestration for Codex

> Build an OpenClaw multi-agent development team that can actually deliver, and fix both the state-loss problem and workflow breakage that appear when agents orchestrate tools like Codex.

[English](README.en.md) | [中文](README.md)

`task-bridge` is a local-first, lightweight task coordination system built for OpenClaw multi-agent collaboration. Its core mission is straightforward: let an OpenClaw-built agent team reliably orchestrate lower-level execution engines such as Codex or Claude Code to complete real long-running development work.

---

## Dashboard Preview (Global Control)

Turn local Jobs, Tasks, Worker Queue, Alerts, and Health into a visual dashboard with one command:

```bash
task-bridge dashboard
```

As a human operator or Team Leader, you can use the dashboard to monitor the whole team in real time. Below are examples of the overview page and the job detail page:

| Dashboard overview | Dashboard job detail |
|---|---|
| ![Dashboard overview](docs/assets/dashboard/overview.png) | ![Dashboard job detail](docs/assets/dashboard/job_detail.png) |
| **Bird's-eye view**: inspect task-state distribution, agent queue activity, and system health. | **Execution focus**: drill into one job to review the dispatch timeline, task breakdown, and current blockers. |

| Task detail | Bilingual support |
|---|---|
| ![Dashboard task detail](docs/assets/dashboard/task_detail.png) | ![Dashboard job list](docs/assets/dashboard/job_list.png) |
| **Execution evidence**: inspect the event timeline, latest result summary, and attached Markdown execution details in one place. | **Full visibility**: quickly tell which jobs are still moving and which ones have converged. Supports English/Chinese UI and local font switching. |

---

## Why Existing Approaches Break

When you try to assemble an agent team with OpenClaw, the hardest problem is usually not the lack of agents. The real problem is that **agents struggle to keep long-running development work under control**.

While integrating OpenClaw with lower-level engines such as Codex, people usually try one of two mainstream approaches. In real engineering workflows, both can cause catastrophic orchestration breakage:

### 1. Direct ACP Invocation

- **Approach**: the Team Leader breaks work down and sends it to a Code Agent, which directly wakes Codex through commands such as `sessions_spawn(acp)`.
- **Why it breaks**: on IM platforms such as Feishu that do not support long-lived streaming, `sessions_spawn` typically becomes asynchronous. The Code Agent sends the wake-up command and immediately assumes its own work is finished, then reports back to the Leader with "task completed" before Codex has even finished reading the codebase. Once "task started" is treated as "task finished," the Leader can move into review or dispatch the next step far too early, and the multi-agent workflow collapses right at the start.

### 2. Relying on a Coding-Agent Skill

- **Approach**: attach a dedicated coding-agent skill to the Worker Agent and let it drive Codex directly through a long-running chat session.
- **Why it breaks**: real engineering tasks often require tens of minutes of context retrieval, code generation, and iterative correction. A Code Agent built on top of an LLM chat loop can rarely track such a long lifecycle reliably within one session. If you depend on heartbeats or cron, the control loop is usually still too fragile. The worst-case outcome is brutal: Codex quietly finishes the work, but the Code Agent has already timed out or disappeared. No one verifies the result, no one writes back the terminal state, and no one notifies the Leader. The execution layer is done, while orchestration is permanently stalled.

---

## The Task Bridge Solution

`task-bridge` abandons the idea that long-running work should be carried by transient chat state, and rebuilds the flow as a minimal local task state machine:

- **Local persisted source of truth**: instead of relying on fragile chat history, every Job, Task, and State is stored locally as JSON.
- **Serial execution with controlled async behavior**: one Worker handles only one task at a time, and it must keep writing back execution records so asynchronous work becomes a stable, traceable task flow.
- **Periodic anti-stall progress nudges**: the daemon periodically reminds Workers to keep moving, preventing silent hangs.
- **Precise terminal notifications with automated follow-up**: the Leader is only woken when a task truly reaches `done`, `blocked`, or `failed`, and unattended terminal tasks can trigger an automatic follow-up reminder so the pipeline does not stall.

---

## A Complete Agent Team

The system introduces a specialized agent team that covers the full software-delivery lifecycle. Under `task-bridge`, responsibilities stay clear:

- **Team Leader (Commander)**: focuses on requirement decomposition, overall coordination, and dispatching high-level Jobs in chat.
- **Planning Agent (Architect)**: owns system design, technical choices, and detailed workflow/Task planning.
- **Code Agent (Programmer)**: accepts work, reports status, and drives the lower-level engine (Codex / Claude Code) to make concrete code changes.
- **Quality Agent (QA)**: handles code quality checks, test writing and execution, bug fixing, and regression validation.
- **Release Agent (Release Manager)**: owns documentation, version control, packaging, and deployment orchestration.
- **Task Bridge (Task Hub)**: the invisible backbone that persists state, dispatches serially, and sends terminal-state notifications.

### Operating Model

```text
User --> [Team Leader] --planning--> [Planning Agent]
             |                           |
      (create / break down Jobs & Tasks) |
             |                           |
             v                           v
     ================ [Task Bridge Daemon] ================
     | (core hub: monitors the queue in the background and |
     |  dispatches work to idle Workers)                  |
     ======================================================
             |                           |
        (dispatch wake-up)          (dispatch wake-up)
             v                           v
       [Code Agent] <---collab---> [Quality Agent] ---> [Release Agent]
     (drive Codex coding)          (testing and review)   (docs and release)
             |                           |
             +------(write-backs and terminal notices)----+
```

---

## Quick Start (Human View)

As a human user, you do not need to manage tasks manually through a long list of CLI commands. Configure the environment, start the daemon, and then just talk to the Team Leader.

### 1. Configure and Install

You need to load the Agent prompts and Skills from this repository into OpenClaw, and install `task-bridge` into the environment your agents can execute:

```bash
# Run the minimum install from the repository root
python -m pip install -e .
```

*(Note: if you change `pyproject.toml` or the console entry point, run this command again.)*

**Best practice: let AI configure it for you**

Hand the setup documents to OpenClaw `default-agent` or Claude Code:

- Chinese setup guide: `docs/zh/openclaw-agent-setup.md`
- English setup guide: `docs/en/openclaw-agent-setup.md`

### 2. Start the Task Bridge Daemon (Background Supervisor)

Once setup is done, keep the task hub running in the background:

```bash
task-bridge daemon --poll-seconds 10 --worker-reminder-seconds 900 --leader-reminder-seconds 3600
```

**Parameter notes:**

- `--poll-seconds 10`: queue polling interval. Default: 10 seconds.
- `--worker-reminder-seconds 900`: anti-stall reminder interval for Workers. Default: 15 minutes. If progress is not updated in time, the Worker is nudged to continue.
- `--leader-reminder-seconds 3600`: reminder interval for the Leader on long-running work. Default: 60 minutes. This prevents the Leader from losing awareness of execution status.
- `--leader-followup 300`: terminal-task follow-up window. Default: 5 minutes. Use `0` to disable it. If a terminal result arrives and no new task is created for too long, Bridge merges the situation into one reminder and nudges the Leader for a next-step decision.

**Persistent run (`nohup`)**:

```bash
mkdir -p .task-bridge
nohup task-bridge daemon \
  --poll-seconds 60 \
  --worker-reminder-seconds 900 \
  --leader-reminder-seconds 7200 \
  --leader-followup 1800 \
  > .task-bridge/daemon.log 2>&1 &
echo $! > .task-bridge/daemon.pid
```

*(Stop it with `kill "$(cat .task-bridge/daemon.pid)"`)*

### 3. Launch the Dashboard (Read-only, Optional)

```bash
# Default bind: 127.0.0.1:8000
task-bridge dashboard

# Or specify host and port
task-bridge dashboard --host 127.0.0.1 --port 8000
```

*Note: the dashboard only reads local data and exposes no write operations. It is suitable for auditing, blocker inspection, and daily checks.*

### 4. Give the Team Leader a Requirement

In your IM tool (such as Feishu) or in a terminal session, talk directly to the **Team Leader**:

> "We need to build a Python CLI tool with user authentication and 80% test coverage. Let the Planning Agent produce the plan first, then let the Code Agent start implementation."

From there, the Team Leader will break the work down automatically, and the daemon will wake each agent in sequence until the work is delivered.

---

## Extra Material: CLI Toolbox (For Agents / Debugging)

> **Note**: the commands below are primarily meant for agents to call in the background, such as when they write back progress. Human operators usually do not need them except for debugging or forced intervention.

### Common Debug Commands

```bash
# Inspect queue and status
task-bridge list-tasks --json
task-bridge worker-status --json
task-bridge queue code-agent --json

# Run one dispatch cycle without starting the daemon
task-bridge dispatch-once --json
```

### Local Data Model

The task structure is explicit and easy to inspect under `~/.openclaw/task-bridge/`:

```text
jobs/<job_id>/
  |- job.json            # Full work topic
  |- tasks/
  |  \- <task_id>.json   # Smallest executable unit
  \- artifacts/
     \- <task_id>/
        \- detail.md     # Optional full execution details; included automatically in terminal notifications
```

### Core Commands

| Category | Commands | Description |
|------|------|------|
| **Task orchestration** | `create-job`, `list-jobs`, `show-job`, `use-job`, `current-job` | Manage high-level work topics (used by the Leader) |
| **Task management** | `create-task`, `list-tasks`, `show-task`, `update-task`, `delete-task` | Manage concrete execution steps |
| **Worker state** | `claim`, `start`, `update-result`, `complete`, `block`, `fail` | Workers write back progress and terminal states (used by multiple agents) |
| **Bridge scheduling** | `worker-status`, `queue`, `dispatch-once`, `notify`, `daemon` | Dispatching and system supervision |

---

## Environment Variables and Advanced Configuration

The system automatically reads variables from the current working directory `.env` or `~/.openclaw/.env`:

- `TASK_BRIDGE_USER_CHAT_ID`: the user `chat_id` injected into notification prompts. The notification chain depends on it.

The variables below must be injected explicitly through your shell or command prefix:

- `TASK_BRIDGE_HOME`: custom data directory. Default: `~/.openclaw/task-bridge`.
- `TASK_BRIDGE_CAPTURE_FILE`: intercept outbound sends and write them to a file. Useful for isolated end-to-end tests.
- `TASK_BRIDGE_DASHBOARD_SSH_TARGET`: override the SSH target shown in dashboard launch guidance without changing the actual bind address.

---

## Reference Guides

To fit this workflow cleanly into your environment, see:

- [OpenClaw Agent Setup (Chinese)](docs/zh/openclaw-agent-setup.md)
- [OpenClaw Agent Workflow Guide (Chinese)](docs/zh/openclaw-agent-flow.md)
- [OpenClaw Agent Setup (English)](docs/en/openclaw-agent-setup.md)
- [OpenClaw Agent Workflow Guide (English)](docs/en/openclaw-agent-flow.md)

---

### Development and Testing Guide

```bash
# 1. Run from source without relying on PATH
PYTHONPATH=src python -m task_bridge create-job --title "Dev task"

# 2. Run Python tests
python -m pip install -e .[test] pytest
python -m pytest -q

# 3. Run Dashboard Playwright tests
npm install
npm run playwright:install
npm run test:playwright
```

> **Task Bridge philosophy**: this is not an all-in-one platform. It is a minimal task bridge. Its real value is that it keeps your agent team from going out of sync and makes AI collaboration actually run end to end. How you design prompts, and how you plug in traditional script workers, remains fully open to you.
