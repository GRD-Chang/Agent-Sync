# Agent Runtime 设计 v3：task-bridge 编排层与直接执行 Worker

本文档定义 Agent-Sync / `task-bridge` 后续演进的目标设计。

核心结论：本项目只做多 Agent 任务编排，不做 Codex harness 配置、安装或验证。概念上的任务流只有一条：

```text
team-leader -> task-bridge -> worker -> task-bridge -> team-leader
```

OpenClaw 与 Codex harness 是外部运行环境前提，不是本项目的编排节点。`task-bridge` 只负责把任务可靠地落盘、派发、提醒、回收和通知；worker 收到任务后就是该任务的 owner，直接在自己的运行环境里执行。

## 1. 设计北极星

目标不是“多搞几个 agent”，也不是把某个 agent 包装成另一层执行器。目标是让长期工程任务可以稳定推进、恢复、审计和收口。

理想系统应该满足：

- 用户只和 `team-leader` 对话。
- `team-leader` 把目标拆成可执行、可验收的 task contract。
- `task-bridge` 把 task 作为本地事实源落盘、排队、派发、提醒、通知。
- worker 收到 `[TASK_DISPATCH]` 后，成为该 task 的 owner，并直接开始执行。
- worker 自己读取仓库、文件、任务材料和可用工具，补齐事实性上下文。
- worker 用 `task-bridge` 写回状态、进展、证据和终态。
- `team-leader` 根据 evidence 决定继续派发、重派、收口或向用户澄清。

一句话：

> `task-bridge` 只保证任务账本可靠；执行责任在 worker；编排判断在 `team-leader`。

## 2. 当前架构判断

最终架构如下：

```text
用户 / 聊天渠道
  |
  v
team-leader
  |  理解目标、维护 work-plan、创建 task contract、选择 worker
  v
task-bridge
  |  保存 task、串行派发、提醒、状态回收、detail 路径、follow-up
  v
worker
  |  收到 [TASK_DISPATCH] 后直接执行；读取 repo/files/tools；写回 result/detail
  v
task-bridge
  |  终态通知、未处理 follow-up、dashboard 状态读取
  v
team-leader
```

边界必须明确：

- `team-leader` 负责“应该做什么、派给谁、如何验收”。
- `task-bridge` 负责“任务事实如何保存、何时派发、如何提醒、如何通知”。
- worker 负责“收到任务后如何完成并提供证据”。
- OpenClaw / Codex harness 只是 worker 与 leader 所处的外部运行环境。
- 本项目不把 OpenClaw 或 Codex harness 设计成需要在任务链路中被再次指挥的中间节点。

## 3. 要删除的旧叙事

旧设计里容易出现一层混乱：worker 收到 task 后，被提示去调用某个仓库内 bridge skill，再由这个 skill 组织另一层执行。

这会造成：

1. **责任错位**：worker 像转发员，不像任务 owner。
2. **状态分散**：任务进展可能存在第二层执行通道里，`task-bridge` 无法稳定回收。
3. **完成误判**：启动执行与完成执行被混淆，leader 可能过早验收或继续派发。
4. **排障困难**：失败时无法判断是任务契约、worker 判断、工具执行还是第二层桥接出了问题。

新设计要彻底删除这层叙事：worker 不再被描述成只做二次交接的角色。worker 就是直接执行者。

## 4. Runtime 前提与项目边界

本项目可以运行在 OpenClaw + Codex harness 之上，但不负责配置、安装或验证 Codex harness 本身。

本项目只假设：

- `team-leader` 和 worker 已经存在于可接收消息、可执行命令的 agent 环境中。
- worker 收到 `[TASK_DISPATCH]` 后可以直接读取文件、运行命令、修改代码、验证结果。
- `task-bridge` CLI 对 `team-leader` 和 worker 可用。

本项目不做：

- 不生成 OpenClaw `embeddedHarness` 配置。
- 不配置 Codex model、fallback、guardian、app-server transport。
- 不验证 Codex app-server health、gateway harness logs 或 `/status`。
- 不直接启动或管理外部 Codex CLI 执行进程。
- 不提供“让 worker 再启动另一个执行器”的 bridge skill。

因此，文档、prompt 和测试都应该只表达任务编排语义，而不是解释或管理底层 harness。

## 5. `task-bridge` 职责

`task-bridge` 是确定性的本地任务账本和派发器。

