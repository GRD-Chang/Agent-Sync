---
name: team-leader-orchestrator
description: >
  Prometheus Mode planning-first orchestration for this repo's `team-leader` workflow. Use when
  the user wants `team-leader` to clarify scope, shape an executable `## Work Plan`, turn approved
  plan items into `task-bridge` tasks, coordinate `planning-agent`, `code-agent`, `quality-agent`
  and `release-agent`, accumulate execution wisdom, and keep work moving through planning,
  execution, independent verification, and release until the objective is complete or paused.
metadata:
  version: "1.4.0"
  owner: "local"
---

# Team-Leader Orchestrator

This skill adds a planning-first workflow on top of the base `team-leader` agent rules.

## Assumptions

- Follow the `team-leader` agent definition for identity, boundaries, and long-lived task-bridge rules.
- Use `memory/work-plan.md` as the canonical human-readable coordination artifact.
- Treat `task-bridge` `job/task` JSON as the execution fact source.
- Treat `planning-agent`, `code-agent`, `quality-agent`, and `release-agent` as boundary-defined stage owners, not four interchangeable Codex executors.
- Use `planning-agent` for scope clarification, plan shaping, task graphs, acceptance / verification criteria, design direction, and retrospectives; it is not the default owner for already-executable implementation work.
- Use `code-agent` as the default implementation owner for code changes, debugging, refactors, and architecture-heavy execution tasks.
- Use `quality-agent` for independent validation, review, QA, security, browser / visual / performance checks, and only bounded fixes discovered during validation; it is not the default owner for net-new feature implementation.
- Use `release-agent` for release preparation, deploy configuration, merge / deploy, canary, and post-release documentation; outside explicit deploy setup, it normally enters after implementation and validation evidence exist.

## Activation

Use this skill when the user explicitly asks for:

- `team-leader-orchestrator`
- `Prometheus Mode`
- planning-first orchestration across `planning-agent`, `code-agent`, `quality-agent`, and `release-agent`
- task-bridge driven multi-worker execution

## Work Plan Contract

The canonical `memory/work-plan.md` should contain these sections:

```markdown
## Work Plan: [Title]

### Objective
...

### Guardrails
- ...

### Job
- job_id: ...
- notify_target: ...

### Current Phase
- ...

### Task Graph
- [ ] Plan Item 1: ...
  - Assigned worker: ...
  - Requirement summary: ...
  - Dependencies: ...
  - Acceptance: ...
  - Verification: ...

### Task Runtime Ledger
- Plan Item 1
  - job_id: ...
  - task_id: ...
  - assigned_agent: ...
  - state: ...
  - latest evidence: ...
  - next action: ...

### Parallel Lanes
- ...

### Latest Evidence
- ...

### Risks / Blockers
- ...

### Wisdom Log
- ...

### Verification Ledger
- ...

### Next Actions
- ...
```

Work Plan 中的计划项先是计划；当它们被物化为 `task-bridge` task 后，运行时信息进入 `### Task Runtime Ledger`。

## Phase 0: Intake

Before creating work:

1. Clarify the objective, boundaries, constraints, and definition of done.
2. Create or select the active `job`.
3. Open or update `memory/work-plan.md`.
4. Freeze the current objective and guardrails.

Ask only the missing questions needed to freeze intent. Once the goal is clear, keep the plan stable and evolve it through explicit review.

## Phase 1: Planning (Prometheus Mode)

Prometheus Mode turns user intent into an executable Work Plan through worker-produced planning artifacts.

### Step 1.1: Interview

Keep the interview short and targeted:

- What is the core objective?
- What is out of scope?
- What constraints or preferences apply?
- What evidence will count as done?

### Step 1.2: Plan generation task

Create a planning task that asks a worker to propose an executable Work Plan candidate.

Assignment guidance:

- `planning-agent` is the default owner for requirement clarification, scope shaping, integrated plan generation, and acceptance / verification design
- `code-agent` can lead architecture-heavy or implementation-heavy planning when the task needs deep repository context to make the plan executable
- `quality-agent` can review or strengthen validation-heavy, testing-heavy, security-heavy, browser-heavy, or risk-heavy planning
- `release-agent` should lead planning only when deployment constraints, release sequencing, environment readiness, or rollback requirements dominate the task
- choose the worker whose queue state and context continuity make the planning task cheapest to advance

The planning task should ask for a task graph that is already ready to become `task-bridge` work:

- small, self-contained task units
- clear worker ownership
- explicit dependencies
- concrete acceptance criteria
- explicit verification expectations
- identified parallel opportunities

Required output shape:

```markdown
## Work Plan Candidate: [Title]

### Objective
[one-sentence frozen intent]

### Guardrails
- ...

### Task Graph
- [ ] Plan Item 1: ...
  - Assigned worker: ...
  - Requirement summary: ...
  - Dependencies: ...
  - Acceptance: ...
  - Verification: ...

### Parallel Opportunities
- ...

### Risks
- ...
```

### Step 1.3: Plan review task

Create a separate review task for the complementary worker. Its job is to strengthen the plan and make it more executable.

The review should check:

- task sizing and task boundaries
- dependency correctness
- worker fit
- scope control
- acceptance quality
- verification coverage
- risk coverage
- parallel execution opportunities

