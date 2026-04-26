# USER.md - About Your Human

_记录你正在服务的用户信息，并持续更新。_

- **Name:**
- **What to call them:**
- **Pronouns:** _(optional)_
- **Timezone:**
- **Notes:**

## Coding Preferences

- **主要语言/框架：**
- **包管理与构建工具：**
- **代码风格偏好：**（简洁 / 严格类型 / 注释密度）
- **测试要求：**（是否强制测试、覆盖率目标）
- **交付偏好：**（先最小可用，再迭代；或一次性完整）

## Project Context

- **当前项目：**
- **近期目标：**
- **关键约束：**（时间、兼容性、依赖、上线窗口）
- **高风险区域：**（核心模块、历史脆弱点）

## Known Workflow Preferences

- `task-bridge` 只做任务编排；不要把底层运行环境配置或验证当成本项目任务目标。
- worker 收到 `[TASK_DISPATCH]` 后直接成为任务 owner，不创建额外执行交接层。
- 如果任务指定 repo / worktree / cwd / 工作路径，先阅读该路径下的 `AGENTS.md`（若存在），再推进实现。
- task contract 需要写清目标、范围、验收和验证；代码事实、文件细节和实现上下文由 worker 读取仓库补齐。

## Collaboration Notes

- 用户更喜欢的汇报方式：
- 用户反感的行为：
- 需要优先记住的决策：

---

了解越准确，任务执行质量越高，工程交付越稳定。
