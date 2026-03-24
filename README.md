# 大聪明军团：Openclaw 多 agent 指挥 codex

> 构建真正能交付的 OpenClaw 多 Agent 开发团队，解决由 Agent 驱动 Codex 等工具协作时的状态丢失与流程断裂问题。

[中文](README.md) | [English](README.en.md)

`task-bridge` 是一个本地优先、专为 OpenClaw 多 Agent 协作设计的轻量级任务协作系统。它的核心使命是：让 OpenClaw 构建的多 Agent 协作团队，能够稳定地指挥底层开发引擎（如 Codex 或 Claude Code）去完成实际的长流程开发工作。

---

## Dashboard 预览（全局掌控）

只需一条命令，即可将本地的 Job、Tasks、Worker Queue、Alerts 和 Health 状态转化为可视化看板：

```bash
task-bridge dashboard
```

作为“人类指挥官”或 Team Leader，你可以通过 Dashboard 实时监控团队运作。以下为总览页与 Job 详情页示例：

| Dashboard 总览 | Dashboard Job 详情 |
|---|---|
| ![Dashboard 总览](docs/assets/dashboard/overview_zh.png) | ![Dashboard Job 详情](docs/assets/dashboard/job_detail_zh.png) |
| **上帝视角**：查看任务状态分布、Agent 队列情况及系统健康度。 | **聚焦执行**：集中查看特定 Job 的派发时间线、任务拆解与当前卡点。 |

| Task 详情 | 跨语言支持 |
|---|---|
| ![Dashboard Task 详情](docs/assets/dashboard/task_detail_zh.png) | ![Dashboard Job 列表](docs/assets/dashboard/job_list_zh.png) |
| **执行证据**：直接审查事件时间线、最新结果摘要，及随任务附带的 Markdown 执行细节。 | **全面掌控**：快速判断哪些 Job 正在推进、是否已收口。支持中英双语与本地字体切换。 |

---

## 为什么现有的方案行不通？

尝试使用 OpenClaw 组建 Agent 团队时，最核心的痛点往往不是缺少 Agent，而是 **Agent 极难稳定地把控长周期的开发任务**。

在将 OpenClaw 接入 Codex 等底层引擎时，业界通常会尝试以下两种主流方案。但在真实的工程落地中，它们极易引发灾难性的工作流断裂：

### 1. 直接通过 ACP 链路调用
- **做法**：Team Leader 拆解任务并分发给 Code Agent，由后者直接通过 `sessions_spawn(acp)` 等命令唤醒 Codex。
- **痛点分析**：在对接飞书等不支持长时间 Stream 的 IM 平台时，`sessions_spawn` 通常只能异步触发。这会引发严重的逻辑错位：Code Agent 刚发出唤醒指令，就立刻误以为自身工作结束，转头向 Leader 汇报“任务已完成”。此时 Codex 甚至才刚开始读代码。这种将“任务启动”直接等同于“任务完成”的机制，会导致 Leader 过早进入验收或派发下一步任务，让多 Agent 工作流在起步阶段就彻底崩溃。

### 2. 依赖 coding-agent skill 驱动
- **做法**：让 Worker Agent 挂载特定的 coding-agent skill，通过长会话直接驱动 Codex 编码。
- **痛点分析**：真实工程中的需求开发，动辄需要几十分钟的深度上下文检索、代码生成与多轮纠错。Code Agent 作为依赖大模型对话流的节点，几乎无法在单次生命周期内稳定追踪如此漫长的过程。如果依赖heartbeat或cron，往往不够稳定。最致命的后果是：底层的 Codex 已经默默把活干完，而 Code Agent 却早已因超时或机制限制而“失联”。最终无人验证代码结果、无人回写终态、更无人通知 Leader，整个协作系统陷入“底层已完工，编排却永久停滞”的假死状态。

---

## Task Bridge 的解决方案

`task-bridge` 放弃了用“瞬时聊天状态”承载长程任务的做法，将其重构成一个极简的本地任务状态机：

