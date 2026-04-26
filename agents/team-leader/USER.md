# USER.md - About Your Human

_了解你正在服务的用户，并持续更新。_

- **Name:**
- **What to call them:**
- **Pronouns:** _(optional)_
- **Timezone:**
- **Notes:**

## Project Preferences

- **开发流程偏好：** 严格工程规范（每步 review）
- **沟通风格：** 简洁、结果导向
- **汇报频率：** 每步完成后汇报；长任务在无阶段完成时每 15 分钟心跳汇报
- **回传要求：** 执行完成必须回传到当前用户会话（不能只停留在 worker 主会话或内部会话）
- **决策偏好：** Critical 问题必须用户确认后才能跳过

## Team & Workflow Notes

- 用户的常见任务类型：
- 用户不希望跳过的流程步骤：
- 需要长期跟踪的项目：

## Known Orchestration Preferences

- `task-bridge` 只做编排；不要把底层运行环境配置或验证当成本项目任务目标。
- `team-leader` 是高层决策者和面向用户的收口者，不亲自承担具体设计、实现、测试或发布执行。
- 具体设计依赖 `planning-agent`，plan / implementation 质量判断依赖 `quality-agent`。
- 任务派发要提供目标、范围、验收和验证，不要求复制 worker 可通过读取仓库获得的全部上下文。
- 不要把任务切得过细；当前 agent 能力足够时，可以把 coherent sprint 作为完整 task 派发。

---

你对用户偏好理解越深，调度效率就越高。
