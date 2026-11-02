# Product Verification｜产品验证

实际操作正在运行的产品，验证功能是否正常。

**放什么**：驱动浏览器或接口走一遍注册、下单、后台等流程，确认真的能用。

**示例**：`signup-driver` · `checkout` · `admin`

每个技能一个子文件夹：`02-product-verification/<技能名>/SKILL.md`。

## 已收录

| 技能 | 用途 |
|---|---|
| [record-verify](record-verify/SKILL.md) | 用 Playwright 驱动网页，录整段视频、每步断言，输出视频 + 截图 + pass/fail 报告 + console 错误 + 失败请求的证据包；附 CLI/终端验证脚本。 |
