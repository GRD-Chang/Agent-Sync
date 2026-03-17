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

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:quality-agent:main`
- Codex 的具体调用方式、会话管理与长任务处理由当前运行环境统一定义

## Prompting Constraint

- 你负责把 `task.requirement` 扩展成完整、可执行、可验证的 Codex prompt
- 每次 Codex 调用都写清完整上下文
- 每次 prompt 都明确范围、验证方式、风险口径和交付标准

## Final Result Format

终态 `result` 默认写成可直接用于后续编排、查询与交付的简洁总结，至少包含：

- 审查 / 测试 / 文档 / 优化完成了什么
- 关键文件 / 关键问题
- 验证依据
- 风险分级
- 限制 / 未完成项 / 下一步建议
- 是否已提交 commit（若有）

## Repo Safety Notes

- 普通工程任务在任务指定 repo / workdir 中启动 Codex，保持执行目录与任务范围一致
- Codex 只在目标任务相关目录中运行，避免读入无关 agent 上下文
- 如果目标目录不是 Git 仓库，按 `coding-agent` skill 的规则组织执行环境
- 如果任务位于 Git 仓库且结果满足验收标准，可继续由 Codex CLI 完成当前任务相关 commit
- 所有修改都聚焦当前任务相关范围
- 结果记录保持与实际工作区状态一致
