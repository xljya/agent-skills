---
name: record-verify
description: 改完网页 UI 或流程之后，用真实浏览器把它跑一遍来证明它能用：录整段视频，每一步都做程序化断言，输出带视频、逐步截图、pass/fail 报告、console 错误和失败请求的证据包。用于验证、回归、交付前自检，或用户说"录个视频证明一下"。也含 CLI/终端程序的验证路线。
---

# record-verify：录屏 + 逐步断言的产品验证

灵感来自 Thariq《How We Use Skills》的「Product Verification」：让 agent **录下自己测试的视频**，让人能看到它到底测了什么，并且**在每一步对状态做程序化断言**。本技能把这两件事打包成可直接运行的脚本。

## 什么时候用

- 改了网页 UI、表单、登录/下单/注册等流程，需要证明"真的能用"。
- 要交付前做冒烟测试或回归检查，希望给人一份可复核的证据。
- 用户说"帮我验证一下"、"录个视频给我看"、"跑一遍流程"。
- 不适用：纯后端单元测试（用项目自己的测试框架）；需要大规模并发压测。

## 准备（一次性）

```bash
# 建议放在虚拟环境里（Debian/Ubuntu 的系统 Python 不允许直接 pip install）
python3 -m venv .venv && . .venv/bin/activate
pip install playwright pyyaml          # pyyaml 只在用 .yaml spec 时需要，用 .json 可不装
playwright install chromium            # 下载浏览器；缺系统库时用: playwright install --with-deps chromium
# 可选: ffmpeg（转 mp4 / gif）。没有也能跑，只是视频是 .webm
```

Node 项目也可以用 `npm i -D playwright && npx playwright install chromium`，但本技能的脚本是 Python 版。

## 写 step spec

spec 是一个 YAML（或 JSON）文件：每个 step 恰好有**一个动作键**，可选 `name`（写给人看的步骤名）、`timeout_ms`。完整例子见 `examples/example-spec.yaml`。

```yaml
name: 登录并下单
base_url: http://127.0.0.1:3000      # goto 的相对路径会拼在它后面
viewport: { width: 1280, height: 720 }
timeout_ms: 5000                      # 默认断言/等待超时
slow_mo_ms: 0                         # 可选: 每个动作之间放慢，视频更好看
# allowed_hosts: [127.0.0.1]          # 可选: 只允许访问这些主机，其它请求被拦截并记录（防止误打生产/第三方）
steps:
  - name: 打开登录页
    goto: /login
  - assert_visible: "form#login"
  - fill: { selector: "#email", value: "tester@example.com" }
  - fill: { selector: "#password", value_env: TEST_PASSWORD }   # 密码走环境变量，报告里显示 ***
  - click: "button[type=submit]"
  - assert_url: { contains: "/dashboard" }
  - assert_text: { selector: "h1", equals: "Dashboard" }
```

| 动作 | 写法 | 说明 |
|---|---|---|
| `goto` | `goto: /path` 或完整 URL | 打开页面 |
| `click` | `click: "<selector>"` | 点击，selector 用 Playwright 语法（CSS、`text=...`、`role=button[name="..."]`） |
| `fill` | `fill: {selector, value}` | 输入；密码用 `value_env: VAR` 或 `secret: true`，报告里会脱敏 |
| `press` | `press: {selector, key}` 或 `press: Enter` | 按键，不写 selector 就是全局键盘 |
| `select` | `select: {selector, value}` | 下拉选择 |
| `wait_for` | `wait_for: "<selector>"` 或 `{selector, state, timeout_ms}` | 等元素出现/消失 |
| `wait_ms` | `wait_ms: 500` | 固定等待，尽量少用，优先 `wait_for` |
| `assert_visible` / `assert_not_visible` | `assert_visible: "<selector>"` | 元素可见/不可见 |
| `assert_text` | `{selector, equals \| contains \| regex}` | 元素文本，超时内轮询 |
| `assert_url` | `{equals \| contains \| regex}` | 当前 URL |
| `assert_count` | `{selector, equals \| min \| max}` | 元素数量 |
| `assert_eval` | `{js, equals \| contains}`，都不写则要求 truthy | 在页面里执行 JS 表达式，断言**应用内部状态**（store、localStorage、DOM 属性等） |
| `screenshot` | `screenshot: name` | 额外命名截图（每步本来就会自动截一张） |

写 spec 的要点：

- **每个动作后面都跟至少一个断言**，断言要检查"结果状态"而不是"点了没报错"。
- 用稳定的 selector（`data-testid`、role、label），别用易变的 CSS 层级。
- 一个 spec 覆盖一条用户路径；很长的流程拆成几个 spec。
- 先跑一次看报告，再回头收紧断言；**也要故意写一个会失败的断言确认它真的会 FAIL**（见 `examples/failing-spec.yaml`），避免"永远绿"的假验证。

## 运行

