# TOOLS.md - Local Notes

本文件只记录这个工作区的本地环境约束、`task-bridge` 命令和执行边界；不维护完整 skill 清单。

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

## Skill Selection

- 收到任务后，先查看当前会话可用的 skills；本文件不重复枚举。
- 如果存在匹配当前 task 目标、范围、验收标准和验证要求的 skill，优先使用该 skill 组织执行。
- 没有匹配 skill，或 skill 不适合当前边界时，再直接阅读材料、分析方案并整理规划证据。
- 不要机械使用无关 skill；skill 选择必须服务于当前任务的澄清、规划和收口。

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:planning-agent:main`
- 规划阶段默认保持轻量，不为了触发 skill 而增加流程

## Prompting Constraint

- 你负责把 `task.requirement` 收敛成规划方案、sprint contract、验收口径、验证要求和后续任务建议
- 每次会话推进都写清目标、边界、证据和当前判断
- 每次执行前都明确范围、验证方式、风险口径和交付标准
- 若当前会话存在匹配任务的 skill，优先使用该 skill；没有匹配 skill 时再直接使用工具和命令
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