它负责：

- `job` 和 `task` 持久化。
- task 状态流转：`queued`、`running`、`done`、`blocked`、`failed`。
- 同一 worker 的任务串行派发。
- dispatch claim / rollback 安全。
- prompt template 渲染。
- worker reminders。
- 终态任务通知 `team-leader`。
- unresolved follow-up 提醒。
- artifact 路径，尤其是 `detail.md`。
- dashboard 可读取的状态。

它不负责：

- 判断具体实现策略。
- 选择 worker 内部命令或 skill 调用顺序。
- 做 code review / QA / release 判断。
- 静默改写 `assigned_agent`。
- 管理 Codex 或任何外部 harness 进程。

设计规则：

> 把可靠性下沉到 `task-bridge`；把判断留给 `team-leader` 和 worker；runtime glue 保持无聊。

## 6. `team-leader` 职责

`team-leader` 是协调者和最终收口者。

它负责：

- 理解用户意图。
- 维护 `memory/work-plan.md`。
- 判断什么时候把计划项物化为真实 task。
- 创建包含目标、范围、验收和验证方式的 task contract。
- 选择合适的 worker owner。
- 阅读终态 result / `detail.md` / evidence。
- 为 `blocked` / `failed` 结果创建后续 task。
- 判断何时向用户交付、澄清或暂停。

它不应该：

- 直接承担实现工作。
- 把 task 创建当成进展完成。
- 过度规定 worker 的内部每一步。
- 默认给同一个 worker 堆多个 queued task。
- 把质量评审合并进实现任务，除非用户明确要求。

## 7. Worker 职责

worker 是直接执行者。

它负责：

- 读取 dispatch 中的 `requirement`、`task.json`、`TOOLS.md` 和相关项目文件。
- 根据 task contract 判断目标、范围、验收标准和验证方式。
- 在开始实质工作前把 task 标记为 `running`。
- 直接在当前环境中选择工具、命令、测试、skill 和验证策略。
- 执行过程中持续写回有意义的 `result`。
- 必要时把详细证据写入 `detail.md`。
- 最后一步才把 task 标记为 `done`、`blocked` 或 `failed`。
- 当 task contract 要求 commit 且仓库状态允许时，完成 task-scoped commit。

它不应该：

- 创建额外的执行交接层。
- 在目标、范围、验收清楚时等待 `team-leader`。
- 没有验证证据就标记 complete。
- 隐藏风险、限制或未验证假设。
- 继续推进已经终态的 task，而不是等待或接收新 task。

## 8. Task Contract

`task.requirement` 第一阶段保持人类可读字符串，不强制 JSON schema。

关键原则：task contract 不需要复制完整代码上下文；它需要提供足够的任务意图、范围边界、验收标准和验证要求。事实性上下文由 worker 通过读取仓库、文档、测试、日志和相关文件补齐。

推荐模板：

```md
Objective:
这个 task 必须完成什么。

Context:
- 为什么存在这个 task。
- 上游 task、决策或用户约束。
- 相关 repo / worktree / cwd。

Scope:
- 允许触碰的文件、模块、文档或系统。
- 明确不做什么。

Acceptance:
- 完成前必须满足的条件。
- team-leader 应该检查什么。

Done Definition:
- 当前 sprint / task 到什么程度才算实现完成。
- 哪些事项不属于本轮完成范围。

Verification:
- 必须运行的命令、测试、手工检查、grep 检查或截图。
- 如果不能运行，说明原因并提供替代证据。

Artifacts:
- 是否需要 detail.md。
- 是否需要 commit。
- 是否需要 report、screenshot、log 或 diff summary。

Notes:
- 风险、约束、operator instructions。
```

缺失处理规则：

- 如果缺少的是实现细节、文件位置或代码事实，worker 应优先自己检索。
- 如果缺少的是目标、权限、范围边界、验收标准或不可逆操作批准，worker 应标记 `blocked` 或写回明确问题。
- 不要把“上下文没写全”当成默认阻塞理由；先判断能否从仓库和任务材料中可靠推导。

## 9. Agent 编排模型

编排按角色分工，而不是按 runtime 分工。

### `planning-agent`

适合：

- 需求澄清。
- 范围控制。
- tradeoff 分析。
- 架构方案。
- task graph 设计。
- acceptance 和 verification 策略。
- 把模糊任务变成可执行 task。

