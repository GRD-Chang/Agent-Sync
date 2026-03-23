# gstack Agent 与 Skill 分配方案

## 目标

本文档用于定义在当前 `team-leader -> worker -> codex` 架构下，如何引入 `~/code/gstack` 提供的 skill，以提升开发质量和效率，同时避免过度拆分带来的协作开销。

设计原则如下：

1. `team-leader` 只负责分发任务、切换阶段、收集结果，不直接调用 Codex，不分配任何 skill。
2. worker 数量保持精简，只保留能够相对独立闭环的强角色。
3. skill 分配尽量单一归属，避免多个 worker 抢职责。
4. 控制类 / 平台类 skill 不做成独立 agent，但需要区分：
   - 仅人工触发的运维 skill
   - 可按需下发给部分 worker 的跨 agent 控制 skill
5. 文档覆盖 gstack 仓库中的全部 28 个 skill，确保不重不漏。

## 总体角色划分

### 1. team-leader

- 类型：调度者
- 是否分配 skill：否
- 职责：
  - 拆解需求和阶段
  - 选择合适的 worker
  - 控制 `plan -> build -> validate -> release` 的流转
  - 汇总各 worker 结果并继续分发

### 2. planning-agent

- 职责：
  - 在写代码前澄清问题、收敛范围、补齐产品与交互方案
  - 输出可执行计划、架构关注点、测试计划输入
  - 在阶段结束时为下一轮计划提供复盘输入
- 适用阶段：
  - 需求澄清
  - 方案评审
  - 计划完善
  - 迭代复盘输入

### 3. build-agent

- 职责：
  - 依据计划实现代码
  - 调试失败路径
  - 做根因定位和修复
- 适用阶段：
  - 编码实现
  - 问题修复

### 4. validation-agent

- 职责：
  - 独立代码审查
  - 安全检查
  - 浏览器级验证
  - 视觉质量检查
  - 性能基线和回归比较
- 适用阶段：
  - 代码完成后
  - 准备发版前
  - 疑似存在质量风险时

### 5. release-agent

- 职责：
  - 发布前整理
  - 创建 PR / 发版 / 部署
  - 部署后验证
  - 文档同步
- 适用阶段：
  - 发布准备
  - 合并部署
  - 上线后观察

### 6. 控制类 / 人工运维能力（非 agent）

- 说明：
  - 这一类 skill 更像控制面能力或平台维护能力，不适合做成独立 worker。
  - 其中一部分仅适合人工或平台维护流程显式触发。
  - 另一部分可以作为跨 agent 的控制能力，按需分发给特定 worker。

## Agent 与 Skill 分配总览

| 归属 | skill |
|---|---|
| `planning-agent` | `office-hours`, `autoplan`, `plan-ceo-review`, `plan-design-review`, `plan-eng-review`, `design-consultation`, `retro` |
| `build-agent` | `investigate` |
| `validation-agent` | `review`, `cso`, `codex`, `browse`, `setup-browser-cookies`, `qa`, `qa-only`, `design-review`, `benchmark` |
| `release-agent` | `setup-deploy`, `ship`, `land-and-deploy`, `canary`, `document-release` |
| 跨 agent 控制能力（非独立 agent） | `careful`, `freeze`, `guard`, `unfreeze` |
| 人工运维保留（非 agent） | `gstack`, `gstack-upgrade` |

## 控制类 skill 的默认下发规则

这些 skill 不单独归属某一个业务 worker，但允许按场景下发：

| skill | 默认下发对象 | 作用 |
|---|---|---|
| `careful` | `validation-agent`, `release-agent`， `build-agent` | 对高风险命令增加显式警告 |
| `freeze` | `build-agent`, `validation-agent` | 在局部修复、调试时限制编辑边界 |
| `guard` | `validation-agent`, `release-agent`， `build-agent` | 同时启用危险命令警告和编辑边界控制 |
| `unfreeze` | 任何已拿到 `freeze` 的 agent | 解除编辑边界 |

