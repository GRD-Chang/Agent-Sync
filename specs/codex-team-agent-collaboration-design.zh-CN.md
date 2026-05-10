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
| - design milestones          |
| - define grading criteria    |
+---------------+--------------+
                |
                | continue
                v
+------------------------------+
| Generator                    |
| - implement one milestone    |
| - self-check                 |
| - write implementation.md    |
+---------------+--------------+
                |
                | candidate_ready
                v
+------------------------------+
| Evaluator                    |
| - review milestone/final     |
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
| 实现任务 | `planner continue -> generator -> candidate_ready -> evaluator -> generator/system` |
| 需求不清 | `generator/evaluator needs_design -> planner`，再由 Planner 判断是否 `ask_user -> user` |
| 设计缺口 | `evaluator needs_design -> planner -> generator` |

代码层只限制不能突破的底线，例如 Generator 不能直接宣布实现完成、final implementation 必须 Evaluator pass、artifact 路径必须可追踪。除此之外，是否做 plan review、是否拆小阶段、是否停在计划阶段，交给 agent 根据任务和 artifact 判断。

## 3. Agent 职责

### 3.1 Planner

Planner 负责把用户输入转成可执行计划。

职责：

- 理解用户目标、非目标和约束。
- 补齐高层架构、模块边界和实现顺序。
- 定义 implementation milestones。
- 定义 acceptance criteria、verification plan 和 task-specific grading criteria。
- 判断当前任务应停在计划、请求 plan review，还是进入实现。
- 在 Evaluator 输出 `needs_design` 时重新规划。
- 统一决定是否向用户提问。

不负责：

- 主要代码实现。
- 日常 bug 修复。
- 替 Evaluator 宣布质量通过。

Planner 输出：

```text
plan.md
final action envelope
```

`plan.md` 建议包含：

```text
goal
non_goal
architecture_summary
implementation_plan
implementation_milestones
acceptance_criteria
verification_plan
risk_flags
open_questions
grading_criteria
```

Planner 的设计粒度是 implementation milestone。一个 milestone 应该大到覆盖一个功能、模块或风险边界，小到 Generator 可以在一轮 Codex run 中完成并交给 Evaluator 独立评审。

合适粒度：

```text
M1: Add Codex run home and file-only handoff artifacts
M2: Add dispatcher action parsing and target routing
M3: Add planner/generator/evaluator role prompt loading
M4: Add evaluator pass gate and fix loop limit
M5: Add CLI smoke tests and docs
```

过粗粒度：

```text
M1: Implement the whole Codex team system
```

过细粒度：

```text
M1: Add parse_action_envelope()
M2: Add one if branch for evaluator
M3: Rename a local variable
```

每个 milestone 建议包含：

```text
milestone_id
goal
scope
non_scope
acceptance
verification
grading_criteria
handoff_condition
```

Planner 默认不强制请求 plan review。只有当计划涉及高风险边界，例如持久化、状态机、权限、安全、公共接口、复杂迁移或里程碑边界不确定时，Planner 才应主动唤醒 Evaluator 做 plan review。

### 3.2 Generator

Generator 负责实现当前计划或当前 milestone。

职责：

- 阅读 `input.md`、`plan.md` 和必要的上一轮评审。
- 阅读代码库并实施变更。
- 修改代码、补测试、运行验证。
- 记录 changed files、tests run、validation evidence 和 known limitations。
- 根据 `evaluation.md` 中的 required fixes 修复问题。
- 发现计划不可行时回到 Planner。
- 发现需求、范围或验收不清时，使用 `action=needs_design,target=planner`，把证据写入固定 artifact 后交回 Planner。

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

`implementation.md` 建议包含：

```text
summary
changed_files
tests_run
validation_evidence
known_limitations
deviations_from_plan
completed_milestone
```

Generator 完成一个 milestone 或最终实现后，不输出 `stop`，而是输出 `action=candidate_ready,target=evaluator`。Generator 一次运行期间不唤醒 Evaluator。只有当本轮工作结束并写好固定 artifact 后，才提交 candidate。

适合作为 milestone candidate 的边界：