```bash
# 先让被测服务跑起来（例如 npm run dev、或 python -m http.server 8765 --directory examples/demo-app）
python scripts/run_verify.py spec.yaml --out ./evidence --mp4
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--out DIR` | 证据包目录（每次运行会清空重建） |
| `--mp4` / `--gif` | 用 ffmpeg 额外生成 `video.mp4`（发给人最通用）/ `video.gif` |
| `--trace` | 额外保存 Playwright `trace.zip`，用 `playwright show-trace trace.zip` 看逐帧 DOM |
| `--keep-going` | 某步断言失败后继续跑完，一次看到所有问题（默认遇到第一个失败就停，后面标 SKIPPED） |
| `--strict` | console 错误或网络请求失败也算整体 FAIL（默认只在报告里警告） |
| `--headed` | 有界面运行，调试用 |
| `--base-url URL` | 覆盖 spec 里的 base_url，方便同一份 spec 跑 staging/本地 |
| `--no-caption` | 视频里不叠加步骤字幕（默认会在底部显示 `Step 3/16: … PASS/FAIL`，绿色通过、红色失败） |

退出码：`0` 全部通过，`1` 有失败，`2` spec 或环境有问题（比如缺 playwright、缺环境变量、spec 写错）。

## 读报告

证据包目录结构：

```
evidence/
├── report.md          # 给人看：总结果 + 每步 PASS/FAIL/SKIPPED + 耗时 + 截图链接 + console 错误 + 失败请求
├── report.json        # 给机器看：同样内容，结构化
├── video.webm         # 整段录像（带步骤字幕）
├── video.mp4/.gif     # --mp4 / --gif 时才有
├── screenshots/       # 每步一张：01-pass.png、03-fail.png …
└── trace.zip          # --trace 时才有
```

读的顺序：

1. `report.md` 顶部的 **Result**：PASS 还是 FAIL，几步通过/失败/跳过。
2. FAIL 的步骤：看 `Detail` 里的"期望 vs 实际"，再打开对应的 `NN-fail.png`，必要时看视频里红色字幕那一刻。
3. **Console errors** 和 **Failed network requests**：即使所有步骤都 PASS，这里有内容也要如实报告（页面看着正常但后台 404/报错是常见隐患），或用 `--strict` 让它们直接算 FAIL。
4. 判断是**产品 bug**还是 **spec 问题**（selector 过期、等待太短）：先确认再改，不要为了变绿去放宽断言。

## 规则

1. **每一步之后都要断言。** 没有断言的步骤不算验证。
2. **没有报告就不能说通过。** 只有跑完脚本、读过 `report.md`/`report.json` 且结果为 PASS，才能对人说"验证通过"；不能凭印象、也不能只凭"脚本没报错"。
3. **汇报时附上证据**：video（优先 mp4）、关键截图、`report.md` 摘要；失败时附失败步骤的截图和错误信息。如实说明哪些没验证到。
4. **密钥不进 spec、不进视频。** 密码/token 用 `value_env` 或 `secret: true`，从环境变量传入；不要把真实凭据写进 spec 或提交到仓库；注意视频和截图会拍到屏幕上显示的内容，避免对着含个人信息的页面录像，证据包分享前先检查。
5. **用测试账号和测试数据。** 不要用用户的真实账号做验证。
6. **不要对生产环境的写操作（下单、发消息、删除、付款、发邮件）直接运行**，除非用户明确批准；默认对本地或 staging 跑，必要时用 `allowed_hosts` 限定范围。
7. 失败了先报告，不要悄悄改 spec 或放宽断言让它变绿；修改 spec 要说明原因。
8. 证据包（视频、截图）可能含敏感信息，**不要提交进公开仓库**，输出目录放在仓库之外或加进 `.gitignore`。

## 可选：CLI / 终端程序的验证

脚本 `scripts/record_terminal.sh` 逐条执行命令、断言输出里包含某个字符串，产出 `session.log` 和逐条 PASS/FAIL 的 `report.md`：

```bash
# 断言文件每行: <命令> || <期望输出包含的字符串>，见 examples/terminal-spec.txt
bash scripts/record_terminal.sh ./evidence-cli examples/terminal-spec.txt
```

想要可回放的"录像"：

- **asciinema**：`asciinema rec -c "bash scripts/record_terminal.sh ./evidence-cli spec.txt" ./evidence-cli/session.cast`，用 `asciinema play` 回放；装了 `agg` 可以转成 gif。
- **tmux（交互式程序/TUI）**：`tmux new -d -s v 'your-cli'`，用 `tmux send-keys -t v '输入' Enter` 驱动，`tmux capture-pane -t v -p` 抓当前屏幕文本做断言，抓到的文本存档作为证据。
- **ffmpeg 录桌面**（有 X 显示时）：`ffmpeg -f x11grab -i :0 -t 30 out.mp4`；无头环境没有画面可录，用上面两种。

规则同上：每条命令都要有断言，别把密钥写进命令，别对生产环境跑破坏性命令。
