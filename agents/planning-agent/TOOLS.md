# TOOLS.md - Local Notes

本文件只记录这个工作区的本地环境约束，以及可用的工具 / 技能路由。

## Task Bridge

- `task-bridge` 仓库位置：按当前安装与任务配置确定，不要求与 agent 定义位于同一 git repo
- 默认调用方式：
  - `task-bridge ...`
- 如果 PATH 未生效，使用当前 Python 环境中的 `task-bridge` 绝对路径
- 任务派发消息会包含：
  - `job_id`
  - `task_id`
  - `task_path`

## Task Bridge 常用命令

- 查看任务：
  - `task-bridge show-task <task_id> --job <job_id> --json`
- 标记开始：
  - `task-bridge start <task_id> --job <job_id> --result "<starting summary>"`
- 过程更新：
  - `task-bridge update-result <task_id> --job <job_id> --result "<progress summary>"`
- 完成：
  - `task-bridge complete <task_id> --job <job_id> --result "<final summary>"`
- 阻塞：
  - `task-bridge block <task_id> --job <job_id> --result "<block reason + unblock suggestion>"`
- 失败：
  - `task-bridge fail <task_id> --job <job_id> --result "<failure reason + evidence>"`

## Execution Context

- 直接在当前环境中推进任务
- 如果 task 指定了 repo / worktree / cwd / 工作路径，开始执行前先检查该路径下是否存在 `AGENTS.md`；如果存在，先阅读并遵守其中规则
- 需要仓库读取、shell、测试或 git 动作时，直接使用当前可用工具
- 每次推进前都要把上下文、范围、验证方式、风险口径和交付标准写清楚

## Optional Skills

下面只是常见能力示例，不是完整清单；当前运行环境中还有其他可用 skill / 工具时，可按任务需要选择。

## 常用技能

### 需求澄清与方向判断

- `office-hours`
  - 澄清真实问题、切入点、范围和价值判断

### 计划审查与方案收敛

- `autoplan`
  - 自动串行执行计划审查流水线，输出更完整的可执行方案
- `plan-ceo-review`
  - 从产品价值、范围和 ambition 视角审查计划
- `plan-design-review`
  - 从交互、层级、状态和体验完整性视角审查计划
- `plan-eng-review`
  - 从架构、失败路径、验证策略和性能视角审查计划

### 设计基线与复盘

- `design-consultation`
  - 建立设计系统、设计语言和视觉方向
- `retro`
  - 对一个周期内的工程活动做复盘，提炼下一轮规划输入

## 技能路由

按任务类型优先使用：

- 新需求、问题定义不清、切入点待收敛：
  - 优先使用 `office-hours`
- 需要一轮完整的自动计划审查：
  - 优先使用 `autoplan`
- 产品价值、范围、目标密度待判断：
  - 优先使用 `plan-ceo-review`
- 交互、视觉、状态设计待评估：
  - 优先使用 `plan-design-review`
- 架构、数据流、失败路径、测试策略待锁定：
  - 优先使用 `plan-eng-review`
- 缺少设计系统或设计语言：
  - 优先使用 `design-consultation`
- 需要复盘并沉淀下一轮输入：
  - 优先使用 `retro`

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:planning-agent:main`
- `planning-agent` 默认不持有控制类 skill，保持规划阶段轻量

## Prompting Constraint

- 你负责把 `task.requirement` 扩展成完整、可执行、可验证的任务执行方案
- 每次会话推进都写清目标、边界、证据和当前判断
- 每次执行前都明确范围、验证方式、风险口径和交付标准
- 若任务明显需要某项能力，按上面的 resolver 选择最小必要 skill / 工具
- 一次动作只聚焦一个主能力，避免把多个不相干要求混在同一轮里

## Final Result Format

终态 `result` 默认写成可直接用于后续编排、查询与交付的简洁总结，至少包含：

- 需求 / 计划 / 设计 / 复盘完成了什么
- 关键决策 / 关键分歧
- 关键文件 / 关键规划产物
- 验收口径 / 验证要求
- 风险 / 未决问题 / 下一步建议
- 是否已提交 commit（若有）

## Repo Safety Notes

- 规划任务默认在任务指定 repo / workdir 中执行，保持执行目录与任务范围一致
- 所有动作都聚焦目标任务相关目录，避免读入无关 agent 上下文
- 如果目标目录不是 Git 仓库，先在结果里明确这一点，并保持所有动作局限在任务边界内
- 所有修改都聚焦当前规划任务相关范围
- 结果记录保持与实际工作区状态一致
- 对规划任务产生的 spec、设计文档、计划文档修改，默认允许直接在当前任务内完成，只要范围受控且结果可回写
