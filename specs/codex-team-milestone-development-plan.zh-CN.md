# Codex Team Milestone 开发计划

本文档基于 `specs/codex-team-agent-collaboration-design.zh-CN.md`，把 Codex Team 第一版实现拆成可评审、可恢复、可按轮推进的 implementation milestones。

目标不是重新设计协议，而是给后续开发提供执行顺序、文件边界、验收标准和验证方式。每个 milestone 都应满足：

```text
Generator 可以在一轮 Codex run 中合理完成
Evaluator 可以基于 artifact 和测试证据独立验收
通过后能成为后续 milestone 的稳定基础
```

## 1. 总体边界

第一版只实现可恢复的 Codex Team harness：

```text
src/task_bridge/codex_team/
  store.py
  schemas.py
  validation.py
  runner.py
  dispatcher.py
  cli.py
  prompts.py
  prompt_templates/
```

可以复用：

- `task_bridge.store.resolve_home()`
- `TaskStore._atomic_write_json()` 的实现方式或等价工具函数
- 当前 argparse CLI 入口
- 当前 pytest 测试基建

不能复用：

- `BridgeRuntime.dispatch_once()` 作为 Codex Team runtime
- 现有 task `queued/running/done/blocked/failed` 作为 Codex Team run state
- OpenClaw task terminal notification 作为 Codex Team completion 语义

第一版不做：

- daemon/dashboard 集成
- OpenClaw task notification 桥接
- 多 Generator 并行
- specialist agent
- long-term memory
- `fast/standard/strict/auto` 模式系统
- work-continuation resume

## 2. Milestone 总览

推荐顺序：

| Milestone | 名称 | 主要产物 | Gate |
| --- | --- | --- | --- |
| M1 | Run store 与 artifact 布局 | `CodexTeamStore`、run home、atomic write、event log | 路径和持久化可信 |
| M2 | Schema 与 validator | 轻量 action envelope、固定 artifact、pending question、runner error 校验 | 机器契约可信 |
| M3 | Fake runner 与 prompt 捕获 | `CodexRunner` fake/capture mode、role prompt builder | 不耗 token 验证闭环 |
| M4 | Dispatcher 核心策略 | run state、route、evaluator gate、fix loop | 协作状态可推进 |
| M5 | `ask_user` / `answer` 恢复 | paused run、pending question、answers log | 人机暂停可恢复 |
| M6 | CLI 子命令 | `task-bridge codex-team ...` | 用户可操作和排障 |
| M7 | Real `codex exec` runner | 最大权限命令、stdout/stderr、timeout、session id | 真实 Codex 可运行 |
| M8 | Repair | envelope / 固定 artifact resume 修复 1-2 轮 | 协议错误可自愈 |
| M9 | Role prompts 与 E2E | Planner/Generator/Evaluator prompts、fake E2E、回归测试 | 第一版可交付 |

每个 milestone 通过后，才进入下一个 milestone。不要把 M7 真实 Codex runner 提前到 store、validator、dispatcher 稳定之前。

## 3. M1：Run Store 与 Artifact 布局

### Goal

建立 Codex Team 独立 run store，保证 run home、metadata、events、attempt 目录和 artifact 路径稳定，不依赖 Codex cwd。

### Scope

- 新增 `src/task_bridge/codex_team/store.py`。
- 新增 `src/task_bridge/codex_team/__init__.py`。
- 使用 `resolve_home() / "codex-team" / "runs" / run_id`。
- 初始化 canonical layout：

```text
input.md
metadata.json
events.jsonl
attempts/
artifacts/logs/
artifacts/test-output/
schemas/
```

- 支持创建 run、读取 metadata、更新 metadata、append event、创建 attempt 目录。
- 支持路径 containment 校验辅助函数。
- 使用原子 JSON 写入。

### Non-Scope

- 不实现 dispatcher 路由。
- 不调用 Codex。
- 不实现 CLI。
- 不写 role prompt。

### Expected Files

- `src/task_bridge/codex_team/store.py`
- `src/task_bridge/codex_team/__init__.py`
- `tests/test_codex_team_store.py`

### Acceptance

