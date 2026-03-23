# OpenClaw Agent 定义方式与核心文件说明

## 目的

本文档用于说明 OpenClaw 中 agent 是如何被定义出来的，以及几个关键工作区文件各自承担什么作用。

重点参考以下官方文档：

- `AGENTS.default`：<https://docs.openclaw.ai/reference/AGENTS.default>
- `AGENTS` 模板：<https://docs.openclaw.ai/reference/templates/AGENTS>
- `HEARTBEAT` 模板：<https://docs.openclaw.ai/reference/templates/HEARTBEAT>
- `IDENTITY` 模板：<https://docs.openclaw.ai/reference/templates/IDENTITY>
- `SOUL` 模板：<https://docs.openclaw.ai/reference/templates/SOUL>
- `TOOLS` 模板：<https://docs.openclaw.ai/reference/templates/TOOLS>

## 总结

OpenClaw 里的 agent 不是只靠一个“agent 配置对象”定义出来的，而是靠一个 **workspace 工作区 + 一组约定文件** 共同定义出来的。

可以把它理解成：

1. `AGENTS.md` 规定运行规则、启动顺序、记忆机制、安全边界和沟通行为。
2. `SOUL.md` 定义 agent 的人格、价值观、语气和边界。
3. `USER.md` 定义 agent 服务的对象是谁。
4. `MEMORY.md` 和 `memory/YYYY-MM-DD.md` 定义 agent 的长期与短期记忆。
5. `TOOLS.md` 定义当前环境下的本地工具说明和环境特定知识。
6. `HEARTBEAT.md` 定义后台轮询、定期检查和主动工作的清单。
7. `IDENTITY.md` 定义名字、形象、风格等身份信息。

因此，OpenClaw 的 agent 更像是“**由文件系统中的长期上下文塑造出来的持续角色**”，而不是一次性 prompt 出来的临时会话。

## Agent 的基本工作方式

根据官方模板，OpenClaw agent 的工作目录默认是 `~/.openclaw/workspace`，也可以通过 `agents.defaults.workspace` 配置为其它目录。

在默认推荐流程里：

1. 先创建 workspace。
2. 把默认模板文件拷进去，例如 `AGENTS.md`、`SOUL.md`、`TOOLS.md`。
3. 如有需要，可以用 `AGENTS.default.md` 替换掉通用版 `AGENTS.md`，得到一份更完整的个人助理默认配置。

这说明 OpenClaw 把 agent 的“定义”落在工作区文件上，而不是落在隐藏配置里。  
agent 每次启动时会读取这些文件，以恢复身份、记忆和行为规则。

## `AGENTS.default` 与 `AGENTS` 模板的关系

### `AGENTS` 模板是什么

`AGENTS` 模板是一个更通用的工作区启动文件。它描述的是：

- 这是 agent 的“家目录”
- 首次运行时如果存在 `BOOTSTRAP.md`，要先读取并完成初始化
- 每次 session 启动时必须先读哪些文件
- 记忆应该怎么组织
- 什么行为属于红线
- 群聊里什么时候该说话，什么时候不该说话
- 心跳任务和主动工作应该怎么做

它更像一份 **通用工作区行为规范**。

### `AGENTS.default` 是什么

`AGENTS.default` 是 OpenClaw 官方给“个人助理型 agent”准备的默认版本。

相比通用模板，它更偏向现成可用，内容更明确，例如：

- 工作区默认位置
- 首次初始化步骤
- 默认安全规则
- session 启动时该读什么
- 记忆和 `MEMORY.md` 的使用方式
- “OpenClaw 能做什么”
- 推荐启用的核心 skills
- 使用建议和平台说明

它可以理解为：**在通用 `AGENTS.md` 模板基础上，预装了一套官方推荐的个人助理运行规范。**

### 两者的核心区别

| 文件 | 角色 | 适合场景 |
|---|---|---|
| `AGENTS` 模板 | 通用骨架 | 想自己定义 agent 行为、适合定制化工作区 |
| `AGENTS.default` | 官方默认成品 | 想快速得到一个可用的个人助理 agent |

## `AGENTS.md` 的作用

`AGENTS.md` 是整个 agent 工作区里最核心的入口文件。

它主要承担以下职责：

### 1. 规定 session 启动顺序

OpenClaw 官方模板明确要求，在 session 刚开始时，agent 应优先读取：

1. `SOUL.md`
2. `USER.md`
3. `memory/YYYY-MM-DD.md`（今天和昨天）
4. 如果是主会话，还要读取 `MEMORY.md`

这意味着 `AGENTS.md` 决定了 agent 每次启动时先恢复哪些上下文。

### 2. 定义记忆系统的使用规则

`AGENTS.md` 规定：

- `memory/YYYY-MM-DD.md` 用于日常原始记录
- `MEMORY.md` 用于长期、提炼后的记忆
- 重要信息要写到文件里，而不是依赖“脑内记忆”

这说明 `AGENTS.md` 既是行为规范，也是记忆管理规范。

### 3. 定义安全边界

例如模板里明确强调：

- 不要泄露私密数据
- 不要在未确认时执行危险命令
- 尽量使用可恢复操作，例如 `trash` 优于 `rm`
- 对外发送内容前要更谨慎

所以 `AGENTS.md` 实际上也是 agent 的高层安全策略文件。

### 4. 定义沟通风格与群聊行为

模板特别讨论了：

- 群聊中什么时候应该响应
- 什么时候应该保持沉默并返回 `HEARTBEAT_OK`
- 如何像人一样使用 reaction，而不是对每条消息都回复

这说明 `AGENTS.md` 不仅管理技术行为，也管理社交行为。

### 5. 定义 heartbeat 的工作方式

模板明确区分 heartbeat 和 cron 的使用场景，并鼓励 agent 在 heartbeat 中做：

