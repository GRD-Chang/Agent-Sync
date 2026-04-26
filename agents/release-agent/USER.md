# USER.md - About Your Human

_记录你正在服务的用户信息，并持续更新。_

- **Name:**
- **What to call them:**
- **Pronouns:** _(optional)_
- **Timezone:**
- **Notes:**

## Release Preferences

- **发布节奏偏好：**（快速发布 / 严格分阶段）
- **风险容忍度：**（保守 / 平衡 / 激进）
- **上线窗口限制：**
- **证据要求：**（必须附 PR / 日志 / 健康检查 / 截图）
- **文档同步要求：**（是否必须同时更新 README / CHANGELOG / spec）

## Environment Context

- **主要部署平台：**
- **生产地址：**
- **健康检查方式：**
- **回滚约定：**
- **高风险时段或禁发窗口：**

## Known Workflow Preferences

- 只有实现 evidence 和质量 evidence 基本齐备后，才进入发布收口。
- 生产、高风险或不可逆动作需要权限、窗口、验证和回滚口径清晰；缺失时阻塞而不是强推。
- 发布结果需要回写 PR / deploy / 文档 / canary / 健康检查等可复核证据。
- task contract 需要写清目标、范围、验收和验证；发布环境事实、配置和状态由 worker 读取材料补齐。

## Collaboration Notes

- 用户偏好的发布汇报粒度：
- 用户不能接受的跳过项：
- 需要长期记住的交付规则：

---

了解越准确，交付任务质量越高，上线风险也越可控。
