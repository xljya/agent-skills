---
name: step-assertions
description: 改完网页 UI 或流程之后，用真实浏览器按 step spec 跑一遍，并在每一步对状态做程序化断言（元素、文本、URL、数量、页面内 JS 状态），输出 pass/fail 报告，同时收集 console 错误和失败请求。用于验证、回归、交付前自检。不录视频；失败步骤自动截图。可以和 video-evidence 搭配使用，但两者互不依赖。也含 CLI 命令输出断言脚本。
---

# step-assertions：逐步断言

灵感来自 Thariq《How We Use Skills》的「Product Verification」：**在每一步对状态做程序化断言。** 本技能只做这一件事：按 spec 驱动浏览器，每一步之后由机器检查状态，给出 PASS/FAIL 报告。

**它不录视频。** 想给人看一段操作录像时，另外配合 `video-evidence` 技能（可选，不依赖它）。

## 什么时候用

- 改了网页 UI、表单、登录/下单/注册等流程，需要证明"真的能用"。
- 交付前做冒烟测试或回归检查，要一份可复核的 pass/fail 报告。
- 要同时抓页面里的 console 错误和失败的网络请求。
- 不适用：纯后端单元测试（用项目自己的测试框架）；大规模压测；只想给人看过程（用 `video-evidence`）。

## 准备（一次性）

```bash
python3 -m venv .venv && . .venv/bin/activate      # 系统 Python 不允许直接 pip install 时用虚拟环境
pip install playwright pyyaml                      # pyyaml 只在用 .yaml spec 时需要，用 .json 可不装
playwright install chromium                        # 缺系统库时: playwright install --with-deps chromium
```

## 写 step spec

spec 是 YAML 或 JSON：每步恰好一个动作键，可选 `name`、`timeout_ms`。完整例子见 `examples/example-spec.yaml`。

