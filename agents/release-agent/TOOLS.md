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

- `$ship 基于当前分支和发布要求，完成发版前收口、跑必要检查、生成 PR 所需结果。`

如果一个任务天然需要技能支持，优先用这种写法，不要只写抽象要求。

## 常用技能

### 发布准备与部署配置

- `setup-deploy`
  - 配置部署平台、生产地址、健康检查和状态命令
- `ship`
  - 做发版前收口、检查、创建 PR 和交付准备

### 上线与发布后观察

- `land-and-deploy`
  - 合并 PR、等待 CI 与 deploy、验证生产状态
- `canary`
  - 上线后持续观察错误、性能异常和页面故障

### 文档同步

- `document-release`
  - 根据本次交付更新 README、架构文档、贡献文档和 CHANGELOG

### 控制类技能

- `careful`
  - 运行危险命令前增加显式提醒
- `guard`
  - 同时启用危险命令提醒和编辑边界控制

## 技能路由

按任务类型优先使用：

- 部署平台尚未配置、生产地址或健康检查缺失：
  - `$setup-deploy ...`
- 正式发版前收口、创建 PR、整理发布动作：
  - `$ship ...`
- 合并、部署、等待 CI / deploy 并验证线上状态：
  - `$land-and-deploy ...`
- 上线后短期持续观察：
  - `$canary ...`
- 发版后同步文档与说明：
  - `$document-release ...`
- 生产、高风险或不可逆动作：
  - 先 `$careful ...` 或 `$guard ...`，再执行主要交付任务

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:release-agent:main`
- Codex 的具体调用方式、会话管理与长任务处理由当前运行环境统一定义

## Prompting Constraint

- 你负责把 `task.requirement` 扩展成完整、可执行、可验证的 Codex prompt
- 每次 Codex 调用都写清完整上下文
- 每次 prompt 都明确范围、验证方式、风险口径和交付标准
- 若任务明显需要某项技能，在 prompt 中用 `"$技能名 任务"` 的形式显式写出
- 一个 prompt 可以只聚焦一个主技能，避免把多个不相干技能混在同一条指令里

## Final Result Format

终态 `result` 默认写成可直接用于后续编排、查询与交付的简洁总结，至少包含：

- 发布 / 部署 / 文档同步完成了什么
- 关键环境 / 关键链接 / 关键交付对象
- 验证依据
- 风险 / 回滚口径 / 未完成项 / 下一步建议
- 是否已提交 commit / 创建 PR / 完成 deploy（若有）

## Repo Safety Notes

- 普通交付任务在任务指定 repo / workdir 中启动 Codex，保持执行目录与任务范围一致
- Codex 只在目标任务相关目录中运行，避免读入无关 agent 上下文
- 如果目标目录不是 Git 仓库，按 `coding-agent` skill 的规则组织执行环境
- 所有修改都聚焦当前交付任务相关范围
- 结果记录保持与实际工作区状态一致
- 对发布准备、部署配置、发版文档同步相关的局部修改，默认允许直接在当前任务内完成，只要范围受控且证据可回写