- 未设置 `TASK_BRIDGE_HOME` 时，默认路径落在 `~/.openclaw/task-bridge/codex-team/runs/<run_id>/`。
- 设置 `TASK_BRIDGE_HOME=/tmp/x` 时，路径落在 `/tmp/x/codex-team/runs/<run_id>/`。
- `metadata.json` 包含 `schema_version`、`run_id`、`repo_root`、`run_home`、`state`、`status`。
- `events.jsonl` append-only；连续写入不会覆盖旧事件。
- attempt 目录使用稳定三位编号，例如 `attempts/001/`。
- artifact real path 必须位于 run home 内，`..` 和 symlink escape 被拒绝。

### Verification

```bash
python -m pytest -q tests/test_codex_team_store.py
```

### Evaluator Focus

- cwd independence
- path containment
- atomic write behavior
- default home 与现有 `task-bridge` 一致性

### Handoff Condition

M1 通过后，M2 可以在稳定 run home 上实现 schema 和 validator。

## 4. M2：Schema 与 Validator

### Goal

把设计文档中的机器契约落成 deterministic validation，避免 dispatcher 依赖自由文本或 prompt-only 约束。

### Scope

- 新增 `src/task_bridge/codex_team/schemas.py`。
- 新增 `src/task_bridge/codex_team/validation.py`。
- 定义并校验：
  - 轻量 action envelope
  - 固定 artifact
  - 补充 artifact 过滤
  - `pending_question.json`
  - runner error
- 校验合法 enum：
  - run state
  - agent status
  - action
  - target
- 校验 `schema_version=1`。
- 校验 role/action/target 组合。

### Non-Scope

- 不生成 prompt。
- 不执行 route。
- 不实现 fake runner。

### Expected Files

- `src/task_bridge/codex_team/schemas.py`
- `src/task_bridge/codex_team/validation.py`
- `tests/test_codex_team_validation.py`

### Acceptance

- 缺少 `schema_version` 的 envelope 被拒绝。
- 非法 `action`、`target`、空 `reason` 被拒绝。
- 非法 role/action/target 组合被拒绝。
- 固定 artifact 缺失、为空或越出 run home 被拒绝。
- 补充 artifact 不存在、越界或不适合传递时被过滤并记录 warning，不直接 failed。
- validator 错误包含机器可读 code 和人可读 message。

### Verification

```bash
python -m pytest -q tests/test_codex_team_validation.py
```

### Evaluator Focus

- schema strictness
- evaluator gate authority
- error model 是否足够给 CLI 展示
- 是否避免 Markdown parsing

### Handoff Condition

M2 通过后，M3 可以让 fake runner 产出 envelope，并由 validator 接管校验。

## 5. M3：Fake Runner 与 Prompt 捕获

### Goal

先在不调用真实 Codex 的情况下验证 runner 边界、prompt 构造输入、stdout/stderr/log artifact 形态。

### Scope

- 新增 `src/task_bridge/codex_team/runner.py`。
- 定义 `CodexRunner` 抽象和 `RunnerResult`。
- 实现 fake runner：
  - 输入预置 envelope / artifacts。
  - 返回 return code、duration、stdout tail、stderr tail。
  - 可模拟 timeout、missing output、invalid JSON。
- 实现 capture runner：
  - 不执行 Codex。
  - 把 prompt 写入 `artifacts/logs/<role>-<seq>.prompt.txt`。
  - 把预期 output path 写入 logs。
- 记录 runner error shape。

### Non-Scope

- 不调用 `codex exec`。
- 不做 dispatcher 完整状态机。
- 不实现 CLI。

### Expected Files

- `src/task_bridge/codex_team/runner.py`
- `tests/test_codex_team_runner.py`

### Acceptance

- fake runner 可以返回合法 envelope。
- fake runner 可以模拟 `RunnerTimeout`、`RunnerFailed`、`MissingNextAction`。
- capture runner 生成 prompt log，且不启动外部进程。
- runner result 不直接修改 run state，只返回 dispatcher 可消费的数据。

### Verification

```bash
python -m pytest -q tests/test_codex_team_runner.py
```

### Evaluator Focus

- runner 与 dispatcher 解耦
- 错误是否机器可读
- 是否适合低资源主机测试

### Handoff Condition