避免：

- scope 清楚后的主实现。
- 发布操作。
- 默认独立 QA。

### `code-agent`

适合：

- 代码阅读。
- 实现。
- 重构。
- bug 修复。
- 会导向代码修改的 root-cause investigation。
- 本地 test / build 验证。

避免：

- 纯独立 review。
- 发布或部署决策。
- 被当成“什么都派给它”的默认 agent。

### `quality-agent`

适合：

- 独立 review。
- QA。
- 测试设计。
- 回归验证。
- 安全 / 性能 / 浏览器 / 视觉检查。
- 在质量任务内，当 blast radius 清楚且可复验时做小范围修复。

避免：

- 成为第二个 `code-agent`。
- 接大范围实现。
- 没有 evidence 就 approve。

### `release-agent`

适合：

- PR readiness。
- changelog 和 release notes。
- versioning。
- deployment preparation。
- canary 和 post-deploy verification。
- 实现已验证后的 docs synchronization。

避免：

- 上游产品规划。
- 主功能实现。
- 没有 implementation 和 quality evidence 就发布。

## 10. 轻量 Resolver

Resolver 是可读的路由 artifact，不是 runtime 子系统。

目标 artifact：

```text
agents/team-leader/TASK_ROUTING.md
```

它负责：

- 帮 `team-leader` 选择合适 worker。
- 按 task 类型定义默认路由。
- 为每个 worker 定义 avoid rules。
- 定义并行规则。
- 定义什么时候先创建 planning task。
- 定义每类路由需要什么 evidence。

它不负责：

- 在 Python 中改写 task assignment。
- 阻止用户显式指定 agent。
- 替代 `team-leader` 判断。
- 变成完整分类器。

## 11. Artifact Contract

长期 agent 系统最大的失败模式，是状态只存在聊天历史里。

这个系统应该把文件视为事实源：

| Artifact | Owner | Purpose |
|---|---|---|
| `task.json` | `task-bridge` | 操作级 task 状态。 |
| `result` field | worker | 简洁进展和最终总结。 |
| `detail.md` | worker | 更长的证据、日志、判断、diff、截图、复现记录。 |
| sprint contract | `planning-agent` | done definition、acceptance、verification、artifacts、风险和未决问题。 |
| evaluation report | `quality-agent` | plan evaluation / implementation evaluation 的 pass、needs-fix 或 blocked 结论与证据。 |
| `memory/work-plan.md` | `team-leader` | 计划、task graph、当前阶段、runtime ledger、verification ledger。 |
| `TASK_ROUTING.md` | repo / `team-leader` | 路由指导。 |
| git commit | worker / release | task-scoped durable code artifact。 |
| tests / logs / screenshots | worker | 验证证据。 |

Artifact 规则：

- `task.json` 是操作账本，不是随手笔记。
- `result` 应该简洁、基于 evidence。
- 当 result 会太长，或交接需要日志时，使用 `detail.md`。
- `memory/work-plan.md` 只在真实状态变化时更新，不写思考噪音。
- 没有 evidence 的终态，不是干净终态。

## 12. Prompt Contract

Prompt 应该描述任务契约和执行责任，不应该解释内部 harness 机制。

### Dispatch Prompt

必须包含：

- `[TASK_DISPATCH]`
- `job_id`
- `task_id`
- `task_path`
- `detail_path`
- `assigned_agent`
- raw `requirement`
- execution contract

Execution contract 应该表达：

- 读取 `task.json` 和 `TOOLS.md`。
- 实质工作前标记 `running`。
- 直接在当前环境执行。
- 按需读取仓库、文档、测试和相关文件补齐事实上下文。
- 按需使用可用工具和 skills。
- 用 `update-result` 写回进展。
- 对照 Acceptance 和 Verification 验证。
- 有必要时写 `detail.md`。
- 当 task 要求且安全时，只 commit task 相关修改。
- terminal state 必须是最后一步。

不应该出现：

- 调用仓库内旧 bridge skill。
- 启动额外的外部执行进程。
- 把任务完成语义绑定到“启动执行”动作。
- 把 Codex harness 当成本项目要管理或驱动的对象。
- 把 worker 描述成 relay / bridge / 转发员。

### Worker Reminder Prompt

必须包含：

