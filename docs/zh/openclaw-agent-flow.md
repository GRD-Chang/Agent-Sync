# OpenClaw Agent 工作流指南

这份文档用于帮助你快速理解 `task-bridge` 的架构体系，以及 `team-leader`、`planning-agent`、`code-agent`、`quality-agent`、`release-agent` 之间的协作流转关系。

## 1. 为什么需要 Task Bridge？

在多 Agent 协作开发中，我们通常面临这样一个问题：当一个 Agent（如 `code-agent`）被唤醒去执行一项耗时较长、流程复杂的工程任务时，传统的通过“聊天记录”维护状态的机制会迅速崩溃。Agent 容易遗忘前置步骤，异步执行常常导致流程挂起，最终任务无法闭环。

`task-bridge` 就是为了解决这一痛点而设计的**本地轻量任务状态机**。

它的核心作用是：**把易丢失的聊天协作过程，转化为可追踪、可恢复、可查询的本地任务模型（JSON）。**

### 核心机制
- **化对话为工单**：用 `job -> task` 的层级关系组织需求推进。
- **事实落地**：将 `assigned_agent` (负责人)、`state` (状态)、`requirement` (需求)、`result` (结果) 固化在本地 JSON 文件中。
- **串行安全分发**：确保同一个 worker 一次只处理一个任务，防止工作流混乱。
- **防挂起守护**：Daemon 后台进程周期性发送派单与执行提醒，保障长流程执行到底。
- **精准的终态回收**：当任务真正进入终态（完成/阻塞/失败）时，Bridge 才将结果回调通知给协调者。

---

## 2. 团队角色与架构

在这套体系中，协作不是通过 Agent 之间的“口头交谈”完成的，而是通过 `task-bridge` 这个中枢进行的：

### 🧑‍💼 Team Leader (协调者)
- **定位**：任务编排者，不直接写代码，也不直接执行工程命令。
- **职责**：
  - 理解用户目标、范围、约束和优先级。
  - 维护全局状态规划 (`memory/work-plan.md`)。
  - 把目标拆解为具体的子任务 (`task`)，写清要求 (`requirement`)。
  - 通过 `task-bridge CLI` 派发工单，选择合适的执行者。
  - 接收 Bridge 回调的任务终态，决定继续派发还是向用户交付验收。

### 🧑‍💻 Worker Agents (执行者 Worker)
- **定位**：阶段化工程执行者，直接接单并在自己的工作区内推进任务。
- **职责**：
  - 收到 Daemon 派发的任务后，接单并立刻将状态标记为 `running`。
  - 先查看当前会话可用 skills；如果存在匹配当前 task 目标、范围、验收和验证要求的 skill，优先使用该 skill 组织执行。
  - 组织上下文，直接执行实际的工程任务。
  - **持续回写**：在执行过程中，通过 `task-bridge update-result` 不断更新关键进展和证据。
  - 验证成果，必要时提交代码 (commit)，最后将任务标记为 `done`、`blocked` 或 `failed`。
- **分工侧重**：
  - `planning-agent`：偏向需求澄清、高层 spec 收敛、验收口径与验证要求。
  - `code-agent`：偏向实现级设计、代码实现、根因调查、缺陷修复与重构。
  - `quality-agent`：偏向 plan evaluation、implementation evaluation、独立评审、QA 与风险分级。
  - `release-agent`：偏向发布准备、部署、上线验证与文档同步。

### 🤖 Task Bridge Daemon (任务中枢)
- **定位**：后台监督者。
- **职责**：扫描本地工单池，按串行规则调度任务；监控长时间无响应的 Agent 并发送督促提醒；在工单了结时精准触发向上级的汇报。
- **自我观测**：每轮写入 `daemon_heartbeat.json`，记录 pid、时间和本轮 `phase_errors`；`daemon-status` 可用来判断 daemon 是否仍在运行，以及 pid 文件是否已经陈旧。
- **失败隔离**：dispatch、reminder、notify、follow-up 和 heartbeat 分阶段执行；单个阶段失败会写入 `daemon_errors.jsonl`，但不会直接杀掉整个 daemon。

---

## 3. 核心对象与数据流转

所有的协作事实都以最简单的文件目录形式存在：

