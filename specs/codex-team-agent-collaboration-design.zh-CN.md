# Codex Team 简化协作设计

本文档定义一个面向 Codex 的轻量团队开发 harness。目标是复现 Anthropic long-running app harness 的关键思想：少量角色、文件化交接、结构化路由、独立评审，让强 agent 自主推进开发，同时让代码层保留必要的交通规则。

第一版只做一种运行模式，不引入 `fast`、`standard`、`strict`、`auto`。不同任务形态由 agent 通过最终 action envelope 自行决定，不由代码写死成固定流水线。

核心公式：

```text
Planner / Generator / Evaluator
+ file-only handoff
+ lightweight structured action
+ lightweight dispatcher guardrails
```

## 1. 目标与非目标

用户通常会提供一份高层设计文档，说明目标、背景和约束，但不会写清全部架构细节、实现步骤和验收标准。系统需要让 Codex 团队继续完成设计、实现、评审和修复。

第一版目标：

- Planner 补齐计划、架构边界、实现里程碑和验收标准。
- Generator 按计划实现代码、补测试、记录验证证据。
- Evaluator 独立评审实现质量，给出可执行的修复意见。
- 通过文件 artifact 在 agent 之间交接，不依赖聊天上下文。
- 通过轻量结构化 action 让 agent 决定下一步唤醒谁，并由 dispatcher 写入 `next_action.json`。
- dispatcher 只做校验、记录、唤醒、暂停、恢复和完成门禁。
- 实现类任务必须在 final evaluator pass 后才能 `completed`。
- 用户只要求设计、分析或计划时，允许停在 `plan.md`，不擅自进入实现。

第一版非目标：

- 不做完整 agent OS。
- 不做复杂 sprint 状态机。
- 不做多 Generator 并行。
- 不做 specialist agent。
- 不做长期 memory。
- 不接入现有 OpenClaw task notification。
- 不复用 `BridgeRuntime.dispatch_once()` 作为 Codex Team runtime。
- 不实现 `fast`、`standard`、`strict`、`auto` 模式系统。

Codex Team 应作为当前 `task-bridge` 仓库中的独立 subsystem 实现。可以复用 CLI、`resolve_home()`、atomic JSON write、测试基建和项目组织，但不要复用现有 task terminal states 作为 Codex Team 的完成语义。

## 2. 核心流程

默认只有三个角色：

```text
planner
generator
evaluator
```

角色关系：

```text
+----------------+
|  User Request  |
+-------+--------+
        |
        v
+------------------------------+
| Planner                      |
| - clarify goal               |
| - define full build spec     |
| - define grading criteria    |
+---------------+--------------+
                |
                | continue
                v
+------------------------------+
| Generator                    |
| - complete build round       |
| - self-check                 |
| - write implementation.md    |
+---------------+--------------+
                |
                | ready_for_review
                v
+------------------------------+
| Evaluator                    |
| - review build round/final   |
| - grade against criteria     |
| - write evaluation.md        |
+---+----------------+---------+
    |                |
    | pass           | needs_fix
    v                v
Generator        Generator
continues        fixes
    |
    | final pass
    v
 completed
```

这张图只是典型实现闭环，不是代码固定流程。合法流转由 agent 输出的 action envelope 决定。

常见路线：

| 场景 | 典型路线 |
| --- | --- |
| 只要计划 | `planner stop -> system` |
| 计划需要独立挑战 | `planner continue -> evaluator`，再进入 `planner/generator/system` |
| 实现任务 | `planner continue -> generator -> ready_for_review -> evaluator -> generator/system` |
| 需求不清 | `generator/evaluator needs_design -> planner`，再由 Planner 判断是否 `ask_user -> user` |
| 设计缺口 | `evaluator needs_design -> planner -> generator` |

代码层只限制不能突破的底线，例如 Generator 不能直接宣布实现完成、final implementation 必须 Evaluator pass、artifact 路径必须可追踪。除此之外，是否做 plan review、是否拆小阶段、是否停在计划阶段，交给 agent 根据任务和 artifact 判断。

## 3. Agent 职责

### 3.1 Planner

Planner 负责把用户输入转成可执行计划。

职责：

- 理解用户目标、非目标、范围、约束和当前阶段。
- 通过读取仓库、文档和上一轮 artifact 补齐必要上下文。
- 产出有野心但可执行的产品/工程 spec，聚焦用户目标、产品能力、交付边界和高层技术设计。
- 定义 `goal_and_scope`、`product_spec`、`architecture_direction`、`engineering_guidance`、`acceptance_and_verification`、`risks_and_open_questions`。
- 判断当前任务应停在计划、请求 plan evaluation、进入实现，还是向用户提问。
- 在 Generator/Evaluator 返回 `needs_design` 时重新规划或澄清问题。

工作规则：

- `goal_and_scope` 必须区分 required scope、later scope、non-goal 和 final condition。
- `required_scope` 是本次 run 必须完成的范围，不是函数级实现计划；小 helper、小测试修复和普通 bug 修复应作为 Generator 内部步骤。
- `engineering_guidance` 保持高层可执行，只描述工作区域、关键依赖、主要风险和推荐切入点，不替 Generator 预先规定函数级、文件级、类级或具体代码结构。
- 写权限边界是 `plan.md` 和必要的规划辅助 artifact；不要修改 repo 源码来完成实现。
- 如果只需要计划且已经完整交付，可以 `action=stop,target=system`。
- 如果需求不清，只有 Planner 可以 `action=ask_user,target=user`。

不负责：

- 主要代码实现。
- 日常 bug 修复。
- 替 Evaluator 宣布质量通过。

Planner 输出：

```text
plan.md
final action envelope
```

`plan.md` 使用少量关键锚点，不把 Markdown 变成 schema。建议包含：

```text
goal_and_scope
product_spec
architecture_direction
engineering_guidance
acceptance_and_verification
risks_and_open_questions
```

`goal_and_scope` 应自然写清 required scope、later scope、non-goal 和 final condition。`product_spec` 应写清完整 build round 必须交付的能力、用户工作流、系统行为和可观察结果。`engineering_guidance` 应写清高层工作区域、关键依赖、主要风险和推荐切入点；Generator 可以改变实现顺序。`acceptance_and_verification` 应写清验收、验证方法和 task-specific grading criteria。

