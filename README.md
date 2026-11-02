# agent-skills

我收藏的 Agent 技能。每个技能是 `SKILL.md`（YAML frontmatter + Markdown 正文），可用于 Grok Bot、Cursor、Claude Code 等。

## 分类

按九类整理，路径是 `skills/<分类>/<技能名>/SKILL.md`。分类参考 Thariq 的 [How We Use Skills](https://x.com/trq212/status/2033949937936085378)。

| 分类 | 中文 | 说明 |
|---|---|---|
| [01-library-api-reference](skills/01-library-api-reference/) | 库与 API 参考 | 内部库、命令行工具、SDK 的用法和容易踩的坑。 |
| [02-product-verification](skills/02-product-verification/) | 产品验证 | 实际操作正在运行的产品，验证功能是否正常。 |
| [03-data-analysis](skills/03-data-analysis/) | 数据与分析 | ID、字段名、常用查询写法。 |
| [04-business-automation](skills/04-business-automation/) | 业务自动化 | 把跨多个工具的流程变成一条命令。 |
| [05-scaffolding-templates](skills/05-scaffolding-templates/) | 脚手架与模板 | 符合框架规范的样板代码。 |
| [06-code-quality-review](skills/06-code-quality-review/) | 代码质量与评审 | 能让交付质量更高的方法论。 |
| [07-ci-cd-deployment](skills/07-ci-cd-deployment/) | 持续集成与部署 | 安全地提交、推送、部署。 |
| [08-incident-runbooks](skills/08-incident-runbooks/) | 故障处理手册 | 从现象到排查再到报告。 |
| [09-infrastructure-ops](skills/09-infrastructure-ops/) | 基础设施运维 | 带安全确认的清理与维护。 |

## 技能列表

| 技能 | 分类 | 用途 | 来源 |
|---|---|---|---|
| [technical-writing](skills/06-code-quality-review/technical-writing/SKILL.md) | 代码质量与评审 | 写文档、RFC、README、PR 描述、commit message 的写作规范 | [cursor/plugins pstack](https://github.com/cursor/plugins/tree/main/pstack/skills/technical-writing) |
| [video-evidence](skills/02-product-verification/video-evidence/SKILL.md) | 产品验证 | 录屏留证：把 agent 的操作录成带字幕的视频、截图和时间线给人看，不做断言 | 自写，参考 Thariq《How We Use Skills》 |
| [step-assertions](skills/02-product-verification/step-assertions/SKILL.md) | 产品验证 | 逐步断言：每步程序化检查状态，输出 pass/fail 报告、console 错误和失败请求，不录视频 | 自写，参考 Thariq《How We Use Skills》 |