- 完成一个独立 feature 或模块边界。
- 改动影响 public API、状态机、权限、数据模型或持久化格式。
- 后续实现会建立在当前设计选择之上。
- Generator 对测试策略或兼容性风险不确定。

不适合作为 milestone candidate 的边界：

- 修改单个 helper。
- 修 lint 或格式。
- 普通单测失败修复。
- 当前实现还不能独立验证。

### 3.3 Evaluator

Evaluator 负责独立评审，不是第二个 Generator。

职责：

- 阅读用户原始需求、`plan.md`、代码 diff 和对应 attempt 的 `implementation.md`。
- 按 base criteria、task criteria 和 review focus 评审。
- 检查实现是否满足验收标准。
- 检查测试证据是否足够。
- 发现回归风险、遗漏、过度实现或范围偏移。
- 必要时运行命令验证或行为验证。
- 在 `evaluation.md` 中输出明确结论、grading 和 required fixes。

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

第一版不要求 Evaluator 额外写 `evaluation.json`。Evaluator 的最终 envelope 只表达路由结论，完整评审依据和 required fixes 以 `evaluation.md` 为准。

Evaluator 的最终 action 只能表达以下结论：

```text
pass
needs_fix
needs_design
continue
stop
```

候选类型：

- milestone candidate：只评审当前 milestone。通过后通常回到 Generator 继续下一阶段，不代表整体完成。
- final candidate：完整验收。通过后可以 `action=pass,target=system`，run 进入 `completed`。
- plan review：评审 Planner 的计划。通过后可进入 Generator，未通过则回到 Planner。

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

固定 artifact 的路径由 dispatcher 根据 `run_home`、当前 role 和 run state 推导，不要求 agent 在 JSON 中重复填写。`evaluating_plan` 使用 `plan_evaluation.md`；`evaluating_milestone` 使用 `attempts/<n>/evaluation.md`。

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

`action` 支持：

| action | 典型发起者 | 含义 |
| --- | --- | --- |
| `continue` | Planner / Evaluator | 计划可继续、milestone 通过后进入下一阶段 |
| `candidate_ready` | Generator | 当前 milestone 或 final candidate 已可评审 |
| `pass` | Evaluator | final candidate 通过，可结束 |
| `needs_fix` | Evaluator | 实现未通过，Generator 必须读取 `evaluation.md` 修复 |
| `needs_design` | Generator / Evaluator | 当前问题需要 Planner 重新设计或澄清 |
| `ask_user` | Planner | 暂停并向用户提问 |
| `stop` | Planner / Evaluator | 当前 run 可以停止 |

角色限制：

| role | 允许的 action -> target |
| --- | --- |
| Planner | `continue -> generator`，`ask_user -> user`，`stop -> system`，必要时 `continue -> evaluator` 做 plan review |
| Generator | `candidate_ready -> evaluator`，`needs_design -> planner` |
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
Task Criteria       Planner 根据任务和 milestone 补充
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

Task criteria 由 Planner 写入 `plan.md` 和 milestone 定义。它们描述当前任务的具体验收点。

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
| `not_applicable` | 当前 milestone 不适用 |

Gate rules：

```text
final candidate:
  any fail => cannot pass
  weak allowed only if evaluator records residual risk

milestone candidate:
  fail on task-specific acceptance => needs_fix or needs_design
  weak can pass only if evaluator records carry-forward risk

plan review:
  unclear milestone boundary or broken grading criteria => needs_design
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
4. 注入 repo_root、run_home、必须读取的固定 artifact、可选补充 artifact、必须写入的固定 artifact 和最终 envelope 约束
5. 启动 codex exec
```

不要把长篇工作内容塞进 prompt。prompt 只传路径、职责、本轮目标和输出约束。agent 自己读取 artifact。

唤醒 Generator 的中文 prompt 示例：