Planner 的设计粒度是完整 build round 的高层工作区域。一个工作区域应该大到覆盖一个功能、模块、用户工作流或风险边界，小到 Generator 可以在一轮长时间 Codex build 中合理推进并交给 Evaluator 独立评审。

`required_scope` 是本次 run 必须完成的范围，不是小 ticket 列表或实现细节清单。长期 roadmap 必须写入 `later_scope`，不能默认纳入本次 final 条件；只有 `final_condition` 满足时，Evaluator 才能 final pass。

跨 agent handoff 有显著时间和 token 成本。Planner 应让 `required_scope` 表达能力边界和交付目标，而不是把 helper、测试修复、普通 bug 修复拆成独立评审点；Generator 应在能力范围内连续推进；Evaluator 应批量评审并给出聚合反馈。

合适的 engineering_guidance 粒度：

```text
- Add Codex run home and file-only handoff artifacts.
- Add dispatcher action parsing and target routing.
- Add planner/generator/evaluator role prompt loading.
- Add evaluator pass gate and fix loop limit.
- Add CLI smoke tests and docs.
```

过粗粒度：

```text
- Implement the whole Codex Team system.
```

过细粒度：

```text
- Add parse_action_envelope().
- Add one if branch for evaluator.
- Rename a local variable.
```

每个高层工作区域应自然写清目标、范围、非范围、验收、验证和 grading criteria。它们是计划表达要素，不是固定字段 schema；Planner 应用自然语言说明为什么这些工作适合由 Generator 连续完成，并适合 Evaluator 做 round-level review。

Planner 默认不强制请求 plan review。只有当计划涉及高风险边界，例如持久化、状态机、权限、安全、公共接口、复杂迁移或里程碑边界不确定时，Planner 才应主动唤醒 Evaluator 做 plan review。

### 3.2 Generator

Generator 负责实现当前计划中的完整 build round。

职责：

- 作为本轮实现 owner，读取 plan/evaluation、补齐代码事实、设计实现、修改仓库并自测。
- 开发前先自主调研本仓库、项目文档和测试；必要时参考开源项目、优秀实现、官方文档或成熟实践。
- 在 plan 边界内连续推进完整 build round，直到 spec 中的所有设计、required scope 和 acceptance 都已实现、自测并可进入 Evaluator review。
- 处理 `blocking_fixes`，并把 `non_blocking_findings`、`scope_status`、`route_decision` 作为下一批输入。
- 在 `implementation.md` 中写清 `build_round_status`、`changes_and_evidence`、`scope_status`、`feedback_addressed` 和 `known_limitations`。

工作规则：

- 开始前确认目标、范围、相关文件、约束、验收标准和验证要求。
- 调研只复用设计思想、接口模式、验证策略和风险控制方法，不直接照搬外部代码，不引入不明许可证风险。
- 自主管理内部任务拆分、实现顺序、自测和修复；不是机械地尽量完成多个 phase，也不要每完成一个小步骤就交给 Evaluator。
- 如果问题仍在 Generator 的实现能力范围内，继续实现和自测，不把 Evaluator 当作每个小步骤后的确认按钮。
- 如果 latest evaluation 的结论是 `continue`，读取 `build_review`、`non_blocking_findings`、`scope_status` 和 `route_decision`，作为下一批工作的输入。
- 如果存在 latest implementation，必须结合 latest evaluation 一起阅读，确认上一轮已完成内容、剩余工作和变更范围。
- 修改 repo 前先查看 git status，并保护已有未归属本轮任务的改动。
- 如果任务表现为 bug、回归、异常或失败链路不清，先做根因调查，再修复和验证。
- 控制 task-scoped 变更范围，不做无关重构或顺手修复。
- 运行必要测试或验证命令，并保留足够证据给 Evaluator 复核。
- 写权限边界是 repo 中当前任务相关文件，以及本轮 `implementation.md`；不要修改 `plan.md` 或 `evaluation.md` 来适配自己的实现。
- 修复轮必须读取 latest evaluation 的 `blocking_fixes` / required fixes，只处理这些修复及其必要验证，不擅自扩大范围或修改验收标准。
- 遇到需求、范围、验收或设计不清时，必须 `action=needs_design,target=planner`。

不负责：

- 修改验收标准来适配自己的实现。
- 自己宣布最终完成。
- 跳过 Evaluator。
- 发现设计问题时继续硬写。
- 直接向用户提问。Generator 不能使用 `ask_user`，必须回到 Planner。

Generator 输出：

```text
attempts/<attempt_id>/implementation.md
final action envelope
```

`implementation.md` 使用少量关键锚点，不把 Markdown 变成 schema。建议包含：

```text
summary
build_round_status
changes_and_evidence
scope_status
feedback_addressed
known_limitations
```

`build_round_status` 应说明完整 spec 是否已经实现并可进入 review；如果不能，说明 blocked 或 interrupted 的证据。`changes_and_evidence` 应自然写清关键改动、必要调研、设计或根因判断、测试和验证证据，以及本轮提交的 commit hash。`scope_status` 应写清 completed scope、remaining scope，以及是否满足 final condition。`feedback_addressed` 应说明上一轮 blocking fixes、non-blocking findings 或 carry-forward risks 如何处理。

Generator 完成完整 spec 并自测后，不输出 `stop`，而是输出 `action=ready_for_review,target=evaluator`。Generator 一次运行期间不唤醒 Evaluator。只有完整 build round 结束并写好固定 artifact 后，才进入 review。

适合进入 `ready_for_review` 的边界至少满足：

- 完整 spec 已实现。
- required scope 已完成或剩余工作仅属于 later scope。
- acceptance 和 verification 已有证据。
- 本轮 task-scoped repo 改动已验证并提交；不能提交的改动已在 `implementation.md` 中说明文件、原因和下一步。
- `implementation.md` 已写清实现、证据、scope 状态和已知限制。

不适合作为 `ready_for_review` 的边界：

- 修改单个 helper。
- 单个测试。
- 单个 lint 或格式修复。
- 普通小 bug。
- 当前实现还不能独立验证。

### 3.3 Evaluator

Evaluator 负责独立评审，不是第二个 Generator。

职责：

- 独立评审 plan 或完整 build round，不接管实现。
- 判断 spec 满足度、`scope_status`、validation 和 blocking/non-blocking 问题。
- 给出 `build_review`、`blocking_fixes`、`non_blocking_findings`、`scope_status` 和 `route_decision`。
- 确保最终 JSON 路由与 `evaluation.md` 的 `route_decision` 一致。
- 遇到设计、验收、final condition 或完整 spec 边界无法判定时回 Planner。

