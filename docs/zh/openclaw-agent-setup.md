# OpenClaw Agent 配置

目标：

- 用 OpenClaw CLI 创建 `team-leader`、`code-agent`、`quality-agent`
- 把本仓库里的 agent 定义迁过去
- 安装并验证 `task-bridge`
- 配置 `tools.exec.pathPrepend`，让 agent 可以直接执行 `task-bridge`

参考：

- <https://docs.openclaw.ai/concepts/agent-workspace>
- <https://docs.openclaw.ai/cli/agents>
- <https://docs.openclaw.ai/tools/exec>

## 1. 创建 3 个 agent

先确认 OpenClaw CLI 可用：

```bash
openclaw --help
openclaw agents --help
```

创建 3 个独立 workspace：

```bash
openclaw agents add team-leader --non-interactive --workspace ~/.openclaw/workspaces/team-leader
openclaw agents add code-agent --non-interactive --workspace ~/.openclaw/workspaces/code-agent
openclaw agents add quality-agent --non-interactive --workspace ~/.openclaw/workspaces/quality-agent
```

验证：

```bash
openclaw agents list --json
```

## 2. 迁移本仓库里的 agent 定义

本仓库已经包含：

- `agents/team-leader/*`
- `agents/code-agent/*`
- `agents/quality-agent/*`
- `skills/local/team-leader-orchestrator/SKILL.md`
- `skills/coding-agent/SKILL.md`

把这些文件复制到各自 workspace：

```bash
REPO_ROOT=/path/to/task-bridge

for agent in team-leader code-agent quality-agent; do
  mkdir -p "$HOME/.openclaw/workspaces/$agent/memory"
  cp "$REPO_ROOT/agents/$agent/AGENTS.md" "$HOME/.openclaw/workspaces/$agent/"
  cp "$REPO_ROOT/agents/$agent/SOUL.md" "$HOME/.openclaw/workspaces/$agent/"
  cp "$REPO_ROOT/agents/$agent/USER.md" "$HOME/.openclaw/workspaces/$agent/"
  cp "$REPO_ROOT/agents/$agent/IDENTITY.md" "$HOME/.openclaw/workspaces/$agent/"
  cp "$REPO_ROOT/agents/$agent/TOOLS.md" "$HOME/.openclaw/workspaces/$agent/"
done
```

同步 identity：

```bash
for agent in team-leader code-agent quality-agent; do
  openclaw agents set-identity --workspace "$HOME/.openclaw/workspaces/$agent" --from-identity
done
```

复制 skill：

```bash
mkdir -p "$HOME/.openclaw/workspaces/team-leader/skills/team-leader-orchestrator"
cp "$REPO_ROOT/skills/local/team-leader-orchestrator/SKILL.md" \
  "$HOME/.openclaw/workspaces/team-leader/skills/team-leader-orchestrator/SKILL.md"

for agent in code-agent quality-agent; do
  mkdir -p "$HOME/.openclaw/workspaces/$agent/skills/coding-agent"
  cp "$REPO_ROOT/skills/coding-agent/SKILL.md" \
    "$HOME/.openclaw/workspaces/$agent/skills/coding-agent/SKILL.md"
done
```

## 3. 安装 `task-bridge`

本项目是 Python 包，通常不需要单独编译二进制。推荐直接安装：

```bash
cd /path/to/task-bridge
python -m pip install -e .
```

验证：

```bash
command -v task-bridge
task-bridge -h
```

如果只是改了 `src/task_bridge/**`，editable install 一般不需要重装。

如果你确实要产出安装包，再执行：

```bash
cd /path/to/task-bridge
python -m pip install build
python -m build
```

## 4. 配置 `tools.exec.pathPrepend`

先找到 `task-bridge` 所在目录：

```bash
dirname "$(command -v task-bridge)"
```

写入 OpenClaw 配置：

```bash
TASK_BRIDGE_BIN_DIR="$(dirname "$(command -v task-bridge)")"
openclaw config set tools.exec.pathPrepend "[\"$TASK_BRIDGE_BIN_DIR\"]"
```

验证：

```bash
openclaw config get tools.exec.pathPrepend
```

如果刚改了 `~/.openclaw/openclaw.json`，重启 Gateway：

```bash
systemctl --user restart openclaw-gateway.service
```

## 5. 配置飞书权限并写入 `chat_id`

参考飞书官方文章：

- <https://www.feishu.cn/content/article/7613711414611463386>

按文中步骤安装飞书插件后，先在飞书里完成权限配置：

```text
/feishu auth
```

安装验证：

```text
/feishu start
```

补充说明：

- 如果需要让 OpenClaw 以你的身份发消息，按文中说明额外开通机器人权限 `im:message.send_as_user`
- 插件装好且权限授权完成后，可以直接在飞书里问该 agent：`我和你对话的chat_id是什么`

拿到 `chat_id` 后，写入 `.env`：

```env
TASK_BRIDGE_USER_CHAT_ID=oc_xxx
```

如果你是在仓库里直接运行 `task-bridge`，放到仓库根目录 `.env`。

如果你主要通过 OpenClaw agent 使用，放到 `~/.openclaw/.env` 更稳妥。

## 6. 最后检查

```bash
openclaw agents list --json
openclaw config get tools.exec.pathPrepend
command -v task-bridge
task-bridge -h
```

通过后，OpenClaw agent 就可以直接执行裸命令 `task-bridge ...`。