```text
current_job
daemon.pid
daemon_heartbeat.json
daemon_errors.jsonl
daemon_state.json
jobs/<job_id>/
  ├── job.json            # 一轮较完整的工作主题（如：开发 Todo CLI）
  ├── tasks/
  │   └── <task_id>.json  # 最小执行单元
  └── artifacts/
      └── <task_id>/
          └── detail.md   # 执行细节/日志证据
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

**Task 核心状态流转 (`state`)：**
`queued` (排队中) -> `running` (执行中) -> `done` (完成) / `blocked` (阻塞) / `failed` (失败)

- `requirement`：Leader 派给 Worker 的任务契约，必须说明任务意图、范围边界、验收标准和验证要求；代码事实、文件位置和实现细节由 Worker 读取仓库与材料补齐。
- `result`：Worker 回写的执行痕迹和最终交付说明。
- `_scheduler`：Bridge 自己维护的调度字段，包括 `awaiting_claim`、`last_dispatch_at`、`last_dispatch_error`、`dispatch_failure_count`、`dispatch_cooldown_until`、`dispatch_blocked`、`final_notified_at`、通知错误和 leader follow-up 时间。

`codex-team/runs/<run_id>/` 是 Codex Team harness 的独立 run store。它复用 `TASK_BRIDGE_HOME`，但不把 Generator 的 `ready_for_review` 映射成现有 task 的 `done/blocked/failed` 终态。Codex Team 当前采用 round harness：Planner 产出完整高层 spec，Generator 连续完成完整 build round 后交给 Evaluator，Evaluator 做 round-level review 并给出聚合修复意见或 final pass。

---

## 4. 主时序工作流图

下面这张 ASCII 时序图描述了一次标准长程任务是如何流转的：

```text
+-------------+      +---------------+      +--------------+      +--------------------------------------+
| User        |      | team-leader   |      | task-bridge  |      | planning / code / quality / release  |
|             |      |               |      |   (daemon)   |      | OpenClaw worker session              |
+-------------+      +---------------+      +--------------+      +--------------------------------------+
       |                     |                      |                              |
       | 1. 提出宏观需求     |                      |                              |
       |-------------------->|                      |                              |
       |                     | 2. 规划并拆解目标    |                              |
       |                     | 3. create-task       |                              |
       |                     |--------------------->|                              |
       |                     |                      | 4. 任务落盘入队 (queued)     |
       |                     |                      |                              |
       |                     |                      | 5. 发现空闲 Worker           |
       |                     |                      | 检查预算与 cooldown           |
       |                     |                      | /reset 后发送 [TASK_DISPATCH] |
       |                     |                      |----------------------------->|
       |                     |                      |                              |
       |                     |                      |      6. start -> running     |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     |                      |      7. 先查可用 skill，匹配则优先用 |
       |                     |                      |      8. 直接执行、修改、测试 |
       |                     |                      |      9. 持续 update-result   |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     |                      | 10. daemon 周期防挂起提醒    |
       |                     |                      |----------------------------->|
       |                     |                      |                              |
       |                     |                      |      11. 验收通过或确认失败 |
       |                     |                      |      12. 标记终态            |
       |                     |                      |<-----------------------------|
       |                     |                      |                              |
       |                     | 13. [通知] 任务结束 |                              |
       |                     |<---------------------|                              |
       |                     |                      |                              |
       |                     | 14. 更新工作计划     |                              |
       |                     | 15. 继续派单或交付   |                              |
       |<--------------------|                      |                              |
```

---

## 5. 关键设计约束与原则

为了确保流水线不崩溃，系统强依赖以下设计约束：

1. **单工原则**：同一个 worker 在同一时刻只能持有一个 `running` 状态的任务，拒绝并发混乱。
2. **状态锁定**：只有处于 `queued` 状态的任务才允许修改需求 (`requirement`) 或更改负责人 (`assigned_agent`)。
3. **安全删除**：只有 `queued` 或 `done` 状态的任务允许删除。若任务失败，禁止直接删除，需保留作为证据，并重建修复任务。
4. **强制回写**：Worker 必须在执行期间不间断地向 `task-bridge` 回写 `result`，保持进度透明。
5. **Skill-first**：Worker 收到任务后先查看当前会话可用 skills；有匹配 skill 时优先使用，没有匹配 skill 时再直接使用命令和工具。
6. **精准打扰**：在任务达到终态前，Bridge 绝不会打扰 Leader，防止中间过程噪音干扰协调者的决策。
7. **预算退避**：如果 OpenClaw 进程预算已满，派发会进入短暂 deferred；这不是任务失败，不会累计到 `dispatch_blocked`，也不会在 `/reset` 前打断活跃会话。
8. **失败阻断**：只有真实 reset/send 失败才递增 `dispatch_failure_count`；连续失败达到阈值后才设置 `dispatch_blocked`，防止同一任务无限重启 worker。
9. **通知边界**：`notify_updates()` 默认只处理 current job；历史终态任务必须显式使用 `notify-backfill --mark-only` 或 `notify-backfill --summary`。
10. **安全测试**：设置 `TASK_BRIDGE_CAPTURE_FILE` 后，Bridge 只把消息写入 JSONL，不调用真实 OpenClaw，也不受 live OpenClaw 进程预算影响。

## 6. 一句话总结

这套系统不是“Leader 直接盯紧 Worker”，而是：

**`team-leader` 通过 `task-bridge` 建立清晰的工单契约，`planning-agent`、`code-agent`、`quality-agent`、`release-agent` 等执行者按阶段直接接单、执行、验证并闭环交付，中间的所有状态变化和证据均持久化到本地文件；最后，Daemon 会在工单了结时准确通知 `team-leader` 回收成果。**