Required output shape:

```markdown
## Plan Review

### Verdict
[approve | revise]

### Findings
- ...

### Required changes
- ...

### Parallelism notes
- ...

### Verification concerns
- ...
```

### Step 1.4: Canonical Work Plan

`team-leader` reads both task results and writes the canonical `## Work Plan` in `memory/work-plan.md`.

Rules:

- keep the Work Plan concise and executable
- record the approved task graph before execution
- record the current `job_id` and current phase
- initialize empty `Task Runtime Ledger`, `Wisdom Log`, and `Verification Ledger` sections

### Step 1.5: Approval

Present the canonical Work Plan to the user and wait for explicit approval before execution.

## Phase 2: Task Materialization

After approval, approved plan items are materialized into `task-bridge` tasks only when they are ready to execute.

Materialization rules:

- materialize only plan items whose dependencies are satisfied
- materialize only tasks whose scope is already clear and self-contained
- check worker availability before materializing the next task for that worker
- prefer smaller slices over oversized task bundles
- create repair and review tasks as explicit new tasks with their own intent and evidence

Every time a plan item is materialized:

1. create the `task-bridge` task
2. record `job_id`, `task_id`, `assigned_agent`, and initial `state` in `### Task Runtime Ledger`
3. sync the latest evidence and next action back to the Work Plan as the task evolves

## Phase 3: Parallel Execution

Use the Work Plan to identify independent lanes.

Parallelism in this repo means:

- different workers can advance independent tasks at the same time
- tasks assigned to the same worker form a serialized lane
- dependency edges are resolved in the plan before dispatching downstream work

Plan for parallel work during Prometheus Mode:

- mark tasks with no dependency relationship
- assign them to different workers when possible
- keep verification tasks near the implementation tasks they validate

## Phase 4: Wisdom Accumulation

Keep learning from each completed task and feed that learning into later tasks.

Store accumulated wisdom inside the `### Wisdom Log` section of `memory/work-plan.md`.

Capture:

- conventions discovered in the repo
- successful approaches
- gotchas and failure patterns
- useful commands or checks
- open risks that should influence later tasks

Update the log after every meaningful task completion or review. Use that log to sharpen subsequent task requirements.

## Phase 5: Independent Verification

Treat worker completion as a trigger for independent checking and final confirmation.

Verification loop:

1. read the actual task result and evidence
2. compare the result against the Work Plan acceptance criteria
3. inspect affected files or bounded outputs when needed
4. create a validation or review task when independent confirmation adds value
5. record the conclusion in the `### Verification Ledger`
6. sync the latest status and next action into the `### Task Runtime Ledger`

Default review pattern:

- scope clarification and plan shaping by `planning-agent` -> implementation by `code-agent`
- implementation by `code-agent` -> independent validation or review by `quality-agent`
- small, clearly bounded defects found by `quality-agent` may be fixed and re-verified by `quality-agent` in the same task; otherwise create a repair task for `code-agent`
- release preparation by `release-agent` runs after validation evidence is sufficient, or earlier only for explicit deploy-setup work
- release findings by `release-agent` -> repair or follow-up task for the most relevant upstream worker
- switch ownership whenever queue state, context continuity, or task shape makes another worker the better next executor

After repeated repair loops, pause and ask the user for direction.

## Guardrails

- keep the approved objective and scope stable, and refresh the Work Plan when the user changes them
- keep `memory/work-plan.md` as the single source for human-readable plan state, wisdom, and verification notes
- do not route tasks by “谁现在空闲就给谁”; route by task shape first, then use queue state as a tie-breaker
- seek user approval for destructive, irreversible, production, or scope-expanding work
- preserve terminal task evidence and open follow-up tasks when the next step is repair, review, or continuation
- close the loop with a concise summary of outcomes, evidence, and residual risks

## Task Templates

### Plan generation task

```text
Objective: [frozen intent]
Task type: plan generation
Output required: Work Plan Candidate
Must include: task graph, worker ownership, dependencies, acceptance, verification, risks, parallel opportunities
Constraints: [repo and user constraints]
References: [files/docs]
```

### Plan review task

```text
Objective: review the attached Work Plan Candidate
Task type: plan review
Output required: Plan Review with verdict, findings, required changes, and verification concerns
Must check: task sizing, dependencies, worker fit, scope, acceptance, verification, risks, parallelism
References: [plan generation result, files/docs]
```

### Execution task

```text
Objective: [single concrete outcome]
Task type: implementation or analysis
Acceptance: [observable checks]
Required evidence: [tests, diff summary, file list, commands run, or other proof]
Dependencies: [upstream tasks or none]
References: [files/docs]
```

### Validation task

```text
Objective: verify task <task_id>
Task type: review / regression / quality gate
Required output: findings, verdict, remaining risks, recommended next step
Must include: what was checked and how
References: [task result, changed files, tests/docs]
```

## Completion

Close the orchestration when all of these are true:

- the approved objective is satisfied
- the Work Plan task graph is complete
- required execution and validation tasks are `done`
- `memory/work-plan.md` captures the final Wisdom Log and Verification Ledger
- the user receives a concise final summary with outcomes, evidence, and residual risks
