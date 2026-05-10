# OpenClaw Agent Workflow Guide

This document helps you quickly understand the `task-bridge` architecture and the collaboration flow between `team-leader`, `planning-agent`, `code-agent`, `quality-agent`, and `release-agent`.

## 1. Why Task Bridge?

In a multi-agent development setup, we usually run into the same problem: once an agent such as `code-agent` is activated for a long-running and complex engineering task, the traditional "state lives in chat history" model breaks down quickly. Agents forget prerequisite steps, asynchronous execution leaves workflows hanging, and tasks fail to close cleanly.

`task-bridge` is designed to solve that exact problem as a **lightweight local task state machine**.

Its core purpose is simple: **turn fragile chat-based collaboration into a traceable, recoverable, queryable local task model (JSON).**

### Core Mechanisms

- **Convert conversations into work items**: organize execution with a `job -> task` hierarchy.
- **Persist facts locally**: store `assigned_agent`, `state`, `requirement`, and `result` in local JSON files.
- **Safe serial dispatching**: ensure one worker handles only one task at a time to avoid workflow collisions.
- **Anti-stall supervision**: a daemon periodically sends dispatch and execution reminders so long-running flows finish end to end.
- **Precise terminal-state callbacks**: only when a task truly reaches a terminal state (`done` / `blocked` / `failed`) does Bridge notify the leader with the outcome.

---

## 2. Roles and Architecture

In this system, collaboration does not happen through direct "talk" between agents. Everything flows through `task-bridge` as the coordination hub.

### Team Leader

- **Role**: task orchestrator. It does not write code directly and does not run engineering commands itself.
- **Responsibilities**:
  - Understand the user's goal, scope, constraints, and priority.
  - Maintain the global execution plan in `memory/work-plan.md`.
  - Break the objective into concrete subtasks (`task`) with clear `requirement` content.
  - Dispatch work through the `task-bridge` CLI to the right executor.
  - Receive terminal-state callbacks from Bridge and decide whether to dispatch follow-up work or deliver the result to the user.

### Worker Agents

- **Role**: stage-specialized execution workers. They accept work and execute it directly inside their own workspace.
- **Responsibilities**:
  - When awakened by the daemon, accept the task and immediately mark it as `running`.
  - First inspect the skills available in the current session. If a skill matches the task goal, scope, acceptance criteria, and verification requirements, use that skill first.
  - Assemble context and directly perform the actual engineering work.
  - **Continuously write back progress**: during execution, keep updating key progress and evidence through `task-bridge update-result`.
  - Verify the outcome, commit changes if needed, and finally mark the task as `done`, `blocked`, or `failed`.
- **Specialization**:
  - `planning-agent`: requirement clarification, solution shaping, sprint contracts, acceptance criteria, and verification requirements.
  - `code-agent`: implementation-level design, implementation, root-cause investigation, bug fixing, and refactoring.
  - `quality-agent`: plan evaluation, implementation evaluation, independent review, QA, and risk grading.
  - `release-agent`: release preparation, deployment, post-deploy verification, and documentation sync.

### Task Bridge Daemon

- **Role**: background supervisor.
- **Responsibilities**: scan the local task pool, dispatch tasks under serial-execution rules, monitor agents that have gone quiet for too long, send reminder nudges, and trigger the exact upward notification when a task is finished.
- **Self-observation**: each loop writes `daemon_heartbeat.json` with pid, timestamp, and `phase_errors`. `daemon-status` can tell whether the daemon is still running and whether the pid file is stale.
- **Failure isolation**: dispatch, reminders, notify, follow-up, and heartbeat run as separate phases. A phase failure is written to `daemon_errors.jsonl`, but it does not kill the whole daemon loop.

---

## 3. Core Objects and Data Flow

All collaboration facts live in a simple file layout:

```text
current_job
daemon.pid
daemon_heartbeat.json
daemon_errors.jsonl
daemon_state.json
jobs/<job_id>/
  ├── job.json            # One broader work topic (for example: build a Todo CLI)
  ├── tasks/
  │   └── <task_id>.json  # Smallest executable unit
  └── artifacts/
      └── <task_id>/
          └── detail.md   # Execution details / logs / evidence
codex-team/
  └── runs/
      └── <run_id>/
          ├── metadata.json
          ├── events.jsonl
          ├── next_action.json
          ├── input.md
          ├── plan.md
          ├── plan_evaluation.md
          └── attempts/
              └── 001/
                  ├── implementation.md
                  └── evaluation.md
```

**Core task state flow (`state`):**
`queued` -> `running` -> `done` / `blocked` / `failed`