默认原则：

1. `planning-agent` 不下发控制类 skill，保持规划阶段轻量。
2. `build-agent` 主要拿 `freeze/unfreeze`，只在高风险改动时拿 `careful/guard`。
3. `validation-agent` 和 `release-agent` 默认更接近真实执行与交付环境，因此更适合持有控制类 skill。

## Skill 逐项归属与作用说明

| skill | 归属 | 大致作用 | 备注 |
|---|---|---|---|
| `gstack` | 人工运维保留 | 总入口 / 路由型 skill，用于识别当前阶段适合调用哪些 gstack skill | 不建议下发给 worker，避免与 team-leader 的调度职责重复 |
| `office-hours` | `planning-agent` | 做需求澄清和产品思考，逼出真实痛点、最小切入点和问题定义 | 适合新需求起步阶段 |
| `autoplan` | `planning-agent` | 自动串行执行 CEO / 设计 / 工程三个 plan review，并自动做中间决策 | 适合快速生成完整计划 |
| `plan-ceo-review` | `planning-agent` | 从产品 / 创始人视角审查计划，评估范围、 ambition 和价值密度 | 重点回答“值不值得做、范围是否对” |
| `plan-design-review` | `planning-agent` | 在实现前评估 UI/UX 方案，检查层级、状态、交互和设计完整性 | 只用于 plan 阶段 |
| `plan-eng-review` | `planning-agent` | 在实现前锁定架构、数据流、失败路径、测试策略和性能关注点 | 输出工程侧可执行方案 |
| `design-consultation` | `planning-agent` | 为项目建立设计系统、品牌方向、字体、颜色、布局和设计语言 | 适合缺少设计基线的新项目 |
| `retro` | `planning-agent` | 对一个周期内的工程活动做复盘，沉淀下一轮规划输入 | 团队没有 team-leader skill 时，归 planning-agent 最合适 |
| `investigate` | `build-agent` | 先做根因调查，再修复问题，避免只改表面现象 | `build-agent` 的核心技能 |
| `review` | `validation-agent` | 对当前分支 diff 做预合并审查，重点查结构性问题、数据安全、边界问题 | 属于独立复核，不应由 build-agent 自审 |
| `cso` | `validation-agent` | 进行安全审查，覆盖 OWASP、STRIDE、攻击面、密钥、依赖风险等 | 面向高风险改动的独立校验 |
| `codex` | `validation-agent` | 用 OpenAI Codex CLI 提供第二视角审查、对抗式挑战或咨询 | 若执行宿主本身是 Codex，则该 skill 在 Codex host 上会被排除 |
| `browse` | `validation-agent` | 使用持久化浏览器做真实点击、截图、状态检查和页面狗粮测试 | 是一类底层验证能力 |
| `setup-browser-cookies` | `validation-agent` | 导入真实浏览器 cookie，便于验证登录后的页面和受保护流程 | 为 QA/浏览器测试提供前置能力 |
| `qa` | `validation-agent` | 系统化做 Web QA，并在发现问题后修复、复测、给出健康度结论 | 适合“测并修”闭环 |
| `qa-only` | `validation-agent` | 只做 QA 报告，不改代码 | 适合需要独立缺陷清单时 |
| `design-review` | `validation-agent` | 对已实现页面做视觉和交互审查，并修复设计层问题 | 属于实现后的设计质量验证 |
| `benchmark` | `validation-agent` | 建立性能基线并做前后对比，例如加载时间、资源大小、Web Vitals | 适合验证性能回归 |
| `setup-deploy` | `release-agent` | 配置部署平台、生产地址、健康检查和状态命令 | 为发布自动化做一次性铺垫 |
| `ship` | `release-agent` | 运行发布前流程：合并基线、跑测试、做 review gate、创建 PR 等 | 是正式发版前的主流程 |
| `land-and-deploy` | `release-agent` | 合并 PR、等待 CI / deploy、验证生产状态 | 处理“落地上线” |
| `canary` | `release-agent` | 上线后持续观察页面错误、性能异常、失败率和视觉回归 | 用于发布后的短期监控 |
| `document-release` | `release-agent` | 根据本次交付更新 README、架构文档、贡献文档、CHANGELOG 等 | 是发布闭环的一部分 |
| `careful` | 跨 agent 控制能力 | 对危险命令增加显式警告，例如 `rm -rf`、强推、删除资源等 | 默认下发给 `validation-agent` 和 `release-agent` |
| `freeze` | 跨 agent 控制能力 | 限制编辑范围，只允许在指定目录内写文件 | 默认下发给 `build-agent` 和 `validation-agent` |
| `guard` | 跨 agent 控制能力 | 同时启用危险命令警告和编辑边界控制 | 默认下发给 `validation-agent` 和 `release-agent` |
| `unfreeze` | 跨 agent 控制能力 | 解除 `freeze` 的编辑限制 | 应与 `freeze` 配套分发 |
| `gstack-upgrade` | 人工运维保留 | 升级 gstack 自身版本，更新本地安装 | 平台维护动作，不属于业务研发流程 |