评估规则：

- Evaluator 是 round-level QA，不是频繁打断 Generator 的调度器；主要在完整 build round 后评审。
- 阅读用户需求、`plan.md`、相关 artifact、必要源码、当前 `implementation.md`、代码 diff 和测试证据；不要只读 summary。
- 对照 product spec、acceptance、verification、base criteria、task-specific criteria 和 review focus 进行 grading。
- 检查实现是否满足用户工作流和交付目标、范围是否受控、测试证据是否足够、是否存在回归或过度实现。
- `blocking_fixes` / required fixes 只放阻塞项；非阻塞问题写入 `non_blocking_findings` 或 `route_decision` 的下一批建议。
- 必要时运行最小验证命令；若无法验证，必须把限制和残余风险写清。
- 证据不足、验收不满足或存在 fail 时不能 pass。
- 写权限边界是本轮 `evaluation.md`；不要接管大范围实现，不要修改 repo 源码来替 Generator 完成任务。

不负责：

- 接管大范围实现。
- 只基于 Generator 总结做评审。
- 无限扩大 scope。
- 用泛泛建议阻塞交付。
- 直接向用户提问。需求或验收歧义应回到 Planner。

Evaluator 输出：

```text
plan_evaluation.md                  # plan review
attempts/<attempt_id>/evaluation.md # implementation review
final action envelope
```

`evaluation.md` 是给 Generator、Planner 和用户阅读的审查报告。每个 grade 为什么是 `pass`、`weak`、`fail` 或 `not_applicable`，都必须在 Markdown 中解释清楚，包括证据、风险和修复建议。

第一版不要求 Evaluator 额外写 `evaluation.json`。Evaluator 的最终 envelope 只表达路由结论，完整评审依据和 blocking fixes 以 `evaluation.md` 为准。

`evaluation.md` 使用少量关键锚点，不把 Markdown 变成 schema。建议包含：

```text
summary
build_review
blocking_fixes
non_blocking_findings
scope_status
route_decision
```

`build_review` 应自然写清完整 spec 满足度、base criteria 与 task-specific grading criteria 的逐项结论、验证证据和风险。`scope_status` 应写清 completed scope、remaining scope 和 final condition status。`route_decision` 必须解释最终 JSON 路由为什么是 `needs_fix`、`continue`、`pass` 或 `needs_design`。

Evaluator 默认路由：

```text
blocking issue -> needs_fix,target=generator
required_scope 仍有 remaining_scope、完整 spec 未满足、验收证据不足或 Generator 提前交审 -> needs_fix,target=generator
当前 build round 可接受，且剩余工作仅为 later_scope、非阻塞增强或可接受残余风险 -> continue,target=generator
无 blocking_fixes，final_condition 满足，remaining_scope 为空或仅剩 later_scope -> pass,target=system
plan/acceptance/final_condition/remaining_scope 或完整 spec 边界无法判定 -> needs_design,target=planner
```

下一批建议不是新计划，也不是强制调度脚本。它应写入 `non_blocking_findings` 或 `route_decision`，用于说明当前 build round 可接受后下一批应集中推进什么；不能扩大 `plan.md` 的 `required_scope`。

Evaluator 的最终 action 只能表达以下结论：

```text
pass
needs_fix
needs_design
continue
stop
```

评审类型：

- plan review：评审 Planner 的计划。通过后可进入 Generator，未通过则回到 Planner。
- build round review：评审 Generator 交出的完整 build round。通过但仍有 later scope 或非阻塞建议时可以 `continue -> generator`。
- final review：完整验收。通过后可以 `action=pass,target=system`，run 进入 `completed`。

## 4. 协议

### 4.1 JSON 与 Markdown 边界

稳定原则：

```text
JSON envelope = routing metadata
fixed Markdown artifact = required handoff content
optional artifacts = supplemental context index
```

JSON 只表达下一步动作，不承载完整计划、实现说明、评审理由或 required fixes。详细内容必须写入固定 Markdown artifact：

```text
planner   -> plan.md
generator -> attempts/<n>/implementation.md
evaluator -> plan_evaluation.md 或 attempts/<n>/evaluation.md
```

固定 artifact 的路径由 dispatcher 根据 `run_home`、当前 role 和 run state 推导，不要求 agent 在 JSON 中重复填写。`evaluating_plan` 使用 `plan_evaluation.md`；`evaluating_final` 使用 `attempts/<n>/evaluation.md`。

### 4.2 next_action.json

每个 agent 运行结束时，必须在最终响应中输出轻量 envelope。CodexRunner 通过 `--output-last-message` 捕获该 envelope，dispatcher 校验通过后原子写入 `next_action.json`。

Canonical shape：

```json
{
  "schema_version": 1,
  "status": "completed",
  "summary": "Plan is ready for implementation.",
  "action": "continue",
  "target": "generator",
  "reason": "Plan is actionable.",
  "artifacts": [
    "/absolute/path/to/repo/docs/background.md"
  ]
}
```

字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 必填，当前为 `1` |
| `status` | 当前 agent run 结果：`completed`、`needs_input`、`blocked`、`failed` |
| `summary` | 简短描述本轮完成内容 |
| `action` | 业务动作，说明为什么进入下一步 |
| `target` | 下一个接收方：`planner`、`generator`、`evaluator`、`user`、`system` |
| `reason` | 人类可读原因 |
| `artifacts` | 可选补充 artifact 索引，不是核心交接依据 |

终止保护由 role/action/target 组合、固定 artifact 校验、Evaluator gate 和 `evaluation.md` 中的 `final_condition_status` 共同承担。非最终完成时，Evaluator 应使用 `continue -> generator` 或 `needs_fix -> generator`；只有确认整个 run 已完成时，才允许 `action=pass,target=system`。

`action` 支持：

| action | 典型发起者 | 含义 |
| --- | --- | --- |
| `continue` | Planner / Evaluator | 计划可继续，或当前 build round 可接受但仍需继续 |
| `ready_for_review` | Generator | 完整 build round 已实现、自测并可评审 |
| `pass` | Evaluator | final condition 满足，可结束 |
| `needs_fix` | Evaluator | 实现未通过，Generator 必须读取 `evaluation.md` 修复 |
| `needs_design` | Generator / Evaluator | 当前问题需要 Planner 重新设计或澄清 |
| `ask_user` | Planner | 暂停并向用户提问 |
| `stop` | Planner / Evaluator | 当前 run 可以停止 |