- `[TASK_REMINDER]`
- `job_id`
- `task_id`
- `assigned_agent`
- `state`
- `task_path`
- 足够让 worker 恢复任务、读取事实材料并继续推进的说明。

推荐后续增强：

- reminder 也包含 `detail_path`，让恢复后的证据继续落到同一个 artifact 路径。

### Notify Prompt

必须包含：

- `[TASK_UPDATE]`
- `job_id`
- `task_id`
- `assigned_agent` 或 `worker_agent`
- terminal `state`
- optional `detail_path`
- `user_chat_id`
- result text
- 给 `team-leader` 的 follow-up instruction

推荐后续增强：

- 给 result body 加 `Result:` 标签，便于阅读和未来解析。

## 13. Memory Model

Memory 是分层的。

不要混淆这些层：

1. **Task memory**：`task.json`、`result`、`detail.md`。
2. **Plan memory**：`team-leader` 维护的 `memory/work-plan.md`。
3. **Agent workspace memory**：agent workspace 中的 daily notes 和 `MEMORY.md`。
4. **Runtime memory**：外部 agent runtime 的 thread、resume、compaction。
5. **Project memory**：git history、docs、tests、specs。

设计原则：

> 单一 memory 层不够。系统应该在每个边界都留下可恢复 artifact。

即使外部 runtime 能恢复自己的 thread，`team-leader` 仍然需要 task ledger 和 work plan。runtime context 不能替代 task state。

## 14. Safety Model

worker 直接执行会提升自主性，这正是目的。但安全姿态必须显式写清楚。

### 14.1 Trusted Local Autonomy

适合：

- 个人本地开发机。
- 希望 worker 无人值守地持续推进。
- 用户接受 worker 拥有本地 shell / 文件 / 网络自主权。

缓解：

- 收窄 task contract。
- 检查 git status。
- task-scoped commits。
- quality-agent review。
- task context 中不要默认暴露生产凭据。

### 14.2 Guarded Autonomy

适合：

- task 触碰敏感 repo。
- 可能出现 destructive commands。
- 仍希望无人值守推进，但需要更多 guardrails。

缓解：

- 明确 task scope。
- 可用时启用 freeze / guard skills。
- release 前增加独立 quality-agent task。
- 高风险动作要求人工批准。

### 14.3 Manual Approval Mode

适合：

- 触碰生产系统。
- secret rotation、database migration、deployment、DNS、billing 等不可逆或高风险操作。

规则：

- 如果缺少明确 evidence 和 operator approval，`release-agent` 应拒绝继续执行不可逆操作。

## 15. Planner / Generator / Evaluator Loop

系统不能依赖自评。长任务的默认结构应该是 planner / generator / evaluator 分离，但是否启用完整链路由 `team-leader` 按复杂度判断。

### 15.1 角色映射

```text
planning-agent = planner / sprint contract owner
code-agent     = generator / implementation owner
quality-agent  = evaluator / plan and implementation quality owner
release-agent  = release gate
team-leader    = user-facing high-level decision maker / reconciliation owner
```

`team-leader` 不直接承担具体设计、实现或质量验收。它负责选择编排模式、创建任务、回收 evidence、做 reconcile，并向用户交付结论。

### 15.2 默认编排模式

简单任务可以直接派 `code-agent`：

```text
team-leader -> code-agent -> team-leader
```

标准开发任务默认走：

```text
team-leader -> planning-agent -> code-agent -> quality-agent -> team-leader
```

高风险或复杂任务默认走：

```text
team-leader -> planning-agent -> quality-agent(plan evaluation) -> code-agent -> quality-agent(implementation evaluation) -> team-leader
```

发布任务只有在实现 evidence 和质量 evidence 基本齐备后，才进入 `release-agent`。

### 15.3 Sprint Contract

开发前最重要的 artifact 是 sprint contract。它由 `planning-agent` 产出，必要时由 `quality-agent` 审核，至少包含：

- done definition。
- scope / non-scope。
- acceptance。
- verification。
- artifacts。
- 风险、未知项和需要用户拍板的问题。

Planner 应保持高层可执行，不要过早替 coder 决定低层实现细节，避免错误细节级联到实现。

### 15.4 Evaluator Gates

`quality-agent` 有两类 evaluator gate：

- **Plan evaluation**：在开发前审查 plan、task graph、done definition、acceptance、verification 和风险是否足够可执行。
- **Implementation evaluation**：在开发后审查 diff、artifact、命令输出、测试结果和未覆盖风险是否满足 sprint contract。