M3 通过后，M4 可以用 fake runner 驱动 dispatcher 状态转换。

## 6. M4：Dispatcher 核心策略

### Goal

实现 Codex Team 的核心协作闭环：创建 run、启动 Planner、校验输出、记录 event、路由下一角色、执行 evaluator gate 和 fix loop。

### Scope

- 新增 `src/task_bridge/codex_team/dispatcher.py`。
- 支持 run state：

```text
created
planning
evaluating_plan
generating
evaluating_milestone
evaluating_final
completed
failed
```

- 支持 route：
  - `planner -> generator`
  - `planner -> evaluator` for plan review
  - `planner -> stop(system)` for plan-only
  - `generator -> needs_design(planner)` for clarification, design issue, or infeasible plan
  - `generator -> candidate_ready(evaluator)`
  - `evaluator continue milestone -> generator`
  - `evaluator pass final -> completed`
  - `evaluator needs_fix -> generator`
  - `evaluator needs_design -> planner`
- 实现 generator direct `stop -> system` 拒绝。
- 实现 Generator/Evaluator direct `ask_user` 拒绝，不自动改写 route。
- 实现 `max_fix_loops=2`。
- 每次 transition 写 `events.jsonl`。
- 更新 `metadata.json` latest pointers。

### Non-Scope

- 不处理 `ask_user/answer`。
- 不接真实 Codex。
- 不接 CLI。
- 不做 daemon。

### Expected Files

- `src/task_bridge/codex_team/dispatcher.py`
- `tests/test_codex_team_dispatcher.py`

### Acceptance

- fake planner 输出 `continue -> generator` 后 state 进入 `generating`。
- fake planner 输出 `continue -> evaluator` 后 state 进入 `evaluating_plan`，评审写入 `plan_evaluation.md`，不占用 `attempts/<n>/evaluation.md`。
- fake generator 输出 milestone candidate 后 state 进入 `evaluating_milestone`。
- fake evaluator milestone pass 后 state 回到 `generating`。
- fake evaluator final pass 后 state 进入 `completed`。
- fake evaluator needs_fix 未超过上限时回 Generator。
- needs_fix 超过上限后回 Planner。
- fake generator 输出 `needs_design -> planner` 时 state 回到 `planning`。
- fake evaluator 输出 `needs_design -> planner` 时 state 回到 `planning`。
- generator direct stop 不会完成 run。
- Generator/Evaluator direct `ask_user` 会产生 `InvalidNextAction`，dispatcher 不自动转成 Planner route。
- 每个 transition 都有 event 记录。

### Verification

```bash
python -m pytest -q tests/test_codex_team_dispatcher.py
```

### Evaluator Focus

- final completion gate
- event log completeness
- fix loop boundary
- 与现有 task terminal states 隔离

### Handoff Condition

M4 通过后，M5 可以补齐 paused/resume 人机交互，不影响核心 route。

## 7. M5：ask_user / answer 恢复

### Goal

实现 Planner 面向用户提问的暂停和恢复，确保用户回答落盘，不依赖聊天上下文。

### Scope

- 扩展 store：
  - `pending_question.json`
  - `answers.jsonl`
- 扩展 dispatcher：
  - `planner -> ask_user(user)` 进入 `paused`
  - `answer` 后恢复到 `planning`
- Generator/Evaluator 直接 `ask_user` 一律拒绝为 `InvalidNextAction`；dispatcher 不自动改写 route。
- Generator/Evaluator 需要用户判断时，必须显式 `needs_design -> planner`，由 Planner 自行决定是否 `ask_user`。
- `answer` 写入 `answers.jsonl` 和 `events.jsonl`。

### Non-Scope

- 不实现复杂多问题表单 UI。
- 不接 dashboard。
- 不让 Generator/Evaluator 直接向用户提问。

### Expected Files

- `src/task_bridge/codex_team/store.py`
- `src/task_bridge/codex_team/dispatcher.py`
- `tests/test_codex_team_pause_resume.py`

### Acceptance

