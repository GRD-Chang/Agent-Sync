# OpenClaw Agent Setup

Goals:

- Create `team-leader`, `planning-agent`, `code-agent`, `quality-agent`, and `release-agent` with the OpenClaw CLI
- Migrate the agent definitions from this repository
- Confirm the worker execution environment is prepared by the operator; this project does not configure it
- Make skills discoverable to worker sessions; when a task has a matching skill, workers should use that skill first
- Install and verify `task-bridge`
- Configure `tools.exec.pathPrepend` so agents can run `task-bridge` directly

References:

- <https://docs.openclaw.ai/concepts/agent-workspace>
- <https://docs.openclaw.ai/cli/agents>
- <https://docs.openclaw.ai/plugins/codex-harness#codex-harness> (external runtime reference, not a project setup step)
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
  if [ "$agent" = "team-leader" ] && [ -f "$REPO_ROOT/agents/team-leader/TASK_ROUTING.md" ]; then
    cp "$REPO_ROOT/agents/team-leader/TASK_ROUTING.md" "$HOME/.openclaw/workspaces/team-leader/"
  fi
done
```

Sync `IDENTITY.md` into OpenClaw identity settings:

```bash
for agent in team-leader planning-agent code-agent quality-agent release-agent; do
  openclaw agents set-identity --workspace "$HOME/.openclaw/workspaces/$agent" --from-identity
done
```

Those copied files are this repo's agent definitions plus the `team-leader` `TASK_ROUTING.md`. `team-leader` orchestrates directly through `AGENTS.md` and `TASK_ROUTING.md`; once a worker receives a task, it becomes the task owner.

Worker `TOOLS.md` files do not maintain a full skill catalog. They only keep local environment constraints, `task-bridge` commands, and execution boundaries.

## 3. External execution environment prerequisite

This project does not install, configure, or validate the lower-level execution environment.

Before continuing with `task-bridge`, the operator should confirm outside this repository that:

- OpenClaw worker agents can execute tasks directly in the current environment.
- Worker sessions can inspect available skills.
- Workers do not need this repository's old relay layer and should not launch a second execution layer.

This repository owns agent definitions, task orchestration, state transitions, evidence collection, and handoff. Model selection, fallback policy, permissions, transport, and other lower-level runtime settings are outside this repository's scope.

## 4. Prepare discoverable worker skills

When `planning-agent`, `code-agent`, `quality-agent`, or `release-agent` receives a task, it should first inspect the skills available in the current session. If a skill matches the task goal, scope, acceptance criteria, and verification requirements, the worker should use that skill first. If no skill fits, the worker reads the repository, runs commands, and records evidence directly.

If you use `garrytan/gstack`, install it into the skill directory your worker runtime can discover. The commands below use `~/.codex/skills` as the local default example; replace the path if your runtime uses a different skill directory.

Do not copy gstack skills into the `team-leader` workspace. `team-leader` only dispatches work and does not directly execute worker tasks.

gstack ships with its own `setup` script. It will:

- build the runtime assets and binaries needed by skills such as `/browse`
- create runtime-discoverable gstack skills inside the target skills directory
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
- the installed directories are named `gstack-*`; workers only need those skills to be discoverable in the current session, and the active runtime owns the concrete triggering mechanism

Verify that the install directories are discoverable:

```bash
find ~/.codex/skills -maxdepth 1 -mindepth 1 -printf '%f\n' | sort | rg '^gstack'
```

For a quick smoke check, you should see `gstack` plus some `gstack-*` skill directories, for example:

- `gstack`
- `gstack-...`

## 5. Install `task-bridge`

This project is a Python package, so you usually do not need to build a standalone binary. The recommended setup is an editable install:

```bash
cd /path/to/<repo-root>
python -m pip install -e .
```

Verify:

```bash
command -v task-bridge
task-bridge -h
task-bridge daemon-status --json
```

If you only changed `src/task_bridge/**`, editable install usually does not need to be re-run.

If you are preparing a wheel or sdist publish, treat that as a separate verification path:

```bash
cd /path/to/<repo-root>
python -m pip install build
python -m build
```

After building, verify the packaged artifact separately before publishing, especially the dashboard static assets. The editable install path above is the runtime flow verified in this repository.

## 6. Configure `tools.exec.pathPrepend`

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

## 7. Configure Feishu permissions and store the `chat_id`

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
task-bridge daemon-status --json
```

Once these pass, your OpenClaw agents should be able to run `task-bridge ...` directly.