角色限制：

| role | 允许的 action -> target |
| --- | --- |
| Planner | `continue -> generator`，`ask_user -> user`，`stop -> system`，必要时 `continue -> evaluator` 做 plan review |
| Generator | `ready_for_review -> evaluator`，`needs_design -> planner` |
| Evaluator | `continue -> generator`，`pass -> system`，`needs_fix -> generator`，`needs_design -> planner`，`stop -> system` |

第一版不引入 specialist target。专项视角写入 `plan.md`、`implementation.md` 或 `evaluation.md`，必要时也可把补充材料路径放入 `artifacts`。

### 4.3 Artifact 规则

Artifact 分两类：

```text
fixed artifact       协议必需品，代码严格校验
supplemental artifact agent 提供的补充索引，代码只做安全过滤
```

固定 artifact：

| role | 固定输出 | 校验 |
| --- | --- | --- |
| Planner | `run_home/plan.md` | 必须存在、非空、在 `run_home` 内 |
| Generator | `run_home/attempts/<n>/implementation.md` | 必须存在、非空、在当前 attempt 内 |
| Evaluator | `run_home/attempts/<n>/evaluation.md` | 必须存在、非空、在当前 attempt 内 |

补充 `artifacts`：

- 可指向 `run_home` 或 `repo_root` 内的有用文件或目录。
- 只作为下一 agent 的可选阅读索引。
- 不应包含源码文件的替代说明；源码改动应写在 `implementation.md` 的 changed files 小节。
- 不存在、相对路径、越出 `run_home/repo_root` 或明显敏感的路径会被 dispatcher 丢弃并记录 warning，不直接让 run failed。

下一 agent prompt 必须由 dispatcher 明确列出：

```text
必须读取：
  <fixed artifacts>

可选补充 artifacts：
  <filtered supplemental artifacts>
```

### 4.4 metadata.json

`metadata.json` 是 run 的当前索引，不保存完整历史。完整历史写入 append-only `events.jsonl`。

Canonical shape：

```json
{
  "schema_version": 1,
  "run_id": "20260508-001",
  "repo_root": "/absolute/path/to/repo",
  "run_home": "/absolute/path/to/run_home",
  "state": "generating",
  "status": "running",
  "current_owner": "generator",
  "current_attempt": 2,
  "current_milestone_id": "M2",
  "latest_implementation": "/absolute/path/to/run_home/attempts/002/implementation.md",
  "latest_plan_evaluation": "/absolute/path/to/run_home/plan_evaluation.md",
  "latest_evaluation": "/absolute/path/to/run_home/attempts/001/evaluation.md",
  "last_error": null,
  "sessions": {
    "planner": "uuid...",
    "generator:M2": "uuid...",
    "evaluator:M2:attempt-1": "uuid..."
  }
}
```

`sessions` 只是观测字段和未来 resume 扩展依据。真实 handoff 仍以 run home 中的 artifact 为准。

## 5. Grading Criteria

Evaluator 的评审标准采用三层结构：

```text
Base Criteria       系统固定底线
Task Criteria       Planner 根据任务和 build round 补充
Review Focus        Generator 请求或 Evaluator 临时补充的重点
```

不要完全固定，也不要完全交给 Evaluator 临时决定。Base criteria 保证稳定底线，Task criteria 保证任务相关性，Review focus 保证具体风险被看见。

### 5.1 Base Criteria

所有实现任务都应检查：

| Criteria | 含义 |
| --- | --- |
| `goal_alignment` | 是否满足用户目标和 Planner plan |
| `functional_correctness` | 功能是否真实可用 |
| `code_quality` | 是否符合项目结构、可维护性和局部设计要求 |
| `test_evidence` | 测试、命令输出或手动验证证据是否充分 |
| `regression_risk` | 是否引入兼容性、安全、数据、CLI 或行为回归 |
| `scope_control` | 是否遵守 scope / non-scope |

### 5.2 Task Criteria

Task criteria 由 Planner 写入 `plan.md`。它们描述当前任务的具体验收点。

示例：

```text
task_specific:
- final envelope must include action and target.
- generator cannot directly stop the run.
- evaluator pass is required for final completion.
- fixed handoff artifacts must exist.
```

Evaluator 不能随意忽略 task criteria。如果标准本身不完整、互相矛盾或导致错误实现，Evaluator 应输出 `needs_design -> planner`。

### 5.3 Review Focus

Review focus 只能补充检查，不能替代 base criteria 和 task criteria，也不能擅自扩大 scope。

示例：

```text
review_focus:
- security
- regression
- cwd_independence
- backwards_compatibility
```

### 5.4 Grade 与 Gate

每项 criteria 使用：

| Grade | 含义 |
| --- | --- |
| `pass` | 满足要求 |
| `weak` | 基本可接受，但有残余风险或证据不足 |
| `fail` | 不满足要求，必须修复或重新规划 |
| `not_applicable` | 当前评审不适用 |

Gate rules：

```text
final review:
  any fail => cannot pass
  weak allowed only if evaluator records residual risk

build round review:
  fail on task-specific acceptance => needs_fix or needs_design
  weak can continue only if evaluator records carry-forward risk

plan review:
  unclear scope boundary or broken grading criteria => needs_design
```

`evaluation.md` 中必须解释每个 `weak`、`fail` 和关键 `pass` 的证据。dispatcher 不从自由文本推导质量结论，只用最终 envelope 的 `action` 和固定 artifact 存在性做路由门禁。

## 6. Handoff 与 Artifact

### 6.1 Run Home

不同 agent 之间只通过文件 artifact 交互，不依赖聊天上下文，也不直接互相对话。

原则：

```text
Agent 不互相聊天
Agent 只读共享 artifact
Dispatcher 传固定 artifact 绝对路径、过滤后的补充 artifact 和任务指令
```

Handoff 不保存在 Codex 当前工作目录里，因为 Codex 的工作路径可能变化。它应保存在 dispatcher 管理的固定 run home。

推荐 run home：

```text
$TASK_BRIDGE_HOME/codex-team/runs/<run_id>/
```

如果没有设置 `TASK_BRIDGE_HOME`，复用当前 `task-bridge` 默认 home：