- 周期检查
- 轻量主动工作
- 记忆整理
- 文档维护

因此 `AGENTS.md` 也承担了后台行为编排规则。

## `SOUL.md` 的作用

`SOUL.md` 用来定义 agent “是谁”。

官方模板强调：

- 不是简单聊天机器人，而是在逐步形成一个“角色”
- 要真正有帮助，而不是表演式礼貌
- 可以有观点，不需要装成没有人格的搜索引擎
- 要先自己查、自己读、自己找，再提问
- 要通过能力赢得信任
- 外部动作谨慎，内部动作可以更主动

它主要定义四类内容：

1. **核心信念**
   例如如何帮助用户、如何处理主动性、如何体现能力。
2. **边界**
   例如隐私、外部行为、群聊发言、外部消息不得半成品发送。
3. **语气与风格**
   例如简洁、不过度讨好、不过度企业化。
4. **持续性**
   它是 session 之间人格连续性的来源之一。

简单说，`SOUL.md` 负责定义 **人格与价值观**。

## `IDENTITY.md` 的作用

`IDENTITY.md` 用来定义 agent 的“身份壳”。

官方模板里建议填写：

- Name
- Creature
- Vibe
- Emoji
- Avatar

它和 `SOUL.md` 的区别在于：

| 文件 | 关注点 |
|---|---|
| `SOUL.md` | 内在原则、风格、边界、价值观 |
| `IDENTITY.md` | 名字、形象、物种设定、视觉识别 |

因此可以把 `IDENTITY.md` 看成 **角色卡**，而 `SOUL.md` 看成 **角色内核**。

## `TOOLS.md` 的作用

`TOOLS.md` 不是定义工具能力本身，而是定义 **当前环境中的本地化工具说明**。

官方文档的关键点是：

- skill 负责说明“工具如何工作”
- `TOOLS.md` 负责写“你当前环境里这些工具具体对应什么”

适合写进 `TOOLS.md` 的内容包括：

- 摄像头名称与位置
- SSH 主机别名
- TTS 偏好的声音
- 音箱、房间或设备昵称
- 其它任何环境相关的信息

它存在的意义是把“共享的 skill”与“私有的本地环境知识”分开。

所以 `TOOLS.md` 本质上是：

**agent 的环境知识手册 / 本地 cheat sheet**

## `HEARTBEAT.md` 的作用

`HEARTBEAT.md` 用来定义 heartbeat 轮询时到底应该做什么。

官方模板非常简单，核心思想是：

- 如果文件为空或只有注释，就跳过 heartbeat API 调用
- 如果要做周期任务，就把任务写进去

也就是说，`HEARTBEAT.md` 是一个 **后台主动任务清单**，而不是人格文件。

结合 `AGENTS` 模板里的说明，heartbeat 适合做的事情有：

- 批量检查邮箱、日历、通知
- 做一些时间允许轻微漂移的周期检查
- 做轻量后台工作
- 维护记忆文件

而不适合 heartbeat、应改用 cron 的事情包括：

- 必须精确到某个时刻的任务
- 需要与主会话隔离的任务
- 一次性定时提醒
- 需要直接投递到特定 channel 的任务

因此：

- `HEARTBEAT.md` 决定“定期做什么”
- `AGENTS.md` 决定“heartbeat 应该怎么做、何时做、何时安静”

## 这些文件如何组合成一个 agent

从结构上看，OpenClaw 中一个完整 agent 大致由以下文件组合构成：

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 总入口，定义启动顺序、记忆规则、安全边界、群聊行为、heartbeat 规则 |
| `SOUL.md` | 人格、价值观、风格、边界 |
| `IDENTITY.md` | 名字、形象、视觉身份、角色设定 |
| `USER.md` | 服务对象是谁、如何帮助对方 |
| `MEMORY.md` | 长期、提炼后的记忆 |
| `memory/YYYY-MM-DD.md` | 每日原始记录和近期上下文 |
| `TOOLS.md` | 本地环境中的工具和设备说明 |
| `HEARTBEAT.md` | 后台周期任务清单 |
| `BOOTSTRAP.md` | 首次运行时的初始化说明 |

因此，OpenClaw 的 agent 定义模型不是“单文件配置”，而是“**工作区文件协同定义**”。

## 对你当前体系的启发

如果你要在自己的多 agent 架构里借鉴 OpenClaw 的定义方式，可以直接对应成下面的概念：

| OpenClaw 文件 | 在你系统中的可类比概念 |
|---|---|
| `AGENTS.md` | agent 的系统级运行规范 |
| `SOUL.md` | agent 的角色提示词 / 行为边界 |
| `IDENTITY.md` | agent 的命名和身份标签 |
| `TOOLS.md` | agent 可用工具和环境说明 |
| `HEARTBEAT.md` | agent 的后台轮询任务配置 |
| `MEMORY.md` + `memory/` | agent 的长期 / 短期记忆层 |

这也说明一个很重要的设计思想：

**OpenClaw 并不是把 agent 只当成一次会话，而是把它当成一个有身份、记忆、工具上下文和后台行为的长期存在体。**

## 结论

OpenClaw 中定义 agent 的核心不是单一配置项，而是：

1. 一个工作区目录
2. 一组约定命名的上下文文件
3. 一套固定的启动与记忆读取顺序
4. 一套对外行为与后台行为的规则

其中：

- `AGENTS.md` 负责总调度规则
- `SOUL.md` 负责人格和边界
- `IDENTITY.md` 负责身份表现
- `TOOLS.md` 负责本地环境知识
- `HEARTBEAT.md` 负责主动任务

如果只保留一句最重要的话，可以概括为：

**在 OpenClaw 里，agent 是被“工作区文件系统中的长期上下文”定义出来的。**