- **本地落盘的事实源**：抛弃脆弱的聊天记录，所有的 Job、Task、State 全部以 JSON 格式落盘本地。
- **串行执行与异步转可控**：同一 Worker 同时只执行一个任务，强制持续回写执行记录，把异步动作转化为可追踪的稳定任务流。
- **周期性防假死推进**：Daemon 守护进程会定期提醒 Worker 推进任务，防止执行挂起。
- **精准的终态通知与自动化 Follow-up**：仅在任务真正达到终态（done/blocked/failed）时主动唤醒 Leader，并对无人处理的终态任务自动催办，防止流水线停转。

---

## 完善的 Agent 团队阵容

引入了覆盖软件工程全生命周期的专业 Agent 团队。在 `task-bridge` 的编排下，团队职责分明：

- **Team Leader (指挥官)**：专注需求拆解，在聊天中统筹全局并派发宏观 Job。
- **Planning Agent (架构师)**：负责系统架构设计、技术选型与详细工作流/Task 规划。
- **Code Agent (程序员)**：专注接单、汇报状态，并驱动底层模型（Codex / Claude Code）执行具体代码变更。
- **Quality Agent (质检员)**：代码质量把控、测试用例编写与执行、Bug 修复及回归验证。
- **Release Agent (发布员)**：负责文档生成、版本控制、项目打包及部署流程编排。
- **Task Bridge (任务中枢)**：底层的无形推手，负责存储状态、串行派发、终态通知。

### 运转机制

```text
User ──> [Team Leader] ──规划──> [Planning Agent] 
             │                          │
      (建立/拆解 Job & Tasks)            │
             │                          │
             ▼                          ▼
     ================ [Task Bridge Daemon] ================
     | (核心中枢：在后台监督队列，将任务分发给空闲 Worker)  |
     ======================================================
             │                          │
        (分发唤醒)                 (分发唤醒)
             ▼                          ▼
       [Code Agent]  <──协同──>  [Quality Agent] ──> [Release Agent]
     (驱动 Codex 编码)          (测试与代码审查)        (文档与发布)
             │                          │
             └──────(回写进度与终态通知) ──┘
```

---

## 快速开始（人类视角）

对人类用户而言，你不需要手动敲击繁琐的命令行来管理任务。只需配置好环境并启动 Daemon，剩下的只需和 Team Leader 聊天即可。

### 1. 配置与安装

你需要将本仓库提供的 Agent Prompt 和 Skill 配置到 OpenClaw，并安装 `task-bridge` 到 Agent 环境：

```bash
# 在仓库根目录执行最小安装
python -m pip install -e .
```
*(注：若修改了 `pyproject.toml` 或入口，请重新执行此命令。)*

**最佳实践：让 AI 帮你配置**
将文档提供给 OpenClaw 的 `default-agent` 或 Claude Code 代劳：
- 中文保姆级教程：`docs/zh/openclaw-agent-setup.md`
- English Setup Guide：`docs/en/openclaw-agent-setup.md`

### 2. 启动 Task Bridge Daemon (后台守护)

配置完成后，让任务中枢在后台运行：

```bash
task-bridge daemon --poll-seconds 10 --worker-reminder-seconds 900 --leader-reminder-seconds 3600
```

**参数说明：**
- `--poll-seconds 10`: 轮询队列间隔（默认 10 秒）。
- `--worker-reminder-seconds 900`: Worker 防挂起提醒间隔（默认 15 分钟）。超时未更新则提醒 Worker 推进。
- `--leader-reminder-seconds 3600`: Leader 长程任务关注提醒间隔（默认 60 分钟）。防止 Leader 失去对执行状态的感知。
- `--leader-followup 300`: 终态任务催办窗口（默认 5 分钟，`0` 表示禁用）。若收到终态后迟迟未下发新任务，主动合并成一条提醒催促 Leader。

**持久化运行 (nohup)**:
```bash
mkdir -p .task-bridge
nohup task-bridge daemon \
  --poll-seconds 60 \
  --worker-reminder-seconds 900 \
  --leader-reminder-seconds 7200 \
  --leader-followup 1800 \
  > .task-bridge/daemon.log 2>&1 &
echo $! > .task-bridge/daemon.pid
```
*(停止命令：`kill "$(cat .task-bridge/daemon.pid)"`)*

### 3. 开启 Dashboard (只读，可选)

