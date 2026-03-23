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

- `$review 审查当前分支 diff，列出高风险问题，并给出可执行修复建议。`
- `$cso 审查这个登录接口的安全问题，重点看鉴权、注入、敏感信息泄露。`
- `$qa 对本地运行的页面做缺陷检查，发现问题后直接修复并复测。`
- `$qa-only 对 staging 页面做一次只读 QA，输出复现步骤和风险分级。`
- `$design-review 审查这个页面的视觉层级、间距和交互一致性，并直接修复明显问题。`
- `$benchmark 对当前页面建立性能基线，并和修改前结果做对比。`

如果一个任务天然需要技能支持，优先用这种写法，不要只写抽象要求。

## 常用技能

### 评审与安全

- `review`
  - 代码审查、diff 风险检查、结构性问题发现
- `cso`
  - 安全审查、攻击面分析、凭据与依赖风险检查

### 浏览器与页面验证

- `browse`
  - 真实浏览器操作、页面复现、截图、状态检查
- `setup-browser-cookies`
  - 导入登录态 cookie，验证受保护页面

### QA 与设计验证

- `qa`
  - 找问题、直接修复并复测
- `qa-only`
  - 只输出 QA 报告，不做代码修改
- `design-review`
  - 审查已实现页面的视觉层级、交互细节和一致性

### 性能验证

- `benchmark`
  - 建立性能基线、做前后对比、检查回归

### 控制类技能

- `careful`
  - 运行危险命令前增加显式提醒
- `freeze`
  - 把修改锁定在明确目录内
- `guard`
  - 同时启用危险命令提醒和目录锁定
- `unfreeze`
  - 解除目录锁定

## 技能路由

按任务类型优先使用：

- 代码评审 / 风险判断：
  - `$review ...`
- 安全 / 鉴权 / 注入 / 隐私风险：
  - `$cso ...`
- 页面复现 / Web 流程验证 / 登录态测试：
  - 先 `$setup-browser-cookies ...`，再 `$browse ...`
- 找 bug 并顺手修：
  - `$qa ...`
- 只给问题单，不改代码：
  - `$qa-only ...`
- 界面质量 / 视觉一致性 / 交互细节：
  - `$design-review ...`
- 性能回归 / 页面速度 / 资源体积：
  - `$benchmark ...`
- 高风险修复或局部热修：
  - 先 `$freeze ...` 或 `$guard ...`，再执行实现或验证任务

## Session Notes

- 当前工作模式：常驻主会话 worker
- 默认主会话：`agent:quality-agent:main`
- Codex 的具体调用方式、会话管理与长任务处理由当前运行环境统一定义

## Prompting Constraint

- 你负责把 `task.requirement` 扩展成完整、可执行、可验证的 Codex prompt
- 每次 Codex 调用都写清完整上下文
- 每次 prompt 都明确范围、验证方式、风险口径和交付标准
- 若任务明显需要某项技能，在 prompt 中用 `"$技能名 任务"` 的形式显式写出
- 一个 prompt 可以只聚焦一个主技能，避免把多个不相干技能混在同一条指令里

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
- 对 review / qa / design-review / benchmark 衍生出的局部修复，默认允许直接在当前任务内完成，只要范围受控且证据可回写
- 若修复已扩展为跨模块新功能、复杂重构或大范围架构调整，应提示 team-leader 重新拆任务