```text
~/.openclaw/task-bridge/codex-team/runs/<run_id>/
```

实现上应使用：

```text
resolve_home() / "codex-team" / "runs" / run_id
```

每次唤醒 agent 时，dispatcher 都必须传入两个绝对路径：

```text
repo_root = /absolute/path/to/repo
run_home = /absolute/path/to/run_home
```

Agent 在 `repo_root` 中读写项目代码，在 `run_home` 中读写 handoff artifact。

### 6.2 目录结构

Canonical layout：

```text
<run_home>/
  input.md
  plan.md
  next_action.json
  metadata.json
  events.jsonl
  pending_question.json
  answers.jsonl
  attempts/
    001/
      implementation.md
      evaluation.md
    002/
      implementation.md
      evaluation.md
  artifacts/
    logs/
      planner-001.stdout.log
      planner-001.stderr.log
      generator-001.stdout.log
      evaluator-001.stdout.log
    screenshots/
    test-output/
  schemas/
    planner.schema.json
    generator.schema.json
    evaluator.schema.json
```

说明：

- `input.md` 保存用户原始输入。
- `plan.md` 保存 Planner 当前计划。
- `next_action.json` 保存最新 envelope。
- `events.jsonl` 保存完整路由、暂停、恢复、错误和完成历史。
- `metadata.json` 保存当前索引和状态。
- `pending_question.json` 只在等待用户回答时存在。
- `answers.jsonl` append-only 保存用户回答。
- `attempts/<n>/implementation.md` 和 `attempts/<n>/evaluation.md` 按轮次保存，不覆盖旧 attempt。

多轮 Generator / Evaluator 不能写到同一个 `implementation.md` 或 `evaluation.md`。每一轮写入新的 attempt 目录。`next_action.json` 只是 latest pointer，不能当历史记录。

### 6.3 Prompt 构造

dispatcher 从最新 envelope 生成下一轮 prompt。逻辑是：

```text
1. 读取 action 和 target
2. 校验 role/action/target 组合
3. 根据 target 选择角色 prompt 模板
4. 注入 repo_root、run_home、artifact 目录规则、必须读取的固定 artifact、可选补充 artifact、必须写入的固定 artifact 和最终 envelope 约束
5. 启动 codex exec
```

不要把长篇工作内容塞进 prompt。prompt 只传路径、职责、本轮目标和输出约束。agent 自己读取 artifact。

Prompt 中共享政策应从统一 section 生成，避免同一政策散落成多套措辞：

```text
ARTIFACT_DIRECTORY_SECTION
HANDOFF_ECONOMY_POLICY
BLOCKING_FIX_POLICY
```

role prompt 可以保留必要重复，但 artifact 目录、handoff economy 和 blocking/non-blocking fix 的核心语义必须来自这些共享 section。

唤醒 Generator 的中文 prompt 示例：

```text
你是 Codex Team 的 Generator。

仓库根目录：
  /absolute/path/to/repo

Run home：
  /absolute/path/to/run_home

Run artifact 目录规则：
  input.md：用户原始任务。
  plan.md：Planner 的当前计划。
  plan_evaluation.md：计划评审。
  attempts/<n>/implementation.md：第 n 轮 Generator 实现交接。
  attempts/<n>/evaluation.md：第 n 轮 Evaluator 评审交接。
  next_action.json：上一轮轻量路由 envelope。
  metadata.json：当前 run 索引。
  artifacts/logs/：runner prompt、last-message、stdout/stderr 日志。
  必须优先读取 required files；需要追溯历史时，可按 attempts/<n>/ 顺序查看旧 implementation/evaluation。

你必须先读取：
  /absolute/path/to/run_home/input.md
  /absolute/path/to/run_home/plan.md

如果这是修复轮，还必须读取：
  /absolute/path/to/run_home/attempts/001/implementation.md
  /absolute/path/to/run_home/attempts/001/evaluation.md

可选补充 artifacts：
  /absolute/path/to/repo/docs/background.md

你的职责：
  你是本轮实现 owner，负责读取 plan/evaluation、补齐代码事实、设计实现、修改仓库并自测。
  开发前先自主调研本仓库、项目文档和测试；必要时参考开源项目、优秀实现、官方文档或成熟实践。
  在 plan 边界内连续推进完整 build round，直到 spec 中的所有设计、required_scope 和 acceptance 都已实现、自测并可进入 Evaluator review。
  处理 blocking_fixes，并把 non_blocking_findings、scope_status、route_decision 作为下一批输入。
  在 implementation.md 中写清 build_round_status、changes_and_evidence、scope_status、feedback_addressed 和 known_limitations。

工作规则：
  只复用设计思想、接口模式、验证策略和风险控制方法，不直接照搬外部代码，不引入不明许可证风险。
  自主管理内部任务拆分、实现顺序、自测和修复；不是机械地尽量完成多个 phase，也不要每完成一个小步骤就交给 Evaluator。
  如果问题仍在你的实现能力范围内，继续实现和自测，不要把 Evaluator 当作每个小步骤后的确认按钮。
  如果存在 latest implementation，必须结合 latest evaluation 一起阅读，确认上一轮已完成内容、剩余工作和变更范围。
  如果 latest evaluation 的 route 是 continue，读取 build_review、non_blocking_findings、scope_status 和 route_decision 作为下一批输入。

你必须写入：
  /absolute/path/to/run_home/attempts/002/implementation.md

implementation.md 写作要求：
  Markdown 字段只是关键锚点，不是表格式 schema；用自然语言写清实现判断、证据和剩余风险。
  至少包含：summary、build_round_status、changes_and_evidence、scope_status、feedback_addressed、known_limitations。
  build_round_status 中说明完整 spec 是否已经实现并可进入 review；如果不能，说明 blocked 或 interrupted 的证据。
  changes_and_evidence 中写清关键改动、必要调研、设计或根因判断、测试和验证证据。
  scope_status 中写清 completed scope、remaining scope，以及是否满足 final_condition。

最终响应：
  输出符合轻量 action schema 的 JSON envelope。
  dispatcher 会校验并写入 /absolute/path/to/run_home/next_action.json。

注意：
  不要覆盖旧 attempt。
  不要直接 stop 宣布实现完成。
  只有完整 spec 已实现、自测完成且 implementation.md 已写好时，才用 action=ready_for_review,target=evaluator。
  helper、schema、fixture、CLI 子命令、局部 bug fix、单个测试通过和半成品都不能触发 ready_for_review。
```

