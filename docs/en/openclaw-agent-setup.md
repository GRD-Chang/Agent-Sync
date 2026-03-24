# OpenClaw Agent Setup

Goals:

- Create `team-leader`, `planning-agent`, `code-agent`, `quality-agent`, and `release-agent` with the OpenClaw CLI
- Migrate the agent definitions from this repository
- Install the skills from `https://github.com/garrytan/gstack` so Codex can execute them
- Install and verify `task-bridge`
- Configure `tools.exec.pathPrepend` so agents can run `task-bridge` directly

References:

- <https://docs.openclaw.ai/concepts/agent-workspace>
- <https://docs.openclaw.ai/cli/agents>
- <https://docs.openclaw.ai/tools/exec>

## 1. Create the 5 agents

First verify that the OpenClaw CLI is available:

```bash
openclaw --help
openclaw agents --help
```

Create 5 isolated workspaces:

```bash
openclaw agents add team-leader --non-interactive --workspace ~/.openclaw/workspaces/team-leader
openclaw agents add planning-agent --non-interactive --workspace ~/.openclaw/workspaces/planning-agent
openclaw agents add code-agent --non-interactive --workspace ~/.openclaw/workspaces/code-agent
openclaw agents add quality-agent --non-interactive --workspace ~/.openclaw/workspaces/quality-agent
openclaw agents add release-agent --non-interactive --workspace ~/.openclaw/workspaces/release-agent
```

Verify:

```bash
openclaw agents list --json
```

## 2. Migrate the agent definitions from this repo

This repository already includes:

- `agents/team-leader/*`
- `agents/planning-agent/*`
- `agents/code-agent/*`
- `agents/quality-agent/*`
- `agents/release-agent/*`
- `skills/local/team-leader-orchestrator/SKILL.md`
- `skills/coding-agent/SKILL.md`

Copy those files into each workspace:

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

Sync `IDENTITY.md` into OpenClaw identity settings:

```bash
for agent in team-leader planning-agent code-agent quality-agent release-agent; do
  openclaw agents set-identity --workspace "$HOME/.openclaw/workspaces/$agent" --from-identity
done
```

Copy the required skills:

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

Those copied files are only this repo's agent definitions plus the local `coding-agent` bridge skill.

The actual `office-hours`, `investigate`, `review`, `ship`, and other gstack skills must still be installed for Codex itself, which is the runtime that executes them.

## 3. Install `garrytan/gstack` skills for Codex

The worker `TOOLS.md` files tell the worker to write Codex prompts in this form:

```text
$skill-name task description
```

Those skills are executed by Codex, so they need to be installed into `~/.codex/skills`.

Do not copy gstack skills into the `team-leader` workspace. `team-leader` only dispatches work and does not call Codex directly.

gstack ships with its own `setup` script. It will:

- build the runtime assets and binaries needed by skills such as `/browse`
- create Codex-discoverable gstack skills inside `~/.codex/skills/`
- prepare `~/.codex/skills/gstack` for the shared helper scripts those skills call

First prepare the gstack repository:

```bash
if [ ! -d "$HOME/.codex/skills/gstack/.git" ]; then
  git clone https://github.com/garrytan/gstack.git ~/.codex/skills/gstack
else
  git -C ~/.codex/skills/gstack pull --ff-only
fi
```

Then run the installer:

```bash
cd ~/.codex/skills/gstack
./setup --host codex
```

Notes:

- `bun` must be installed before running `./setup --host codex`
- Windows also needs `node`
- the installed directories are named `gstack-*`, but the actual skill names remain `office-hours`, `investigate`, `review`, `ship`, and so on, so your worker prompts should still use `$investigate ...`, `$review ...`, `$ship ...`

Verify:

```bash
find ~/.codex/skills -maxdepth 1 -mindepth 1 -printf '%f\n' | sort | rg '^gstack-(office-hours|autoplan|plan-ceo-review|plan-design-review|plan-eng-review|design-consultation|retro|investigate|review|cso|browse|setup-browser-cookies|qa|qa-only|design-review|benchmark|setup-deploy|ship|land-and-deploy|canary|document-release|careful|freeze|guard|unfreeze)$'
```

For a quick smoke check, you should at least see:

- `gstack`
- `gstack-office-hours`
- `gstack-investigate`
- `gstack-review`
- `gstack-ship`

## 4. Install `task-bridge`

This project is a Python package, so you usually do not need to build a standalone binary. The recommended setup is an editable install:

```bash
cd /path/to/<repo-root>
python -m pip install -e .
```

Verify:

```bash
command -v task-bridge
task-bridge -h
```

If you only changed `src/task_bridge/**`, editable install usually does not need to be re-run.

If you are preparing a wheel or sdist publish, treat that as a separate verification path:

```bash
cd /path/to/<repo-root>
python -m pip install build
python -m build
```

After building, verify the packaged artifact separately before publishing, especially the dashboard static assets. The editable install path above is the runtime flow verified in this repository.

## 5. Configure `tools.exec.pathPrepend`

Find the directory that contains `task-bridge`:

```bash
dirname "$(command -v task-bridge)"
```

Write it into OpenClaw config:

```bash
TASK_BRIDGE_BIN_DIR="$(dirname "$(command -v task-bridge)")"
openclaw config set tools.exec.pathPrepend "[\"$TASK_BRIDGE_BIN_DIR\"]"
```

Verify:

```bash
openclaw config get tools.exec.pathPrepend
```

If you just changed `~/.openclaw/openclaw.json`, restart the Gateway:

```bash
systemctl --user restart openclaw-gateway.service
```

## 6. Configure Feishu permissions and store the `chat_id`

Reference:

- <https://www.feishu.cn/content/article/7613711414611463386>

After installing the Feishu plugin, complete authorization in Feishu:

```text
/feishu auth
```

Verify the installation:

```text
/feishu start
```

Notes:

- If you want OpenClaw to send messages as you, also enable the bot permission `im:message.send_as_user`
- Once the plugin and permissions are ready, ask the agent directly in Feishu: `What is the chat_id for this conversation?`

After you get the `chat_id`, put it in `.env`:

```env
TASK_BRIDGE_USER_CHAT_ID=oc_xxx
```

Use `TASK_BRIDGE_USER_CHAT_ID` exactly. Current code does not fall back to `TASK_BRIDGE_USER_FEISHU_ID`.

If you run `task-bridge` directly from this repository, use the repo root `.env`.

If you mainly use OpenClaw agents, `~/.openclaw/.env` is the safer default.

Only `TASK_BRIDGE_USER_CHAT_ID` is auto-read from those `.env` files. Variables such as `TASK_BRIDGE_HOME` and `TASK_BRIDGE_CAPTURE_FILE` still need to be exported in the shell or service manager that starts `task-bridge`.

## 7. Final check

```bash
openclaw agents list --json
find ~/.codex/skills -maxdepth 1 -mindepth 1 -printf '%f\n' | sort | rg '^gstack-' || true
openclaw config get tools.exec.pathPrepend
command -v task-bridge
task-bridge -h
```

Once these pass, your OpenClaw agents should be able to run `task-bridge ...` directly.