- Planner 发起 `ask_user` 后 state 为 `paused`。
- `pending_question.json` 包含 `schema_version`、`run_id`、`question`、`created_at`。
- Generator/Evaluator direct `ask_user` 被拒绝，且不会自动创建 `pending_question.json`。
- Generator/Evaluator `needs_design -> planner` 后不进入 `paused`，而是回到 `planning`。
- 非 paused run 调用 answer 被拒绝。
- answer 后 `answers.jsonl` 追加用户回答。
- answer 后下一轮 owner 是 Planner。
- answer 不覆盖历史 answers。

### Verification

```bash
python -m pytest -q tests/test_codex_team_pause_resume.py
```

### Evaluator Focus

- paused state recovery
- user answer durability
- Planner-only question ownership

### Handoff Condition

M5 通过后，M6 可以暴露 CLI，不需要 CLI 自己理解内部状态细节。

## 8. M6：CLI 子命令

### Goal

把 Codex Team 暴露为 `task-bridge codex-team ...`，同时不破坏现有 task-bridge CLI。

### Scope

- 新增 `src/task_bridge/codex_team/cli.py`。
- 在 `src/task_bridge/cli.py` 中添加嵌套 subparser。
- 支持：

```text
task-bridge codex-team start --repo-root <path> (--input <text> | --input-file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
task-bridge codex-team status <run_id> [--json]
task-bridge codex-team show <run_id> [--json]
task-bridge codex-team logs <run_id> [--tail <n>] [--json]
task-bridge codex-team answer <run_id> (--text <text> | --file <path>) [--runner real|capture] [--no-run] [--max-steps <n>] [--json]
task-bridge codex-team cancel <run_id> --reason <text> [--json]
```

- CLI 只调用 Codex Team dispatcher/store API，不直接操作内部 JSON。
- `--max-steps` 统计实际 agent step 次数。`--max-steps 0` 只创建 run 并返回 `MaxStepsExceeded`，不得启动任何 Codex 进程。
- 定义退出码：
  - `0` 成功
  - `2` 参数或状态非法
  - `3` run 不存在
  - `4` runner lock busy
  - `5` runner unavailable/failed
- 所有子命令支持机器可读 JSON 输出。

### Non-Scope

- 不接 dashboard。
- 不接 daemon。
- 不做 shell completion。

### Expected Files

- `src/task_bridge/codex_team/cli.py`
- `src/task_bridge/cli.py`
- `tests/test_codex_team_cli.py`
- 必要时更新 `pyproject.toml` package data，但第一版纯 Python 通常不需要。

### Acceptance

- `task-bridge -h` 仍可用。
- `task-bridge codex-team -h` 可显示子命令。
- `start` 能在隔离 `TASK_BRIDGE_HOME` 下创建 run。
- `status/show/logs/answer/cancel` 能返回稳定 JSON。
- 现有 `create-job`、`daemon-status` 不受影响。

### Verification

```bash
TASK_BRIDGE_HOME=/tmp/task-bridge-codex-team-cli python -m pytest -q tests/test_codex_team_cli.py tests/test_cli.py
task-bridge -h
task-bridge daemon-status --json
```

### Evaluator Focus

- backward compatibility
- CLI help discoverability
- JSON output stability
- 不把 dashboard 依赖引入基础 CLI 路径

### Handoff Condition

M6 通过后，M7 可以在 CLI 背后接入真实 Codex runner。

## 9. M7：Real `codex exec` Runner

### Goal

实现真实 `codex exec` 启动逻辑，并保持进程生命周期、日志、超时和错误可观测。

### Scope

- 扩展 `src/task_bridge/codex_team/runner.py`。
- 构造命令：

```text
codex exec
  --cd <repo_root>
  --dangerously-bypass-approvals-and-sandbox
  --output-schema <run_home>/schemas/<role>.schema.json
  --output-last-message <run_home>/artifacts/logs/<role>-<seq>.last-message.json
  --json
  -
```

- prompt 从 stdin 输入。
- 默认保留用户 config 中的 model/provider/auth、MCP 和 plugin 设置。只有在调用方显式配置时，runner 才追加 `--disable <feature>`。
- 捕获 stdout/stderr tail。
- 写入 `artifacts/logs/<role>-<seq>.stdout.log` 和 `artifacts/logs/<role>-<seq>.stderr.log`。
- 支持 timeout，并终止进程组。
- 尽力提取 session id，失败只记录 warning。
- 支持 `codex_max_global=1`、`codex_max_per_run=1` 的锁边界。

