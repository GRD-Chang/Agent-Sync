# TOOLS.md - Local Notes

本文件只记录这个工作区的本地环境约束与入口，不重复展开 skill 通用说明。

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

## Coding Entry

- 优先使用已配置到 PATH 的 `codex`
- 默认权限等级：
  - `codex --yolo`
- 执行要求：
  - 使用 Codex 时给予最高权限 `--yolo`
  - prompt 中继续写清完整上下文、范围、验证方式、风险口径和交付标准

## Skill Prompt Pattern

如果需要让 Codex 使用某项技能，在 prompt 中直接使用下面的格式：

`$技能名 任务说明`

例如：

- `$autoplan 基于现有需求和仓库上下文，自动完成 CEO、设计、工程三个维度的计划审查，输出可执行方案。`

如果一个任务天然需要技能支持，优先用这种写法，不要只写抽象要求。

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
  - `$office-hours ...`
- 需要一轮完整的自动计划审查：
  - `$autoplan ...`
- 产品价值、范围、目标密度待判断：
  - `$plan-ceo-review ...`
- 交互、视觉、状态设计待评估：
  - `$plan-design-review ...`
- 架构、数据流、失败路径、测试策略待锁定：
  - `$plan-eng-review ...`
- 缺少设计系统或设计语言：
  - `$design-consultation ...`
- 需要复盘并沉淀下一轮输入：
  - `$retro ...`

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:planning-agent:main`
- Codex 的具体调用方式、会话管理与长任务处理由当前运行环境统一定义
- `planning-agent` 默认不持有控制类 skill，保持规划阶段轻量

## Prompting Constraint

- 你负责把 `task.requirement` 扩展成完整、可执行、可验证的 Codex prompt
- 每次 Codex 调用都写清完整上下文
- 每次 prompt 都明确范围、验证方式、风险口径和交付标准
- 若任务明显需要某项技能，在 prompt 中用 `"$技能名 任务"` 的形式显式写出
- 一个 prompt 可以只聚焦一个主技能，避免把多个不相干技能混在同一条指令里

## Final Result Format

终态 `result` 默认写成可直接用于后续编排、查询与交付的简洁总结，至少包含：

- 需求 / 计划 / 设计 / 复盘完成了什么
- 关键决策 / 关键分歧
- 关键文件 / 关键规划产物
- 验收口径 / 验证要求
- 风险 / 未决问题 / 下一步建议
- 是否已提交 commit（若有）

## Repo Safety Notes

- 规划任务默认在任务指定 repo / workdir 中启动 Codex，保持执行目录与任务范围一致
- Codex 只在目标任务相关目录中运行，避免读入无关 agent 上下文
- 如果目标目录不是 Git 仓库，按 `coding-agent` skill 的规则组织执行环境
- 所有修改都聚焦当前规划任务相关范围
- 结果记录保持与实际工作区状态一致
- 对规划任务产生的 spec、设计文档、计划文档修改，默认允许直接在当前任务内完成，只要范围受控且结果可回写
