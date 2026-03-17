# TOOLS.md - Local Notes

本文件只记录这个工作区的本地环境与协作约束。

## Task Bridge

- `task-bridge` 仓库位置：按当前安装与任务配置确定，不要求与 agent 定义位于同一 git repo
- 默认调用方式：
  - `task-bridge ...`
- 如果 PATH 未生效，使用当前 Python 环境中的 `task-bridge` 绝对路径
- 标准执行链路通过 `task-bridge` 完成建单、跟踪与结果回收。

## 当前支持的命令

### job 管理

- `task-bridge create-job --title "<title>"`
- `task-bridge list-jobs --json`
- `task-bridge show-job [job_id] --json`
- `task-bridge use-job <job_id>`
- `task-bridge current-job --json`

### team-leader 常用 task 操作

- 创建任务：
  - `task-bridge create-task --requirement "<self-contained requirement>" --assign code-agent`
  - `task-bridge create-task --requirement "<self-contained requirement>" --assign quality-agent`
- 查看任务：
  - `task-bridge list-tasks [--job <job_id>] [--state queued|running|done|blocked|failed] [--agent <agent>] --json`
  - `task-bridge show-task <task_id> [--job <job_id>] --json`
- 调整任务：
  - `task-bridge update-task <task_id> [--requirement "<text>"] [--assign <agent>] [--job <job_id>]`
  - `task-bridge delete-task <task_id> [--job <job_id>]`

### 调度与状态查看

- `task-bridge worker-status --json`
- `task-bridge queue <agent> --json`

- `update-task --assign` 只适用于 `queued` task。
- `update-task` 至少需要提供 `--requirement` 或 `--assign` 之一。

## Scheduling Guardrails

- 给某个 agent 物化新 task 之前，先执行 `task-bridge queue <agent> --json`
- 如果该 agent 存在 `running_task_id` 或任何 `queued_tasks`，不要继续给它建单
- 同一个 agent 一次只能有一个 task；下一个 task 必须等前一个进入终态后再创建
- 如果某个 task 终态为 `blocked` 或 `failed`，保留原 task，不要覆盖；创建一个新的修复 task 继续推进

## Assign Targets

- 默认派单目标：
  - `code-agent`
  - `quality-agent`
- 你只需要在建 task 时写入合适的 `assigned_agent`。
- `task-bridge` 会处理后续执行流转，并在任务终态时通知你。

## Session Notes

- `task-bridge` 默认只在任务进入终态时通知 `team-leader`
- `complete` 不会立刻自动触发一次独立 CLI 通知；实际通知发生在 `notify` / `daemon` 轮询链路中
- 如果需要中间态，使用 `task-bridge show-task` / `task-bridge list-tasks` / `task-bridge worker-status` 主动查询

## State Files

- 操作事实源：`task-bridge` 的 `jobs/<job_id>/job.json` 与 `tasks/<task_id>.json`
- 本地协调主文件：`memory/work-plan.md`
- 收到新任务时要先确保：
  - `memory/work-plan.md` 已创建或已切换到当前活跃 `job`
  - 当前阶段、计划项、关键证据、风险与下一步已写入 `memory/work-plan.md`
  - 已物化任务的 `job_id`、`task_id`、`assigned_agent`、`state` 已同步到 Work Plan 的运行时区块