唤醒 Evaluator 的中文 prompt 示例：

```text
你是 Codex Team 的 Evaluator。

仓库根目录：
  /absolute/path/to/repo

Run home：
  /absolute/path/to/run_home

你必须先读取：
  /absolute/path/to/run_home/input.md
  /absolute/path/to/run_home/plan.md
  /absolute/path/to/run_home/attempts/002/implementation.md

你的职责：
  作为 round-level QA 独立检查代码 diff、测试证据和完整 build round，不频繁打断 Generator。
  不要把每个小问题都变成单独 needs_fix；blocking_fixes / required_fixes 只放阻塞项。
  非阻塞问题写入 non_blocking_findings 或 route_decision 的下一批建议，减少无意义往返。
  按 base criteria、task criteria 和 review focus 进行 grading。
  final 判断前先检查 final_condition 和 required_scope；本轮 review 通过不等于整个 run 结束。

你必须写入：
  /absolute/path/to/run_home/attempts/002/evaluation.md

evaluation.md 写作要求：
  Markdown 字段只是关键锚点，不是表格式 schema；用自然语言写清评审判断和路由依据。
  至少包含：summary、build_review、blocking_fixes、non_blocking_findings、scope_status、route_decision。
  build_review 中说明完整 spec 满足度、base criteria 与 task-specific grading criteria 的逐项结论、验证证据和风险。
  scope_status 中写清 completed scope、remaining scope 和 final condition status。

最终响应：
  输出符合轻量 action schema 的 JSON envelope。
  dispatcher 会校验并写入 /absolute/path/to/run_home/next_action.json。

注意：
  blocking issue -> action=needs_fix,target=generator。
  required_scope 仍有 remaining_scope、完整 spec 未满足、验收证据不足或 Generator 提前交审 -> action=needs_fix,target=generator。
  当前 build round 可接受，且剩余工作仅为 later_scope、非阻塞增强或可接受残余风险 -> action=continue,target=generator。
  final_condition 满足且 remaining_scope 为空或仅剩 later_scope -> action=pass,target=system。
  无法判定设计、验收、final_condition、remaining_scope 或完整 spec 边界 -> action=needs_design,target=planner。
```

## 7. Dispatcher

Dispatcher 是轻量 harness，不替 agent 做工程判断。

职责：

- 创建 run home。
- 写入 `input.md`、初始化 `metadata.json` 和 `events.jsonl`。
- 启动初始 Planner。
- 接收 agent 输出。
- 校验最终 envelope、固定 artifact 和 role/action/target 组合。
- 过滤补充 artifacts。
- 记录事件和当前状态。
- 根据 `target` 唤醒下一个 agent。
- 控制 fix loop 上限。
- 处理 `ask_user` 暂停和 `answer` 恢复。
- 控制实现类任务的最终完成门禁。
- 向每个 agent 传入 repo root 和 run home 绝对路径。

不负责：

- 生成架构方案。
- 决定代码怎么写。
- 替 Evaluator 做质量判断。
- 判断用户意图属于设计、评审还是实现。
- 自动拆 sprint。
- 自动扩大 scope。

### 7.1 Guardrails

必须校验：

- `action` 合法。
- `target` 合法。
- 当前 role 可以输出该 `action -> target`。
- `reason` 非空。
- 固定 artifact 存在、非空、位于预期 attempt。
- 固定 artifact real path 位于 run home 内，不能通过 `..` 或 symlink escape 越界。
- 补充 `artifacts` 只保留 `run_home` 或 `repo_root` 内的安全路径；无效项记录 warning，不直接失败。
- `metadata.json` 和 `next_action.json` 带 `schema_version`。
- `ask_user` 只能由 Planner 发起。Generator/Evaluator 输出 `ask_user` 必须视为 `InvalidNextAction` 或进入 repair。

完成门禁：

```text
Generator 不能直接 stop -> system 宣布代码实现完成。

标准实现完成路径：
  generator -> ready_for_review -> evaluator -> pass(system)
```

如果 Generator 输出 `stop -> system`，dispatcher 应拒绝该输出或进入 repair，不能直接完成 run。Evaluator 只有在 `evaluation.md` 中确认 final_condition 满足时才应输出 `pass -> system`，不能把中间 review 当作 final completion。

Planner 可以在用户只要求设计、分析或计划时输出 `stop -> system`，前提是已写入 `plan.md`。

高风险任务必须经过 Evaluator：

- 数据迁移。
- 权限、安全、认证。
- 并发、锁、状态机。
- 发布、部署、版本。
- CLI 入口、依赖、配置。
- 持久化格式。
- 大范围重构。

### 7.2 Run State

Run state 用于恢复和校验，不用于替 agent 设计流程。

第一版状态：

```text
created
planning
evaluating_plan
generating
evaluating_final
paused
completed
cancelled
failed
```

状态转换规则：

- `planner -> stop(system)` 可以完成 plan-only run。
- `planner -> evaluator(plan_review)` 进入 `evaluating_plan`。
- `planner -> generator` 进入 `generating`。
- `generator -> ready_for_review` 进入 `evaluating_final`。
- `evaluator continue` on build round 回到 `generating`。
- `evaluator pass` on final 进入 `completed`。
- `planner -> ask_user(user)` 进入 `paused`。
- `answer` 后写入 `answers.jsonl`，再回到 `planning`。
- `cancel` 进入 `cancelled`。
- 不可恢复错误进入 `failed`。

Generator 的 `ready_for_review` 不能映射成现有 `task-bridge` 的 terminal task state。只有 Codex Team run 在 final evaluator pass 后，才可以视为 `completed`。

### 7.3 ask_user 与 answer

Planner 是唯一直接面向用户提问的 agent。Generator 和 Evaluator 如果发现需求、范围、验收、设计或执行路径不清，必须显式输出 `action=needs_design,target=planner`，并在固定 artifact 中说明问题。Planner 读取这些证据后，自行判断是修改计划、继续路由、停止，还是 `ask_user -> user`。

dispatcher 不自动把 Generator/Evaluator 的问题改写成 `ask_user`，也不自动把非法 `ask_user` 改写成 `needs_design -> planner`。agent 负责表达语义，dispatcher 只负责校验和路由。