Evaluator 结论必须明确：`pass`、`needs-fix` 或 `blocked`。

质量规则：

- implementation result 不是 quality evidence。
- `code-agent done` 只表示实现完成并自测，不表示独立质量验收通过。
- “tests passed” 但没有命令输出，是弱 evidence。
- `quality-agent` 应读取 artifacts 和 source，不只读 worker summary。
- quality task `failed` 或 `blocked` 时，不应继续 release。

### 15.5 拆分粒度

当前 agent 能力较强时，不必把任务切到过细。拆分应该服务于认知边界、风险边界、文件所有权和验收边界。

推荐原则：

- 能形成完整交付闭环的 coherent sprint，可以作为一个较完整 task 派给 `code-agent`。
- 不同模块、不同风险、不同验证路径或不同 owner 时，再继续拆小。
- 不要把大需求整包压给单个 worker，也不要把一件 coherent work 切碎成大量机械小 task。
- `team-leader` 不亲自细化具体设计；需要设计细节时派 `planning-agent`。
- `team-leader` 不亲自判断实现质量；需要质量判断时派 `quality-agent`。

## 16. 开发计划

开发目标：把 Agent-Sync 收敛成纯编排层。

### Phase 0：冻结边界

目标：统一 mental model，避免把外部 runtime 配置拉回本项目。

完成标准：

- 设计文档明确“本项目不配置、不安装、不验证 Codex harness”。
- 后续 patch 不把 harness setup 当成本项目功能。
- 文档统一表达 `team-leader -> task-bridge -> worker -> task-bridge -> team-leader`。

### Phase 1：Prompt cleanup

目标：删除 nested execution language。

要改：

- `src/task_bridge/prompt_templates/dispatch.txt`
- `src/task_bridge/prompt_templates/worker_reminder.txt`
- 相关 runtime / CLI 测试期望

验收：

- dispatch / reminder 生成内容不包含旧 bridge skill 叙事。
- prompt 表达“在当前环境直接执行”。
- prompt 不要求 worker 启动另一层执行器。
- tests 覆盖正向 message shape 和负向旧关键词。

### Phase 2：删除旧 bridge skill 路径

目标：worker 不再依赖本仓库旧的 bridge skill。

验收：

- repo 文档中不再要求 worker 安装或调用旧 bridge skill。
- worker setup 不再复制 old bridge skill。

### Phase 3：轻量 Resolver artifact

目标：把 agent 编排规则沉淀为可维护 Markdown，而不是塞进 runtime 或长 prompt。

要维护：

- `agents/team-leader/TASK_ROUTING.md`
- `agents/team-leader/AGENTS.md` 对该 artifact 的引用

验收：

- 路由规则可单独 review。
- `task-bridge` daemon 不参与自动改派。
- `assigned_agent` 仍由 `team-leader` 判断或用户指定。

### Phase 4：Task Contract 和 Artifact Contract

目标：让 task 可执行、可验收，让结果可恢复。

验收：

- task contract 明确目标、范围、验收、验证和 artifacts。
- worker 能通过 task contract + repo/files/tools 开始推进。
- `team-leader` 可以通过 terminal result / `detail.md` 判断下一步。

### Phase 5：Agent docs 收敛

目标：四个 worker 都是 direct execution agents，但边界不同。

验收：

- worker docs 不再把外部 runtime 描述成需要 worker 管理的执行对象，也不额外创建执行交接层。
- worker docs 说“在当前环境直接执行”。
- `planning-agent` 不当实现兜底。
- `code-agent` 是主实现 owner。
- `quality-agent` 是独立验证 owner，不是第二个默认实现 worker。
- `release-agent` 只在 evidence 足够后收口和发布。
- `team-leader` 不直接实现代码，也不亲自承担具体技术设计或质量验收。

### Phase 6：文档收敛

目标：README / setup / flow docs 都表达“本项目只做编排”。

验收：

- 可以说明项目基于外部 agent runtime 运行。
- 不提供 Codex harness 配置步骤作为本项目目标。
- 如需提到 Codex harness，只写“按 OpenClaw / Codex harness 官方文档在项目外处理”。
- flow diagram 不出现 worker 组装 prompt 调起第二层执行器。
- flow diagram 表达 worker 收到 task 后直接执行。