```bash
# 默认监听 127.0.0.1:8000
task-bridge dashboard

# 或指定监听地址与端口
task-bridge dashboard --host 127.0.0.1 --port 8000
```
*注：Dashboard 仅读取本地数据，不提供写操作，适合用于审计、定位卡点与日常检查。*

### 4. 给 Team Leader 下发需求

在你的 IM（如飞书）或终端中，直接对 **Team Leader** 对话：

> "我们需要开发一个包含用户认证的 Python CLI 工具，覆盖率要求 80%，让 Planning Agent 先出方案，然后安排 Code Agent 动工。"

接下来，Team Leader 会自动拆解任务，Daemon 会依次唤醒各路 Agent，完成最终交付。

---

## 补充材料：CLI 工具箱 (面向 Agent / 调试)

> **注意**：以下命令主要供 Agent 在后台调用（如回写进度），人类平时无需执行，仅用于 Debug 或强制干预。

### 常用调试命令
```bash
# 查看队列与状态
task-bridge list-tasks --json
task-bridge worker-status --json
task-bridge queue code-agent --json

# 单次派发测试 (不启动 Daemon 时)
task-bridge dispatch-once --json
```

### 本地数据模型
任务结构清晰透明，方便人工随时审查 `~/.openclaw/task-bridge/`：
```text
jobs/<job_id>/
  ├── job.json            # 完整工作主题
  ├── tasks/
  │   └── <task_id>.json  # 最小执行单元
  └── artifacts/
      └── <task_id>/
          └── detail.md   # (可选) 完整的执行细节。终态通知时将自动附带。
```

### 核心命令清单
| 类别 | 命令 | 说明 |
|------|------|------|
| **任务编排** | `create-job`, `list-jobs`, `show-job`, `use-job`, `current-job` | 管理宏观工作主题 (Leader 使用) |
| **任务管理** | `create-task`, `list-tasks`, `show-task`, `update-task`, `delete-task` | 管理具体执行步骤 |
| **Worker 状态** | `claim`, `start`, `update-result`, `complete`, `block`, `fail` | Worker 回写进度与终态 (各路 Agent 使用) |
| **Bridge 调度** | `worker-status`, `queue`, `dispatch-once`, `notify`, `daemon` | 派发与系统守护机制 |

---

## 环境变量与进阶配置

系统会自动从当前工作目录 `.env` 或 `~/.openclaw/.env` 读取变量：
- `TASK_BRIDGE_USER_CHAT_ID`：注入通知 Prompt 的用户 `chat_id`（通知链路强依赖）。

以下变量需要通过 Shell 或前缀显式注入：
- `TASK_BRIDGE_HOME`：自定义数据目录（默认 `~/.openclaw/task-bridge`）。
- `TASK_BRIDGE_CAPTURE_FILE`：拦截发送动作并写入文件，适合做隔离的 E2E 测试。
- `TASK_BRIDGE_DASHBOARD_SSH_TARGET`：覆盖 dashboard 启动提示中的 SSH 目标地址，不影响实际监听。

---

## 参考指南

想要将这套工作流完美融入你的环境，请查阅：
- [OpenClaw Agent 配置指南 (中文)](docs/zh/openclaw-agent-setup.md)
- [OpenClaw Agent 工作流说明 (中文)](docs/zh/openclaw-agent-flow.md)
- [OpenClaw Agent Setup (English)](docs/en/openclaw-agent-setup.md)
- [OpenClaw Agent Workflow Guide (English)](docs/en/openclaw-agent-flow.md)

---

### 开发与测试指引

```bash
# 1. 源码运行 (不依赖 PATH)
PYTHONPATH=src python -m task_bridge create-job --title "Dev task"

# 2. 运行 Python 测试
python -m pip install -e .[test] pytest
python -m pytest -q

# 3. 运行 Dashboard Playwright 测试
npm install
npm run playwright:install
npm run test:playwright
```

> **Task Bridge 哲学**：它不是一个大而全的平台，而是一个极简的任务桥梁。它的核心价值在于让你的 Agent 团队不再失联，让 AI 协作真正落地跑通！至于具体 Prompt 如何设计、如何接入传统脚本 Worker，完全由你自由扩展。