Generator/Evaluator 回到 Planner 时，建议在固定 artifact 中包含：

```text
issue_type
observed_evidence
why_current_plan_cannot_continue
suggested_question_optional
```

Planner 发起 `ask_user` 时：

```text
action = ask_user
target = user
state = paused
```

dispatcher 必须写入：

```text
pending_question.json
answers.jsonl
events.jsonl
```

`answer` CLI 只允许作用于 `paused` run。它把用户回答 append 到 `answers.jsonl`，归档或清除 `pending_question.json`，写入 `user_answered` event，并把 state 恢复为 `planning`，下一步继续唤醒 Planner。

### 7.4 Fix Loop

默认最多允许：

```text
max_fix_loops = 2
```

当 Evaluator 连续返回 `needs_fix` 超过上限，dispatcher 唤醒 Planner。Planner 需要判断是否拆小任务、修改方案、向用户提问或停止。

用户显式要求跳过评审、停止任务或改变目标时，dispatcher 可以接受，但必须记录 `user_override` event。

## 8. CodexRunner 与 Session 策略

Agent 通过 `codex exec` 启动。第一版需要一个 `CodexRunner` 抽象，统一管理进程生命周期、输出捕获、超时和错误。

`CodexRunner` 负责：

- 构造 `codex exec` 命令。
- 设置工作目录、环境变量和超时。
- 捕获 return code、duration、stdout/stderr tail，并把 stdout/stderr 完整写入 `artifacts/logs/`。
- 尽力提取 Codex session id。提取失败不阻断 run，但记录 warning。
- 超时时终止进程组并写入 runner error。
- 支持 fake/capture mode，便于测试 dispatcher、schema 和 prompt，不真实消耗 Codex token。

第一版真实执行统一给 Codex 最大权限，不提供 read-only/workspace-write 模式开关：

```text
codex exec
  --cd <repo_root>
  --dangerously-bypass-approvals-and-sandbox
  --output-schema <run_home>/schemas/<role>.schema.json
  --output-last-message <run_home>/artifacts/logs/<role>-<seq>.last-message.json
  --json
  -
```

含义：

- prompt 从 stdin 传入，避免 shell quoting 问题。
- 默认保留用户 config 中的 model/provider/auth、MCP 和 plugin 设置。只有在调用方显式配置时，runner 才追加 `--disable <feature>`。
- `--output-schema` 约束最终 envelope。
- `--output-last-message` 捕获最终输出。
- dispatcher 校验通过后，原子写入 `next_action.json`。
- agent 仍负责写 Markdown artifact。
- `--dangerously-bypass-approvals-and-sandbox` 表示 Codex 进程拥有最大权限。harness 的安全边界主要是 run lock、固定 artifact 校验、补充 artifact 过滤、event log、evaluator gate 和用户信任边界，不是 OS sandbox。
- 每次真实执行还会写入 `artifacts/logs/<role>-<seq>.stdout.log` 和 `artifacts/logs/<role>-<seq>.stderr.log`，runner error details 必须包含 log path 和 tail，便于失败排障。

资源约束：

```text
codex_max_global = 1
codex_max_per_run = 1
codex_runner_timeout_seconds = 7200
stdout_stderr_tail_bytes = 100000
```

这适配当前 8G 主机，第一版不要并发启动多个 Codex agent。runner lock 必须非阻塞获取；锁忙时返回 `RunnerLockBusy`，由 CLI 映射为退出码 `4`，不得排队等待前一个 Codex 进程最长运行时间。

### 8.1 Session 策略

`codex exec` 可以新开 non-interactive session，也可以通过 `codex exec resume <SESSION_ID>` 恢复已有 session。

当前 CLI 差异：

```text
codex exec:
  supports --output-schema
  supports --output-last-message
  supports --cd

codex exec resume:
  does not support --output-schema
  supports --output-last-message
  does not support --cd
```

因此第一版把 session 策略分成三层：

```text
normal_agent_run = new
repair = resume same session
work_continuation_resume = future
```

也就是说，第一版正常 Planner / Generator / Evaluator 工作都新开 session，继续使用 `--output-schema` 强约束最终 envelope。跨角色、跨 build round 或继续开发不复用 session。只有当前 agent 的输出或固定 artifact 不满足协议时，才 resume 同一个 session 做有限修复。

默认策略：

```text
default_codex_session_policy = new
evaluator_session_policy = new
resume_policy = repair_protocol_errors
resume_repair_attempts = 2
resume_output_validation = dispatcher_post_validate
work_continuation_resume = future
```

以下情况应新开 session：

- Planner 初次规划。
- Generator 开始新的 build round。
- Evaluator 做 build round review。
- Evaluator 做 final review。
- 任意跨角色切换。
- 用户目标变化。
- Planner 大幅修改 plan。
- 上一 session 明显跑偏或包含过多失败尝试。

Repair 默认先尝试，超限后才进入 failed。修复分三类：

| 类型 | 处理 |
| --- | --- |
| envelope repair | JSON 不合法、缺字段、enum 错、role/action/target 组合非法。resume 当前 agent，只重写最终 envelope，不执行命令、不改文件 |
| artifact repair | 固定 artifact 缺失、为空或明显写错。resume 当前 agent，允许补写或修正固定 Markdown artifact |
| route repair | Evaluator 的评审结论和 route 不一致。resume Evaluator，根据 `evaluation.md` 重写 envelope |

不应通过 repair 解决的情况：

- Evaluator 判断实现质量不通过：应 `needs_fix -> generator`。
- Generator 发现计划不可行：应 `needs_design -> planner`。
- Codex 认证失败、runner 超时、repo 不可访问等系统级错误：记录 runner error；如果 run 已进入 failed 且错误可恢复，用户可以通过 `task-bridge codex-team resume <run_id>` 继续。
- 补充 artifacts 无效：过滤并记录 warning，不触发 repair。

Envelope repair prompt 必须明确禁止继续工作：

```text
你上一轮最终输出不符合 Codex Team action schema。

不要执行命令。
不要修改任何文件。
不要重新实现任务。
只根据已有上下文，重新输出一个合法 JSON envelope。
最终回复必须是纯 JSON，不要包含 Markdown、解释或代码块。

Schema 要求：
- schema_version: 1
- summary: string
- status: completed | needs_input | blocked | failed
- action: continue | ready_for_review | pass | needs_fix | needs_design | ask_user | stop
- target: planner | generator | evaluator | user | system
- reason: non-empty string
- artifacts: optional supplemental paths under run_home or repo_root

上一轮校验错误：
<validator errors>

上一轮无效输出：
<invalid last message>
```

