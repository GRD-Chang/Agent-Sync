# TASK_ROUTING.md - team-leader 轻量路由指南

本文件是 `team-leader` 的路由参考。它回答“这类 task 通常应该派给谁、需要什么 evidence、什么时候应该先拆小”。

它不是 runtime，不是强制分类器，也不参与 `task-bridge` daemon 调度。显式用户要求和 `team-leader` 的具体判断优先。

## 路由原则

- 显式用户指定的 `assigned_agent` 优先。
- `team-leader` 是面向用户的高层决策者和收口者，不直接承担具体设计、实现、测试或发布动作。
- 具体设计主要依赖 `planning-agent`；计划可行性、验收标准和质量判断主要依赖 `quality-agent`。
- scope 不清楚、方案未冻结、验收标准不明确时，先派 `planning-agent` 做澄清或方案冻结。
- 复杂或高风险开发进入实现前，默认先走 `planning-agent -> quality-agent`：先产出 plan / task graph / acceptance / verification，再由 `quality-agent` 做 plan evaluation，最后由 `team-leader` reconcile 后派发开发。
- 需要实际代码修改时，默认派 `code-agent`。
- `code-agent` 完成一个开发 sprint / task 后，默认由 `quality-agent` 做 implementation evaluation；`code-agent done` 只代表实现完成，不代表质量已通过。
- 需要独立验证、review、QA、安全、性能或浏览器检查时，默认派 `quality-agent`。
- 实现和质量证据基本齐备后，才派 `release-agent` 做交付收口。
- 同一个 worker 同一时间只保留一个未完成 task；不要给同一 worker 堆多个 queued task。
- 不要复用 `blocked` / `failed` task 继续工作；保留原 task 作为证据，再创建后续 task。
- 并行只发生在不同 worker 之间，并且必须先拆清边界。
- 任务拆分要服务于认知边界和验收边界；不要把开发任务切得过细，能由强 worker 在一个 coherent sprint 内完成的工作，可以作为一个较完整 task 派发。

## planning-agent

适合：

- 新需求澄清、问题定义、范围收敛。
- 实现前的产品、设计、工程计划评审。
- 技术选型、方案比较、风险识别。
- task graph、验收口径、验证策略。
- 当前还不适合直接实现的任务。

避免：

- 已边界清晰的主实现任务。
- 纯代码修改、测试执行或发布操作。
- 被当成“还没想好派谁”的兜底执行者。

需要 evidence：

- 推荐方案和被拒绝方案。
- 明确 scope / non-scope。
- task graph 或下一步任务建议。
- sprint contract：本轮开发的 done definition、acceptance、verification、artifacts。
- 主要风险、未知项和需要 evaluator 审核的判断。

## code-agent

适合：

- 代码阅读、实现、修复、重构。
- 根因分析后需要修改代码的问题。
- 可通过本地命令验证的工程交付。
- 跨模块但边界清晰的实现任务。
- 复杂修复和主实现 owner。

避免：

- 纯独立 review。
- 发布、部署、上线后监控。
- 证据验收优先的质量任务。
- 无关重构或超出 task scope 的顺手修复。

需要 evidence：

- 修改了什么文件。
- 关键实现或根因判断。
- 运行了什么验证命令。
- 风险、限制、未完成项。
- 是否完成 task-scoped commit。

## quality-agent

适合：

- plan evaluation：审查 planning-agent 的方案、范围、task graph、done definition 和 verification 是否足够可执行。
- implementation evaluation：审查 code-agent 的实现、diff、测试结果和风险是否满足 sprint contract。
- 独立 code review。
- QA、测试设计、回归验证。
- 安全、性能、浏览器、视觉检查。
- 对 worker 结果做证据化验收。
- 在当前质量任务内可闭环的小范围修复。

避免：

- 作为第二个默认实现 worker。
- 在影响范围不清晰时直接承担大规模改动。
- 只读 worker summary 就批准。

