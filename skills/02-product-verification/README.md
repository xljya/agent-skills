# Product Verification｜产品验证

实际操作正在运行的产品，验证功能是否正常。

**放什么**：驱动浏览器或接口走一遍注册、下单、后台等流程，确认真的能用。

**示例**：`signup-driver` · `checkout` · `admin`

每个技能一个子文件夹：`02-product-verification/<技能名>/SKILL.md`。

## 已收录

两个技能对应 Thariq 文中的两种互相独立的做法，可以单独用，也可以搭配用，互不依赖。

| 技能 | 用途 |
|---|---|
| [video-evidence](video-evidence/SKILL.md) | 录屏留证：把 agent 的操作录成带字幕的视频（含截图和时间线），给人看"到底测了什么"。不做断言；含 agent-browser 自由探索录屏和终端录制。 |
| [step-assertions](step-assertions/SKILL.md) | 逐步断言：每一步由机器检查状态，输出 pass/fail 报告、console 错误和失败请求。不录视频；含 CLI 输出断言脚本。 |
