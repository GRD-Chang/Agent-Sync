# OpenClaw Agent 配置

目标：

- 用 OpenClaw CLI 创建 `team-leader`、`planning-agent`、`code-agent`、`quality-agent`、`release-agent`
- 把本仓库里的 agent 定义迁过去
- 安装 `https://github.com/garrytan/gstack` 中的 skill，供 Codex 执行
- 安装并验证 `task-bridge`
- 配置 `tools.exec.pathPrepend`，让 agent 可以直接执行 `task-bridge`

参考：

- <https://docs.openclaw.ai/concepts/agent-workspace>
- <https://docs.openclaw.ai/cli/agents>
- <https://docs.openclaw.ai/tools/exec>

## 1. 创建 5 个 agent

先确认 OpenClaw CLI 可用：

```bash
openclaw --help
openclaw agents --help
```

创建 5 个独立 workspace：

```bash
openclaw agents add team-leader --non-interactive --workspace ~/.openclaw/workspaces/team-leader
openclaw agents add planning-agent --non-interactive --workspace ~/.openclaw/workspaces/planning-agent
openclaw agents add code-agent --non-interactive --workspace ~/.openclaw/workspaces/code-agent
openclaw agents add quality-agent --non-interactive --workspace ~/.openclaw/workspaces/quality-agent
openclaw agents add release-agent --non-interactive --workspace ~/.openclaw/workspaces/release-agent
```

验证：

```bash
openclaw agents list --json
```

## 2. 迁移本仓库里的 agent 定义

本仓库已经包含：

- `agents/team-leader/*`
- `agents/planning-agent/*`
- `agents/code-agent/*`
- `agents/quality-agent/*`
- `agents/release-agent/*`
- `skills/local/team-leader-orchestrator/SKILL.md`
- `skills/coding-agent/SKILL.md`

把这些文件复制到各自 workspace：

```bash
REPO_ROOT=/path/to/<repo-root>

for agent in team-leader planning-agent code-agent quality-agent release-agent; do
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
for agent in team-leader planning-agent code-agent quality-agent release-agent; do
  openclaw agents set-identity --workspace "$HOME/.openclaw/workspaces/$agent" --from-identity
done
```

复制 skill：

```bash
mkdir -p "$HOME/.openclaw/workspaces/team-leader/skills/team-leader-orchestrator"
cp "$REPO_ROOT/skills/local/team-leader-orchestrator/SKILL.md" \
  "$HOME/.openclaw/workspaces/team-leader/skills/team-leader-orchestrator/SKILL.md"

for agent in planning-agent code-agent quality-agent release-agent; do
  mkdir -p "$HOME/.openclaw/workspaces/$agent/skills/coding-agent"
  cp "$REPO_ROOT/skills/coding-agent/SKILL.md" \
    "$HOME/.openclaw/workspaces/$agent/skills/coding-agent/SKILL.md"
done
```

这里复制的是本仓库自己的 agent 定义和 `coding-agent` 桥接 skill。

真正由 Codex 执行的 `office-hours`、`investigate`、`review`、`ship` 等 gstack skill，需要额外安装到 Codex 的 skill 目录，见下一步。

## 3. 安装 `garrytan/gstack` skill（供 Codex 使用）

`planning-agent`、`code-agent`、`quality-agent`、`release-agent` 的 `TOOLS.md` 会指导 worker 在给 Codex 的 prompt 里使用：

```text
$技能名 任务说明
```

这些 skill 的真正执行主体是 Codex，因此需要先把 gstack 安装到 `~/.codex/skills`。

不要把 gstack skill 直接复制进 `team-leader` 工作区；`team-leader` 只负责分发任务，不直接调用 Codex。

gstack 自带 `setup` 脚本，会自动：

- 构建 `/browse` 等 skill 依赖的二进制和运行时资源
- 在 `~/.codex/skills/` 下创建 Codex 可发现的 gstack skill
- 准备 `~/.codex/skills/gstack` 供这些 skill 的共享脚本使用

先准备 gstack 仓库：

```bash
if [ ! -d "$HOME/.codex/skills/gstack/.git" ]; then
  git clone https://github.com/garrytan/gstack.git ~/.codex/skills/gstack
else
  git -C ~/.codex/skills/gstack pull --ff-only
fi
```

然后执行安装：

```bash
cd ~/.codex/skills/gstack
./setup --host codex
```

补充说明：

- 运行 `./setup --host codex` 前，机器上需要有 `bun`
- Windows 额外需要 `node`
- `./setup` 会把适配 Codex 的 skill 安装为 `gstack-*` 目录，但 skill 本身的名字仍然是 `office-hours`、`investigate`、`review`、`ship` 这类裸名称，因此 worker prompt 里继续使用 `$investigate ...`、`$review ...`、`$ship ...`

验证：

```bash
find ~/.codex/skills -maxdepth 1 -mindepth 1 -printf '%f\n' | sort | rg '^gstack-(office-hours|autoplan|plan-ceo-review|plan-design-review|plan-eng-review|design-consultation|retro|investigate|review|cso|browse|setup-browser-cookies|qa|qa-only|design-review|benchmark|setup-deploy|ship|land-and-deploy|canary|document-release|careful|freeze|guard|unfreeze)$'
```

如果你只想快速确认安装成功，至少应该看到：

- `gstack`
- `gstack-office-hours`
- `gstack-investigate`
- `gstack-review`
- `gstack-ship`

## 4. 安装 `task-bridge`

本项目是 Python 包，通常不需要单独编译二进制。推荐直接安装：

```bash
cd /path/to/<repo-root>
python -m pip install -e .
```

验证：

```bash
command -v task-bridge
task-bridge -h
```

如果只是改了 `src/task_bridge/**`，editable install 一般不需要重装。

如果你准备发布 wheel / sdist，请把它视为单独的验证路径：

```bash
cd /path/to/<repo-root>
python -m pip install build
python -m build
```

构建完成后，请在发布前单独验证打包产物，尤其是 dashboard 的静态资源。当前仓库里已验证的运行路径仍然是上面的 editable install。

## 5. 配置 `tools.exec.pathPrepend`

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

## 6. 配置飞书权限并写入 `chat_id`

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

请使用精确变量名 `TASK_BRIDGE_USER_CHAT_ID`；当前代码不会回退读取 `TASK_BRIDGE_USER_FEISHU_ID`。

如果你是在仓库里直接运行 `task-bridge`，放到仓库根目录 `.env`。

如果你主要通过 OpenClaw agent 使用，放到 `~/.openclaw/.env` 更稳妥。

另外，只有 `TASK_BRIDGE_USER_CHAT_ID` 会被程序自动从这些 `.env` 文件读取；`TASK_BRIDGE_HOME`、`TASK_BRIDGE_CAPTURE_FILE` 这类变量仍需由 shell 或 service manager 显式导出。

## 7. 最后检查

```bash
openclaw agents list --json
find ~/.codex/skills -maxdepth 1 -mindepth 1 -printf '%f\n' | sort | rg '^gstack-' || true
openclaw config get tools.exec.pathPrepend
command -v task-bridge
task-bridge -h
```

通过后，OpenClaw agent 就可以直接执行裸命令 `task-bridge ...`。