- `requirement`: the task contract written by the leader for the worker. It must state intent, scope boundaries, acceptance criteria, and verification requirements; code facts, file locations, and implementation details are filled in by the worker from the repository and task materials.
- `result`: the execution trace and final delivery note written back by the worker.
- `_scheduler`: Bridge-owned scheduling fields, including `awaiting_claim`, `last_dispatch_at`, `last_dispatch_error`, `dispatch_failure_count`, `dispatch_cooldown_until`, `dispatch_blocked`, `final_notified_at`, notification errors, and leader follow-up timestamps.

`codex-team/runs/<run_id>/` is the isolated run store for the Codex Team harness. It reuses `TASK_BRIDGE_HOME`, but it does not map Generator candidate completion onto existing task terminal states such as `done`, `blocked`, or `failed`.

---

## 4. Main Workflow Sequence

The following ASCII sequence diagram shows how a standard long-running task moves through the system:

```text
+-------------+      +---------------+      +--------------+      +--------------------------------------+
| User        |      | team-leader   |      | task-bridge  |      | planning / code / quality / release  |
|             |      |               |      |   (daemon)   |      | OpenClaw worker session              |
+-------------+      +---------------+      +--------------+      +--------------------------------------+
       |                     |                      |                              |
       | 1. Submit a goal    |                      |                              |
       |-------------------->|                      |                              |
       |                     | 2. Plan and split    |                              |
       |                     | 3. create-task       |                              |
       |                     |--------------------->|                              |
       |                     |                      | 4. Persist as queued task    |
       |                     |                      |                              |
       |                     |                      | 5. Find idle worker          |
       |                     |                      | Check budget and cooldown    |
       |                     |                      | Send /reset, then            |
       |                     |                      | [TASK_DISPATCH]              |
       |                     |                      |----------------------------->|
       |                     |                      |                              |
       |                     |                      |      6. start -> running     |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     |                      |      7. Check skills first   |
       |                     |                      |      8. Execute / edit / test|
       |                     |                      |      9. Continuous result    |
       |                     |                      |         updates              |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     |                      | 10. Periodic anti-stall      |
       |                     |                      | reminders                    |
       |                     |                      |----------------------------->|
       |                     |                      |                              |
       |                     |                      |      11. Pass or fail        |
       |                     |                      |      12. Mark terminal state |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     | 13. [Notify] task finished   |
       |                     |<---------------------|                              |
       |                     |                      |                              |
       |                     | 14. Update work plan |                              |
       |                     | 15. Continue or deliver      |
       |<--------------------|                      |                              |
```

---

## 5. Key Constraints and Design Principles

To keep the pipeline from collapsing, the system depends on the following rules:

1. **Single-task rule**: a worker may hold only one `running` task at a time. Concurrent execution on the same worker is not allowed.
2. **State lock**: only tasks in `queued` may have their `requirement` or `assigned_agent` changed.
3. **Safe deletion**: only tasks in `queued` or `done` may be deleted. A failed task must be kept as evidence, and any recovery should happen in a newly created task.
4. **Mandatory write-back**: workers must continuously update `result` through `task-bridge` during execution so progress stays visible.
5. **Skill-first execution**: workers inspect available skills when they receive a task. If a matching skill exists, they use it first. If no skill fits, they use commands and tools directly.
6. **Precise interruption policy**: before a task reaches a terminal state, Bridge must not disturb the leader with intermediate noise.
7. **Budget backoff**: if the OpenClaw process budget is full, dispatch is briefly deferred. This is not a task failure, does not count toward `dispatch_blocked`, and avoids touching a live worker session before `/reset`.
8. **Failure blocking**: only real reset/send failures increment `dispatch_failure_count`. After repeated failures, Bridge sets `dispatch_blocked` so the same task cannot restart the worker forever.
9. **Notification boundary**: `notify_updates()` only handles the current job by default. Historical terminal tasks require explicit `notify-backfill --mark-only` or `notify-backfill --summary`.
10. **Safe tests**: with `TASK_BRIDGE_CAPTURE_FILE` set, Bridge writes messages to JSONL instead of calling OpenClaw, and live OpenClaw process counts do not affect the test.

## 6. One-Sentence Summary

This system is not "the leader constantly watching workers." Instead:

**`team-leader` defines a clear work-order contract through `task-bridge`, executors such as `planning-agent`, `code-agent`, `quality-agent`, and `release-agent` accept work directly, execute it, verify it, and close the loop, every state change and piece of evidence is persisted locally, and the daemon notifies `team-leader` exactly when the work item is concluded.**