### Non-Scope

- 不实现 work-continuation resume。
- 不提供 sandbox mode 切换。
- 不并发运行多个 Codex agent。

### Expected Files

- `src/task_bridge/codex_team/runner.py`
- `tests/test_codex_team_real_runner_command.py`

### Acceptance

- command builder 输出参数顺序稳定，可单测断言。
- prompt 通过 stdin，不拼进 shell 字符串。
- timeout 生成 `RunnerTimeout`。
- `codex` 不存在时生成 `RunnerUnavailable`。
- 非 0 exit 生成 `RunnerFailed`，包含 return code 和 stderr tail。
- 不使用 `shell=True`。
- 真实 runner 启动 `codex exec` 时使用非阻塞方式获取全局锁和 run 级锁；锁忙时返回 `RunnerLockBusy`，不等待前一个 Codex 进程结束。
- `RunnerFailed`、`RunnerTimeout` 和 `MissingNextAction` 的 error details 包含 stdout/stderr log 路径和 tail。

### Verification

```bash
python -m pytest -q tests/test_codex_team_real_runner_command.py
codex exec --help
```

只在 M1-M6 通过后做真实 smoke。真实 smoke 第一轮只读，不做代码修改。

### Evaluator Focus

- subprocess safety
- timeout/process group handling
- low-memory host friendliness
- command 与设计文档一致性

### Handoff Condition

M7 通过后，M8 可以在真实 Codex 输出或固定 artifact 不符合协议时做有限 repair。

## 10. M8：Repair

### Goal

当 agent 最终 envelope、固定 artifact 或 route 语义不符合协议时，允许 resume 同 session 修复 1-2 轮，再决定是否 failed。

### Scope

- 增加 `resume_policy = repair_protocol_errors`。
- 支持 `resume_repair_attempts = 2`。
- 构造 repair prompt，明确：
  - envelope repair 不执行命令、不修改文件、不重新实现任务
  - artifact repair 只补写或修正固定 Markdown artifact
  - route repair 根据已有固定 artifact 重写合法 envelope
- repair 后仍走完整 dispatcher post-validate。
- 补充 artifact 无效只过滤并记录 warning，不触发 repair。

### Non-Scope

- 不支持继续开发的 resume。
- 不跨角色、跨 milestone、跨 repo resume。
- 不让 Evaluator 通过 repair 修改业务代码。

### Expected Files

- `src/task_bridge/codex_team/runner.py`
- `src/task_bridge/codex_team/dispatcher.py`
- `src/task_bridge/codex_team/prompts.py`
- `tests/test_codex_team_envelope_repair.py`

### Acceptance

- JSON parse failed 可触发一次 repair。
- 缺少 `schema_version` 可触发一次 repair。
- 缺少 `action` 或 `target` 可触发 repair。
- 固定 artifact 缺失或为空可触发 artifact repair。
- role/action/target 组合不合法可触发 route repair。
- repair 后合法则继续 route。
- repair 后仍非法则 run 进入 failed 或记录 `InvalidNextAction`。
- 补充 artifact 无效不会 failed，只记录 dropped artifact warning。

### Verification

```bash
python -m pytest -q tests/test_codex_team_envelope_repair.py
```

### Evaluator Focus

- repair 范围是否严格
- 是否避免让 resume 继续工作
- post-validation 是否完整复用

### Handoff Condition

M8 通过后，M9 可以完成 prompts 和端到端 fake/real smoke。

## 11. M9：Role Prompts 与 E2E

### Goal

补齐 Planner / Generator / Evaluator prompts，验证完整 fake-runner E2E，并回归现有 `task-bridge` CLI。

### Scope

- 新增 role prompt 模板：
  - planner
  - generator
  - evaluator
  - envelope repair
- 模板注入：
  - repo root
  - run home
  - required reads
  - required writes
  - final envelope schema 约束
  - role-specific guardrails
- fake-runner E2E：
  - Planner 产出 `plan.md`
  - Generator 产出 `attempts/001/implementation.md`
  - Evaluator needs_fix
  - Generator 产出 `attempts/002/implementation.md`
  - Evaluator final pass
  - run completed