需要 evidence：

- 检查了哪些文件、页面、命令或 artifact。
- 对照了哪个 sprint contract / acceptance / verification。
- 发现的问题和严重度。
- 已验证通过的路径。
- 未覆盖路径和风险。
- 明确结论：pass / needs-fix / blocked。
- 是否建议 release 或需要后续修复 task。

## release-agent

适合：

- PR、版本、CHANGELOG、README、发布说明。
- 部署配置、上线操作、canary 和发布后验证。
- 交付收口和发布流程编排。
- 实现与质量证据齐备后的文档同步。

避免：

- 前置规划。
- 主功能实现。
- 实现证据或质量证据不足时强行发布。
- 不可逆操作缺少 operator approval。

需要 evidence：

- 引用的实现 task 和质量 task。
- 发布前检查项。
- 变更摘要和风险。
- 部署 / PR / 文档状态。
- 上线后验证或无法验证的原因。

## 编排模式

### 简单任务

适合小范围、低风险、验收清晰的修改：

```text
team-leader -> code-agent -> team-leader
```

可选增加 `quality-agent` 轻量验证。

### 标准开发任务

适合多数中等复杂度开发：

```text
team-leader -> planning-agent -> code-agent -> quality-agent -> team-leader
```

`planning-agent` 负责具体设计和 sprint contract；`code-agent` 负责实现；`quality-agent` 负责独立验证。

### 高风险或复杂任务

适合跨模块、高不确定性、安全/数据/发布风险较高的工作：

```text
team-leader -> planning-agent -> quality-agent(plan evaluation) -> code-agent -> quality-agent(implementation evaluation) -> team-leader
```

只有 plan evaluation 通过后才进入开发。implementation evaluation 失败时，不直接 release，由 `team-leader` 创建修复 task。

### 发布任务

适合已有实现与质量证据后的交付：

```text
team-leader -> release-agent -> quality-agent/release verification -> team-leader
```

不可逆或生产动作缺少 operator approval 时，不继续发布。

## 拆分粒度

- 不追求把任务切得极小；当前 agent 能力足够时，应派发能形成完整交付闭环的 coherent sprint。
- 一个 sprint task 应该有清晰目标、范围、验收、验证和 artifact，不要求只改一个文件或只做一个微步骤。
- 只有在依赖关系、风险边界、文件所有权或验证路径明显不同的时候才继续拆小。
- 不要让 `team-leader` 自己细化具体技术设计；需要设计细节时派 `planning-agent`。
- 不要让 `team-leader` 自己判断实现质量；需要质量判断时派 `quality-agent`。

## 并行策略

- 可以让 `planning-agent` 先行收敛计划，再并行派发给 `code-agent` 与 `quality-agent`。
- 可以让 `code-agent` 与 `quality-agent` 并行承担不同开发子任务，但必须先拆出清晰文件或模块边界。
- 可以让 `quality-agent` 与 `release-agent` 并行做发布前验证与交付准备，但 release 不能越过关键质量阻塞。
- 边界不清时先派更小的摸底 task。

## Rescue Routing

### blocked

- 保留原 task。
- 新建后续 task，写清上一个 `task_id`、阻塞原因、需要补齐的信息、验收标准。
- 如果是需求不清，派 `planning-agent`。
- 如果是实现问题，派 `code-agent`。
- 如果是验证问题，派 `quality-agent`。

### failed

- 保留原 task 作为证据。
- 不要让同一个 task 继续被执行。
- 根据失败类型创建更小的修复 task。
- 如果失败原因不明，优先派 `code-agent` 做根因调查，或派 `quality-agent` 做独立复现。

### stale

- 如果 worker 长时间 running，先检查 `task-bridge queue <agent> --json` 和 task result。
- 如果有进展但未收口，发 reminder。
- 如果无证据、无进展、scope 又不清，创建 planning rescue task。
