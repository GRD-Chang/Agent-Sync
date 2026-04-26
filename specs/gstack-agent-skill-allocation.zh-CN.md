# Worker Skill 使用原则

## 目标

本文档说明当前多 agent 架构中，worker 如何使用可用 skills。

核心原则很简单：

1. `team-leader` 不持有具体执行型 skill，不直接做设计、实现、测试或发布。
2. `planning-agent`、`code-agent`、`quality-agent`、`release-agent` 收到 task 后，先查看当前会话可用 skills。
3. 如果存在匹配当前 task 目标、范围、验收标准和验证要求的 skill，worker 优先使用该 skill 组织执行。
4. 如果没有匹配 skill，或 skill 不适合当前边界，worker 直接阅读仓库、运行命令、整理证据并回写结果。
5. `TOOLS.md` 不维护完整 skill 清单，只记录本地环境约束、`task-bridge` 命令和执行边界。

这不是静态 skill 分配表。skill 能力由当前运行环境暴露，worker 在执行时按任务选择。

## 当前角色边界

### `team-leader`

- 面向用户做高层判断、建单、派发、证据回收和最终收口。
- 根据 `TASK_ROUTING.md` 选择合适 worker。
- 不直接调用执行型 skill。
- 不直接写代码、跑测试、做发布或替代 evaluator。

### `planning-agent`

- 负责需求澄清、范围收敛、方案冻结和 sprint contract。
- 适合规划类、设计类、架构口径类、复盘类 task。
- 如果当前会话存在匹配规划任务的 skill，优先使用该 skill。
- 输出重点是：scope / non-scope、done definition、acceptance、verification、artifacts、风险和未决问题。

### `code-agent`

- 负责实现级设计、代码阅读、根因调查、实现、修复、重构、测试和 task-scoped commit。
- 适合边界清晰的实现任务、缺陷修复、代码改造和可本地验证的工程交付。
- 如果当前会话存在匹配工程任务的 skill，优先使用该 skill。
- 输出重点是：改了什么、为什么这样改、验证证据、风险限制、是否已提交。

### `quality-agent`

- 负责 plan evaluation、implementation evaluation、独立 review、QA、测试验证、风险分级和必要的小范围修复。
- 适合质量判断、验收、回归、安全、性能、浏览器验证和文档一致性任务。
- 如果当前会话存在匹配质量任务的 skill，优先使用该 skill。
- 输出必须给出明确结论：`pass` / `needs-fix` / `blocked`。

### `release-agent`

- 负责发布准备、PR/部署/上线验证、回滚口径、交付说明和文档同步。
- 适合实现 evidence 与质量 evidence 基本齐备后的交付收口。
- 如果当前会话存在匹配发布任务的 skill，优先使用该 skill。
- 生产、高风险或不可逆动作必须先明确权限、窗口、验证和回滚口径。

## Skill-first 执行规则

Worker 收到 `[TASK_DISPATCH]` 后，按以下顺序推进：

1. 读取 `task.json` 和自己的 `TOOLS.md`。
2. 如果 task 指定了 repo / worktree / cwd / 工作路径，先检查该路径下是否存在 `AGENTS.md`；如果存在，先阅读并遵守。
3. 查看当前会话可用 skills。
4. 判断是否存在匹配当前 task 的 skill。
5. 有匹配 skill：优先使用该 skill 组织执行。
6. 无匹配 skill：直接阅读仓库、运行必要命令、整理证据。
7. 通过 `task-bridge start/update-result/complete/block/fail` 回写状态和结果。

## 为什么不再维护静态 skill 分配表

之前的方案把 skills 按角色写成静态表格。这会带来三个问题：

- skill 列表会随运行环境变化，文档容易过期。
- worker 可能误以为只有表格里的 skills 可用。
- agent 能力增强后，过细的 skill 分配反而会制造不必要的流程感。

当前方案把选择权放回 worker：

- `team-leader` 决定派给哪个 worker。
- `task-bridge` 负责可靠派发和状态流转。
- worker 根据当前 task 和当前会话可用 skills 做最小必要选择。

这样能同时保持两件事：

- 编排层稳定、可追踪。
- 执行层灵活、贴近当前 runtime 能力。

## 不变的边界

- 不为了“用 skill”而使用 skill。
- 不把 skill 当成第二层任务中转。
- 不让 `team-leader` 替代 planner、coder、evaluator 或 release worker。
- 不让 worker 超出 task contract 做无关重构。
- 不在缺少证据时把结果标记为完成。

