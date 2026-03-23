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

- **Role**: stage-specialized execution workers. They interact directly with the underlying model or engine, such as Codex or Claude Code.
- **Responsibilities**:
  - When awakened by the daemon, accept the task and immediately mark it as `running`.
  - Assemble context and drive the lower-level engine to perform the actual engineering work.
  - **Continuously write back progress**: during execution, keep updating key progress and evidence through `task-bridge update-result`.
  - Verify the outcome, commit changes if needed, and finally mark the task as `done`, `blocked`, or `failed`.
- **Specialization**:
  - `planning-agent`: requirement clarification, plan review, design direction, and solution shaping.
  - `code-agent`: solution design, implementation, bug fixing, and refactoring.
  - `quality-agent`: test authoring, regression validation, code review, and documentation cleanup.
  - `release-agent`: release preparation, deployment, post-deploy verification, and documentation sync.

### Task Bridge Daemon

- **Role**: background supervisor.
- **Responsibilities**: scan the local task pool, dispatch tasks under serial-execution rules, monitor agents that have gone quiet for too long, send reminder nudges, and trigger the exact upward notification when a task is finished.

---

## 3. Core Objects and Data Flow

All collaboration facts live in a simple file layout:

```text
jobs/<job_id>/
  ├── job.json            # One broader work topic (for example: build a Todo CLI)
  ├── tasks/
  │   └── <task_id>.json  # Smallest executable unit
  └── artifacts/
      └── <task_id>/
          └── detail.md   # Execution details / logs / evidence
```

**Core task state flow (`state`):**
`queued` -> `running` -> `done` / `blocked` / `failed`

- `requirement`: the instruction written by the leader for the worker. It must be self-contained and explain what to do and how to verify completion.
- `result`: the execution trace and final delivery note written back by the worker.

---

## 4. Main Workflow Sequence

The following ASCII sequence diagram shows how a standard long-running task moves through the system:

```text
+-------------+      +---------------+      +--------------+      +-----------------------+      +-------------+
| User        |      | team-leader   |      | task-bridge  |      | planning / code / quality / release |      | Codex / CLI |
|             |      |               |      |   (daemon)   |      |                       |      |             |
+-------------+      +---------------+      +--------------+      +-----------------------+      +-------------+
       |                     |                      |                           |                       |
       | 1. Submit a goal    |                      |                           |                       |
       |-------------------->|                      |                           |                       |
       |                     | 2. Plan and split    |                           |                       |
       |                     | 3. create-task       |                           |                       |
       |                     |--------------------->|                           |                       |
       |                     |                      | 4. Persist as queued task |                       |
       |                     |                      |                           |                       |
       |                     |                      | 5. Find idle worker       |                       |
       |                     |                      | Send [TASK_DISPATCH]      |                       |
       |                     |                      |-------------------------->|                       |
       |                     |                      |                           |                       |
       |                     |                      |                           | 6. start -> running   |
       |                     |                      |<--------------------------|                       |
       |                     |                      |                           | 7. Build prompt / run |
       |                     |                      |                           |---------------------->|
       |                     |                      |                           |                       |
       |                     |                      | 8. Periodic anti-stall    |                       |
       |                     |                      | reminders                 |                       |
       |                     |                      |-------------------------->|                       |
       |                     |                      |                           | 9. Execute / edit /   |
       |                     |                      | 10. Continuous            | test                  |
       |                     |                      | update-result             |<----------------------|
       |                     |                      |<--------------------------|                       |
       |                     |                      |                           |                       |
       |                     |                      |                           | 11. Pass or fail      |
       |                     |                      | 12. Mark terminal state   |                       |
       |                     |                      |<--------------------------|                       |
       |                     |                      |                           |                       |
       |                     | 13. [Notify] task    |                           |                       |
       |                     | finished             |                           |                       |
       |                     |<---------------------|                           |                       |
       |                     |                      |                           |                       |
       |                     | 14. Update work plan |                           |                       |
       |                     | 15. Dispatch next or |                           |                       |
       |                     | deliver to user      |                           |                       |
       |<--------------------|                      |                           |                       |
```

---

## 5. Key Constraints and Design Principles

To keep the pipeline from collapsing, the system depends on the following rules:

1. **Single-task rule**: a worker may hold only one `running` task at a time. Concurrent execution on the same worker is not allowed.
2. **State lock**: only tasks in `queued` may have their `requirement` or `assigned_agent` changed.
3. **Safe deletion**: only tasks in `queued` or `done` may be deleted. A failed task must be kept as evidence, and any recovery should happen in a newly created task.
4. **Mandatory write-back**: workers must continuously update `result` through `task-bridge` during execution so progress stays visible.
5. **Precise interruption policy**: before a task reaches a terminal state, Bridge must not disturb the leader with intermediate noise.

## 6. One-Sentence Summary

This system is not "the leader constantly watching workers." Instead:

**`team-leader` defines a clear work-order contract through `task-bridge`, executors such as `planning-agent`, `code-agent`, `quality-agent`, and `release-agent` drive the underlying engine (for example Codex) to complete the work, every state change and piece of evidence is persisted locally, and the daemon notifies `team-leader` exactly when the work item is concluded.**