## 为什么采用这套分配

### planning-agent 合并了产品、设计和工程计划能力

- 这三类能力都发生在“写代码之前”。
- `autoplan` 本身就是把 CEO / 设计 / 工程 review 串成一个完整流水线。
- 如果继续拆成多个 planning worker，交接成本会高于收益。

### build-agent 保持极简

- 编码与调试是最容易受上下文切换影响的阶段。
- 这里不应塞入过多流程型 skill，否则反而会降低执行效率。
- `investigate` 足够承担“根因分析 + 修复推进”的核心职责。

### validation-agent 保持独立

- 它的价值来自“不是 build-agent 本人”。
- 代码审查、安全审查、浏览器验证、视觉检查和性能回归，本质上都是独立验收能力。
- 这些能力合并在同一个强验证 agent 里，既能保持独立性，也不会产生太多 handoff。

### release-agent 单独负责交付闭环

- 发布流程和问题发现流程目标不同，不应混入 `validation-agent`。
- 它关注的是“如何安全地交付出去”，包括部署配置、发版、上线验证和文档回写。

### 控制类 skill 分两类处理

- `gstack`、`gstack-upgrade` 属于人工运维保留能力，不进入默认 worker 分发集合。
- `careful`、`freeze`、`guard`、`unfreeze` 属于跨 agent 控制能力，不单独归属某个业务 worker，但可按需下发给执行型 agent。
- 这样既不会把它们误当成独立角色，又不会遗漏它们在实际执行中会被部分 worker 使用的事实。

## Codex 宿主下的特殊说明

若某个 worker 运行在 Codex 宿主内，则需要注意：

1. `codex` skill 会因为自指问题在 Codex host 上被排除，不会直接下发给 Codex 自己。
2. 此时 `validation-agent` 仍然成立，只是少掉 `codex` 这一项。
3. 若需要真正的第二模型视角，应该由非 Codex 宿主的 reviewer 触发该 skill。

## 最终建议

推荐长期采用以下结构：

1. `team-leader`：无 skill，只做调度。
2. `planning-agent`：负责需求到计划的完整收敛。
3. `build-agent`：负责实现与调试。
4. `validation-agent`：负责独立审查与质量验证。
5. `release-agent`：负责发布、部署、上线后验证与文档同步。
6. `gstack`、`gstack-upgrade` 由人工运维显式触发；`careful`、`freeze`、`guard`、`unfreeze` 作为跨 agent 控制能力按需下发。

这套方案兼顾了三个目标：

- agent 足够强，可以相对独立工作
- skill 归属清晰，不重不漏
- 不会因为过细拆分而引入额外协作成本