```text
你是 Codex Team 的 Generator。

仓库根目录：
  /absolute/path/to/repo

Run home：
  /absolute/path/to/run_home

你必须先读取：
  /absolute/path/to/run_home/input.md
  /absolute/path/to/run_home/plan.md

如果这是修复轮，还必须读取：
  /absolute/path/to/run_home/attempts/001/evaluation.md

可选补充 artifacts：
  /absolute/path/to/repo/docs/background.md

你的职责：
  按当前 plan 或 required fixes 修改仓库代码，补充必要测试并运行验证。

你必须写入：
  /absolute/path/to/run_home/attempts/002/implementation.md

最终响应：
  输出符合轻量 action schema 的 JSON envelope。
  dispatcher 会校验并写入 /absolute/path/to/run_home/next_action.json。

注意：
  不要覆盖旧 attempt。
  不要直接 stop 宣布实现完成。
  完成后用 action=candidate_ready,target=evaluator。
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
  独立检查代码 diff、测试证据和当前 milestone/final candidate。
  按 base criteria、task criteria 和 review focus 进行 grading。

你必须写入：
  /absolute/path/to/run_home/attempts/002/evaluation.md

最终响应：
  输出符合轻量 action schema 的 JSON envelope。
  dispatcher 会校验并写入 /absolute/path/to/run_home/next_action.json。

注意：
  evaluation.md 写详细判断依据和 required fixes。
  最终 envelope 只写路由结论，例如 action=needs_fix,target=generator 或 action=pass,target=system。
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
  generator -> candidate_ready -> evaluator -> pass(system)
```

如果 Generator 输出 `stop -> system`，dispatcher 应拒绝该输出或转入 Evaluator，不能直接完成 run。

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
evaluating_milestone
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
- `generator -> candidate_ready` 进入 `evaluating_milestone`。
- `evaluator continue` on milestone 回到 `generating`。
- `evaluator pass` on final 进入 `completed`。
- `planner -> ask_user(user)` 进入 `paused`。
- `answer` 后写入 `answers.jsonl`，再回到 `planning`。
- `cancel` 进入 `cancelled`。
- 不可恢复错误进入 `failed`。

Candidate completion 不能映射成现有 `task-bridge` 的 terminal task state。只有 Codex Team run 在 final evaluator pass 后，才可以视为 `completed`。

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

也就是说，第一版正常 Planner / Generator / Evaluator 工作都新开 session，继续使用 `--output-schema` 强约束最终 envelope。跨角色、跨 milestone 或继续开发不复用 session。只有当前 agent 的输出或固定 artifact 不满足协议时，才 resume 同一个 session 做有限修复。

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
- Generator 开始新的 implementation milestone。
- Evaluator 做 milestone review。
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
- Codex 认证失败、runner 超时、repo 不可访问等系统级错误：记录 runner error。
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
- action: continue | candidate_ready | pass | needs_fix | needs_design | ask_user | stop
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
same_milestone_id
same_attempt_chain
```

不要跨项目、跨角色、跨 milestone resume。因为 `codex exec resume` 不支持 `--cd`，只能 resume 当初在同一个 `repo_root` 创建的 session。

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
allow_milestone_candidates = true
milestone_boundary_owner = planner
milestone_adjustment_owner = generator
allow_generator_direct_stop = false
allowed_targets = planner,generator,evaluator,user,system
allowed_actions = continue,candidate_ready,pass,needs_fix,needs_design,ask_user,stop
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
6. CLI：实现 `task-bridge codex-team start/status/show/logs/answer/cancel`，并支持 `--json`。
7. Real `codex exec` command builder：stdin prompt、`--output-schema`、`--output-last-message`、`--json`、最大权限。
8. Repair：当最终 envelope 或固定 artifact 不合格时，resume 同 session 修复 1-2 轮，并做 dispatcher post-validate。
9. Role prompts 和 fake-runner E2E，外加现有 `task-bridge` CLI 回归测试。

第一版 CLI 契约：

```text
task-bridge codex-team start --repo-root <path> (--input <text> | --input-file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
task-bridge codex-team status <run_id> [--json]
task-bridge codex-team show <run_id> [--json]
task-bridge codex-team logs <run_id> [--tail <n>] [--json]
task-bridge codex-team answer <run_id> (--text <text> | --file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
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
- 多 Builder 并行。
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
