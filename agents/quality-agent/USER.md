# USER.md - About Your Human

_记录你正在服务的用户信息，并持续更新。_

- **Name:**
- **What to call them:**
- **Pronouns:** _(optional)_
- **Timezone:**
- **Notes:**

## Review Preferences

- **评审深度偏好：**（快速体检 / 全量深审）
- **风险阈值：**（哪些问题必须阻断）
- **输出格式偏好：**（列表 / 表格 / 按模块）
- **证据要求：**（是否必须附命令与复现步骤）
- **优先关注：**（安全 / 性能 / 可维护性 / 文档一致性 / 测试完整性）

## Project Risk Context

- **核心链路：**
- **历史事故点：**
- **发布窗口与限制：**
- **不可回归项：**

## Known Workflow Preferences

- 质量结论必须基于可复核证据，不只阅读 worker summary 就批准。
- `quality-agent` 同时承担 plan evaluation 和 implementation evaluation；结论必须明确为 `pass` / `needs-fix` / `blocked`。
- 对 blast radius 清晰、修复成本可控、属于当前质量任务自然延伸的问题，可以直接修复并复验。
- task contract 需要写清目标、范围、验收和验证；测试证据、diff 事实和风险细节由 worker 读取仓库补齐。

## Collaboration Notes

- 用户对“误报”容忍度：
- 用户偏好的建议粒度：
- 需要长期跟踪的问题类型：

---

了解越准确，任务质量越高，审核和交付判断越稳定。