```yaml
name: 登录并下单
base_url: http://127.0.0.1:3000      # goto 的相对路径会拼在它后面
viewport: { width: 1280, height: 720 }
timeout_ms: 5000                      # 默认断言/等待超时
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
| `fill` | `fill: {selector, value}` | 输入；密码用 `value_env: VAR` 或 `secret: true`，报告里脱敏 |
| `press` | `press: {selector, key}` 或 `press: Enter` | 按键，不写 selector 就是全局键盘 |
| `select` | `select: {selector, value}` | 下拉选择 |
| `wait_for` | `wait_for: "<selector>"` 或 `{selector, state, timeout_ms}` | 等元素出现/消失 |
| `wait_ms` | `wait_ms: 500` | 固定等待，尽量少用，优先 `wait_for` |
| `assert_visible` / `assert_not_visible` | `assert_visible: "<selector>"` | 元素可见/不可见 |
| `assert_text` | `{selector, equals \| contains \| regex}` | 元素文本，超时内轮询 |
| `assert_url` | `{equals \| contains \| regex}` | 当前 URL |
| `assert_count` | `{selector, equals \| min \| max}` | 元素数量 |
| `assert_eval` | `{js, equals \| contains}`，都不写则要求 truthy | 在页面里执行 JS 表达式，断言**应用内部状态**（store、localStorage、DOM 属性等） |
| `screenshot` | `screenshot: name` | 额外命名截图 |

写 spec 的要点：

- **每个动作后面都跟至少一个断言**，断言要检查"结果状态"，而不是"点了没报错"。
- 用稳定的 selector（`data-testid`、role、label），别用易变的 CSS 层级。
- 一个 spec 覆盖一条用户路径；很长的流程拆开。
- **每套 spec 都要带一个故意会失败的断言来证明它真的会 FAIL**（见 `examples/failing-spec.yaml`），避免"永远绿"的假验证。

## 运行

```bash
# 先让被测服务跑起来（例如 npm run dev、或 python -m http.server 8765 --directory examples/demo-app）
python scripts/run_assertions.py spec.yaml --out ./evidence
```

| 参数 | 作用 |
|---|---|
| `--out DIR` | 输出目录（每次运行会清空重建） |
| `--keep-going` | 某步断言失败后继续跑完，一次看到所有问题（默认遇到第一个失败就停，后面标 SKIPPED） |
| `--strict` | console 错误或网络请求失败也算整体 FAIL（默认只在报告里警告） |
| `--screenshot-every-step` | 每步都截图（默认只在 FAIL 时截图） |
| `--trace` | 额外保存 Playwright `trace.zip`，用 `playwright show-trace trace.zip` 看逐帧 DOM |
| `--headed` | 有界面运行，调试用 |
| `--base-url URL` | 覆盖 spec 里的 base_url，同一份 spec 跑 staging/本地 |

退出码：`0` 全部通过，`1` 有失败，`2` spec 或环境有问题（缺 playwright、缺环境变量、spec 写错）。

## 读报告

```
evidence/
├── report.md          # 给人看：总结果 + 每步 PASS/FAIL/SKIPPED + 耗时 + console 错误 + 失败请求
├── report.json        # 给机器看：同样内容，结构化
├── screenshots/       # 默认只有失败步骤的截图 NN-fail.png；加 --screenshot-every-step 则每步一张
└── trace.zip          # --trace 时才有
```

读的顺序：

1. `report.md` 顶部的 **Result**：PASS 还是 FAIL，几步通过/失败/跳过。
2. FAIL 的步骤：看 `Detail` 里的"期望 vs 实际"，再看对应的 `NN-fail.png`。
3. **Console errors** 和 **Failed network requests**：即使所有步骤都 PASS，这里有内容也要如实报告（页面看着正常但后台 404/报错是常见隐患），或用 `--strict` 让它们直接算 FAIL。
4. 判断是**产品 bug**还是 **spec 问题**（selector 过期、等待太短）：先确认再改。

## 规则

1. **每一步之后都要断言。** 没有断言的步骤不算验证。
2. **没有报告就不能说通过。** 只有跑完脚本、读过 `report.md`/`report.json` 且结果为 PASS，才能对人说"验证通过"；不能凭印象，也不能只凭"脚本没报错"。
3. **汇报时附上报告**：`report.md` 摘要、失败步骤的截图和错误信息；如实说明哪些没验证到。
4. **每套 spec 都要带一个故意失败的断言**，确认它会 FAIL（`failing-spec.yaml` 的做法）。
5. **不要为了变绿放宽断言。** 失败了先报告；改 spec 要说明原因，不能悄悄删断言或把 `equals` 改成 `contains` 来蒙混。
6. **用测试账号和测试数据**，不要用用户的真实账号。
7. **不要对生产环境的写操作（下单、发消息、删除、付款、发邮件）直接运行**，除非用户明确批准；默认对本地或 staging 跑，必要时用 `allowed_hosts` 限定范围。
8. 密钥不进 spec：密码/token 用 `value_env` 或 `secret: true` 从环境变量传入，不要提交到仓库。报告和截图可能含页面内容，公开仓库不要提交输出目录。

## 配合 agent-browser：先探索，再固化成 spec

[agent-browser](https://github.com/vercel-labs/agent-browser)（Vercel Labs）是给 agent 用的浏览器命令行工具。它输出页面的可访问性快照，元素用 `@e1` 这类短引用表示，很省 token，适合**探索**一个还不熟的页面。它不适合当最终验证：引用每次快照都可能变，回放也不稳定。分工如下：

| 阶段 | 用什么 | 目的 |
|---|---|---|
| 探索 | agent-browser | 摸清页面结构，找到稳定的 selector，试通流程 |
| 验证 | `run_assertions.py` + spec | 步骤固定、可重复跑，每步断言，报告作为证据 |

安装：`npm install -g agent-browser && agent-browser install`（Linux 缺系统库时用 `agent-browser install --with-deps`）。

探索流程：

```bash
agent-browser open http://127.0.0.1:3000/login
agent-browser wait --load domcontentloaded
agent-browser snapshot -i                 # 只列可交互元素，带 @e1、@e2 引用
agent-browser fill @e3 "tester@example.com"
agent-browser click @e5
agent-browser get url                     # 看跳到了哪
agent-browser snapshot -i                 # 看新页面
agent-browser console && agent-browser errors   # 顺手看有没有报错
agent-browser close
```

把探索结果固化成 spec：

1. **不要把 `@eN` 写进 spec**，它只在当次快照里有效。把它换成稳定的 selector：快照里的 role 和 name 写成 `role=button[name="登录"]`，或用 label、`data-testid`、`text=...`。需要时可以用 `agent-browser get attr @e5 data-testid` 查属性。
2. 探索时每看到一个「结果」（跳转后的 URL、出现的标题、列表数量），就在 spec 里对应写一个 `assert_url`、`assert_text`、`assert_count`。
3. 跑 `run_assertions.py`，以它的报告为准。agent-browser 的探索过程不算验证结果。

## 可选：CLI / 终端程序的断言

脚本 `scripts/assert_terminal.sh` 逐条执行命令、断言输出里包含某个字符串，产出 `session.log` 和逐条 PASS/FAIL 的 `report.md`（不录屏）：

```bash
# 断言文件每行: <命令> || <期望输出包含的字符串>，见 examples/terminal-spec.txt
bash scripts/assert_terminal.sh ./evidence-cli examples/terminal-spec.txt
```

退出码 `0` 全部通过，`1` 有失败。规则同上：每条命令都要有断言（也要放一条故意失败的来证明会 FAIL），别把密钥写进命令，别对生产环境跑破坏性命令。交互式程序 / TUI 可以用 `tmux send-keys` 驱动、`tmux capture-pane -p` 抓屏幕文本再做断言。