- 回归现有 CLI 和 pytest。

### Non-Scope

- 不接 dashboard。
- 不接 OpenClaw notification。
- 不验证真实大规模代码生成质量。

### Expected Files

- `src/task_bridge/codex_team/prompts.py`
- `src/task_bridge/codex_team/prompt_templates/planner.txt`
- `src/task_bridge/codex_team/prompt_templates/generator.txt`
- `src/task_bridge/codex_team/prompt_templates/evaluator.txt`
- `src/task_bridge/codex_team/prompt_templates/envelope_repair.txt`
- `tests/test_codex_team_e2e.py`
- `pyproject.toml` package data，如 prompt templates 需要随包安装

### Acceptance

- prompt 不包含长篇 artifact 内容，只传路径、职责和输出约束。
- Generator prompt 明确禁止直接 `stop -> system` 宣布实现完成。
- Generator prompt 明确禁止直接 `ask_user`，遇到需求、范围、验收或设计不清时必须 `needs_design -> planner`。
- Evaluator prompt 明确禁止直接 `ask_user`，遇到设计缺口、验收歧义或 blocked 时必须 `needs_design -> planner` 或按规则 `stop -> system`。
- Prompt 明确区分必须读取的固定 artifact 和可选补充 artifact。
- fake-runner E2E 可以完整完成 run。
- `events.jsonl` 包含从 created 到 completed 的完整 transition。
- 现有 `task-bridge` CLI 回归通过。

### Verification

```bash
python -m pytest -q tests/test_codex_team_e2e.py tests/test_cli.py tests/test_runtime.py
task-bridge -h
task-bridge create-job --title "smoke test"
task-bridge daemon-status --json
```

### Evaluator Focus

- role boundary clarity
- artifact-only handoff
- end-to-end recovery evidence
- existing CLI regression

### Handoff Condition

M9 通过后，第一版 Codex Team harness 可以进入真实小任务试运行。

## 12. 跨 Milestone Gate

每个 milestone 的 Evaluator 都必须检查：

```text
base:
  goal_alignment
  functional_correctness
  code_quality
  test_evidence
  regression_risk
  scope_control
```

通用必查项：

- 是否保持 `src/task_bridge/codex_team/` 隔离。
- 是否没有破坏现有 `task-bridge` CLI。
- 是否没有引入 daemon/dashboard 强耦合。
- 是否没有让 Codex Team completion 映射到现有 task terminal state。
- 是否有足够单测覆盖失败路径。
- 是否遵守 8G 主机资源约束，默认不并发启动 Codex agent。

若某个 milestone 修改 `src/task_bridge/cli.py`、`pyproject.toml` 或 package data，必须额外回归：

```bash
task-bridge -h
python -m pytest -q tests/test_cli.py
```

若某个 milestone 修改 runner 或 dispatcher，必须额外回归：

```bash
python -m pytest -q tests/test_codex_team_dispatcher.py tests/test_codex_team_runner.py
```

## 13. 推荐开发节奏

第一轮建议只做到 M1-M4：

```text
M1 store
M2 validator
M3 fake runner
M4 dispatcher core
```

这四个 milestone 通过后，系统已经能在 fake runner 下跑通核心协作闭环。此时再进入 M5-M6，把暂停恢复和 CLI 暴露给用户。最后再做 M7-M9，把真实 Codex、repair 和 prompts 接上。

不要从真实 `codex exec` 开始。真实 Codex runner 会引入认证、进程、权限、超时和 token 消耗问题；如果 store、schema、dispatcher 尚未稳定，排障成本会被放大。

## 14. 最终交付定义

第一版可交付的定义：

- `task-bridge codex-team start/status/show/logs/answer/cancel` 可用。
- fake-runner E2E 能稳定完成 final evaluator pass。
- real `codex exec` 能完成最小只读 Planner smoke。
- 所有 Codex Team run artifact 都落在 run home。
- `events.jsonl` 能解释每次路由、暂停、恢复、错误和完成。
- Generator final candidate 不能绕过 Evaluator。
- Evaluator final pass 是唯一实现类 run completed gate。
- 现有 `task-bridge` CLI、daemon status 和基础测试不回归。