repair 后 dispatcher 必须再次执行同一套 schema 校验和 guardrails。仍失败则进入 `InvalidNextAction` 或 `InvalidFixedArtifact`，不能继续路由。

未来如果启用真实工作续跑 resume，必须满足：

```text
same_role
same_run_id
same_repo_root
same_attempt_chain
```

不要跨项目、跨角色、跨 build round resume。因为 `codex exec resume` 不支持 `--cd`，只能 resume 当初在同一个 `repo_root` 创建的 session。

### 8.2 Runner 错误

Runner 错误必须机器可读，并给用户清晰修复方向：

| 错误 | 典型原因 | 恢复方式 |
| --- | --- | --- |
| `RunnerUnavailable` | `codex` binary 不存在 | 安装或修复 PATH |
| `RunnerAuthFailed` | Codex 未登录或认证失效 | 运行 `codex login` 或修复 auth |
| `RunnerTimeout` | agent 运行超过限制 | 记录日志，允许用户取消或重试 |
| `RunnerFailed` | `codex exec` 非 0 退出 | 展示 return code 和 stderr tail |
| `MissingNextAction` | agent 没有输出合法 envelope | resume 同 session 修复，超限后 failed |
| `InvalidNextAction` | JSON schema/action/target 不合法 | resume 同 session 修复，超限后拒绝 route |
| `InvalidFixedArtifact` | 固定 artifact 缺失、为空或不在预期位置 | resume 当前 agent 补写或修正 |
| `SupplementalArtifactDropped` | 补充 artifact 不存在、越界或不适合传递 | 丢弃并记录 warning，不中断 run |
| `RunnerLockBusy` | 全局或同一 run 已有 Codex runner 活动 | 返回 busy，避免并发破坏和资源挤压 |

## 9. 推荐默认配置

```text
default_start = planner
max_fix_loops = 2
require_evaluator_for_final = true
round_harness = true
allow_generator_direct_stop = false
allowed_targets = planner,generator,evaluator,user,system
allowed_actions = continue,ready_for_review,pass,needs_fix,needs_design,ask_user,stop
base_grading_criteria = goal_alignment,functional_correctness,code_quality,test_evidence,regression_risk,scope_control
allowed_grades = pass,weak,fail,not_applicable
run_home = $TASK_BRIDGE_HOME/codex-team/runs/<run_id>
fixed_artifacts_must_be_inside_run_home = true
supplemental_artifacts_allowed_roots = run_home,repo_root
invalid_supplemental_artifact_policy = drop_and_warn
codex_exec_permission = dangerously_bypass_approvals_and_sandbox
codex_max_global = 1
codex_max_per_run = 1
codex_runner_timeout_seconds = 7200
stdout_stderr_tail_bytes = 100000
default_codex_session_policy = new
evaluator_session_policy = new
resume_policy = repair_protocol_errors
resume_repair_attempts = 2
resume_output_validation = dispatcher_post_validate
work_continuation_resume = future
```

## 10. 最小实现路径

第一阶段只实现可恢复的 Codex Team harness，不接入 daemon/dashboard，不接入 OpenClaw task notification。

推荐实现里程碑：

1. `CodexTeamStore`：默认路径对齐 `resolve_home()`，实现 `metadata.json`、`events.jsonl`、attempt 目录和路径 containment。
2. JSON Schema：实现轻量 action envelope、runner error、`pending_question.json`。
3. Validator：实现 schema 校验、固定 artifact 校验、补充 artifact 过滤和 role/action/target 校验。
4. `CodexRunner` fake/capture mode：先验证 dispatcher 闭环，不真实调用 Codex。
5. Dispatcher policy：实现 run state、event log、evaluator pass gate、fix loop、`ask_user/answer`。
6. CLI：实现 `task-bridge codex-team start/status/show/logs/answer/resume/cancel`，并支持 `--json`。
7. Real `codex exec` command builder：stdin prompt、`--output-schema`、`--output-last-message`、`--json`、最大权限。
8. Repair / resume：当最终 envelope 或固定 artifact 不合格时，resume 同 session 修复 1-2 轮；当 run 因可重试 runner 级错误 failed 时，允许 `codex-team resume` 优先按 thread id 恢复，否则重跑当前 owner，并做 dispatcher post-validate。
9. Role prompts 和 fake-runner E2E，外加现有 `task-bridge` CLI 回归测试。

第一版 CLI 契约：

```text
task-bridge codex-team start --repo-root <path> (--input <text> | --input-file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
task-bridge codex-team status <run_id> [--json]
task-bridge codex-team show <run_id> [--json]
task-bridge codex-team logs <run_id> [--tail <n>] [--json]
task-bridge codex-team answer <run_id> (--text <text> | --file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
task-bridge codex-team resume <run_id> [--runner real|capture] [--max-steps <n>] [--json]
task-bridge codex-team cancel <run_id> --reason <text> [--json]
```

`--max-steps` 统计实际 agent step 次数。`--max-steps 0` 只创建 run，不启动 Codex，并返回 `MaxStepsExceeded`。

现有 CLI 必须保持回归：

```text
task-bridge -h
task-bridge create-job --title "smoke test"
task-bridge daemon-status --json
python -m pytest -q
```

暂缓：

- 完整 sprint contract negotiation。
- 多 Generator 并行。
- specialist agent。
- 复杂事件系统。
- 完整权限系统。
- 长期 memory。
- fast/standard/strict/auto 模式系统。
- auto router。
- 现有 daemon/dashboard 集成。
- OpenClaw task notification 桥接。

## 11. 最终结论

最优第一版不是纯 agent 自由聊天，也不是复杂 harness 状态机，而是：

```text
agent-directed Planner / Generator / Evaluator
+ lightweight action(target,reason)
+ fixed Markdown artifacts
+ file-only handoff in fixed run home
+ dispatcher guardrails
```

Planner 负责避免任务过粗或方向错误。Generator 负责实现和自测。Evaluator 负责形成独立质量压力，并通过 `evaluation.md` 给出可解释、可复查的评审结果。dispatcher 只执行交通规则、固定 artifact 校验、补充 artifact 过滤和有限 repair，不替 agent 做工程判断。
