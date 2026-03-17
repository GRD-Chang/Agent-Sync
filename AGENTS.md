# Repository Notes

## Repo

- `task-bridge` 仓库根目录：本仓库根目录
- `task-bridge` 是 Python 包，不需要单独构建二进制；CLI 入口定义在 `pyproject.toml`
- 如果任务涉及 `task-bridge` 的代码、测试、安装或 CLI 验证，优先在 `task-bridge` 仓库根目录执行

## Update Flow

- 日常代码更新直接修改当前仓库源码
- 当前安装方式是 editable install；因此修改 `src/task_bridge/**` 后，通常不需要重新安装
- 如果修改了 `pyproject.toml`、依赖、console script 入口或包元数据，再重新安装：
  - `cd <repo-root>`
  - `python -m pip install -e .`

## CLI Path

- 优先直接执行裸命令：`task-bridge ...`
- OpenClaw agent 通过 Gateway 的 `exec` 运行命令；是否能直接使用裸命令，取决于 Gateway `exec` 的 PATH
- 当前已采用的解决方案：
  - 在 `~/.openclaw/openclaw.json` 中配置 `tools.exec.pathPrepend=["<python-bin-dir>"]`
  - 因此 OpenClaw agent 现在应优先直接使用裸命令：`task-bridge ...`
- 若怀疑当前环境未生效，先验证：
  - `command -v task-bridge`
  - `task-bridge -h`
- 若裸命令仍不可用，再退回绝对路径：
  - `<python-bin-dir>/task-bridge`

## OpenClaw Integration

- OpenClaw agent 使用 `task-bridge` 的推荐方式：
  - 直接执行裸命令 `task-bridge`
  - 若失败，再使用当前 Python 环境中的绝对路径 `<python-bin-dir>/task-bridge`
- 如果修改了 `~/.openclaw/openclaw.json` 中与 `tools.exec.pathPrepend` 相关的配置，需要重启 Gateway：
  - `systemctl --user restart openclaw-gateway.service`
- 仅修改 `task-bridge` 仓库源码时，不需要重启 Gateway

## Validation

- CLI 可用性验证：
  - `task-bridge -h`
- 测试建议在仓库根目录执行：
  - `cd <repo-root>`
  - `PYTHONPATH=src pytest -q`

## Safe E2E Testing

- 如果只是验证 `task-bridge` 逻辑，不需要真实触达 `team-leader`，优先使用隔离模式：
  - 设置独立 `TASK_BRIDGE_HOME`，例如 `/tmp/task-bridge-test-<marker>`
  - 使用 `TASK_BRIDGE_CAPTURE_FILE` 或自定义 `sender` stub
  - 这样可以验证 `notify` / `follow-up` 逻辑，且不会给真实 agent 发消息

- 如果必须验证真实投递链路，但又不能影响现有 `team-leader` 工作，必须遵守以下规则：
  - 绝对不要使用默认数据目录 `~/.openclaw/task-bridge`
  - 绝对不要复用现有真实 job
  - 必须使用独立 `TASK_BRIDGE_HOME=/tmp/task-bridge-live-<marker>`
  - job 标题、task requirement、task result 中都必须带唯一标记，如 `[TEST_IGNORE] TB_E2E_20260314_223632`
  - 消息正文必须明确写明：这是测试通知，请忽略，不要创建任何真实 task
  - 如果要验证 `detail_path`，先在 task 的 `detail_path` 位置写入真实 `detail.md`
  - 如果要验证 unresolved `follow-up`，在同一测试 job 下不要创建新 task
  - 测试结束后删除该隔离目录

- 真实投递验证的推荐流程：
  - 1. `TASK_BRIDGE_HOME` 指向 `/tmp/task-bridge-live-<marker>`
  - 2. 创建测试 job / task，内容带 `[TEST_IGNORE] <marker>`
  - 3. 如需测 `detail_path`，写入 `detail.md`
  - 4. 将 task 标记为 `done` / `blocked` / `failed`
  - 5. 调用 `notify` 或 `notify_updates()`
  - 6. 去 `~/.openclaw/agents/team-leader/sessions/*.jsonl` 搜索 marker，确认 `[TASK_UPDATE]` 已真实进入会话
  - 7. 如需测 `follow-up`，保持该 job 下无新 task；为了加速测试，可以只在隔离 home 中把 `_scheduler.final_notified_at` / `_scheduler.leader_followup_due_at` 改成历史时间，再调用 `send_due_leader_unresolved_followups()` 或跑一轮 `daemon`
  - 8. 再次搜索 `~/.openclaw/agents/team-leader/sessions/*.jsonl`，确认 `[TASK_FOLLOWUP_REQUIRED]` 已真实进入会话

- 重要边界：
  - “真实投递链路验证”不等于“零外部影响”
  - 只要真实给 `team-leader` 发消息，就一定会产生一条测试消息
  - 上述做法的目标是：不污染现有真实 job，不诱导 `team-leader` 创建真实 task，并且让其能基于 marker 明确识别并忽略测试
