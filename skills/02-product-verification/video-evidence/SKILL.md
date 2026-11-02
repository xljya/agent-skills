---
name: video-evidence
description: 把 agent 实际操作的过程录成带字幕的视频，让人能亲眼看到"到底测了什么、做了什么"：演示、bug 复现视频、PR 附带证据、交付前给人过目。只录过程，不做 pass/fail 断言，也不代表"已验证正确"。可以和 step-assertions 搭配使用，但两者互不依赖。也含自由探索录屏（agent-browser）和终端录制（asciinema / tmux / ffmpeg）。
---

# video-evidence：录屏留证

灵感来自 Thariq《How We Use Skills》的「Product Verification」：**让 agent 录下它输出的视频，让你能清楚看到它到底测了什么。** 本技能只做这一件事：把 agent 做过的操作忠实地录成一段人能看的视频，附带逐步截图和一份时间线。

**它不是断言系统。** 视频只能证明"做了这些操作、屏幕上出现了这些画面"，不能单独证明"结果正确"。需要机器判定对错时，另外配合 `step-assertions` 技能（可选，不依赖它）。

## 什么时候用

- 给人看 agent 测了什么、点了哪里：演示、走查、交付前过目。
- 录 **bug 复现视频**：把复现步骤写成 spec，一键录出来贴到 issue。
- 给 **PR 附证据**：改了 UI，附一段操作录像和关键截图。
- 自由探索一个页面或 CLI 工具，把过程留下来（见下面的 agent-browser / 终端路线）。
- 不适用：需要自动判定 pass/fail（用 `step-assertions`）；页面里有大量敏感信息且无法脱敏（见"密钥与隐私"）。

## 准备（一次性）

```bash
python3 -m venv .venv && . .venv/bin/activate      # 系统 Python 不允许直接 pip install 时用虚拟环境
pip install playwright pyyaml                      # pyyaml 只在用 .yaml spec 时需要
playwright install chromium                        # 缺系统库时: playwright install --with-deps chromium
# 可选: ffmpeg，用来转 mp4（发给人最通用）和 gif
```

## 写 step spec

spec 是 YAML 或 JSON，**只有动作，没有断言**。每步恰好一个动作键，可选 `name`（视频字幕和时间线里显示的文字）。完整例子见 `examples/demo-session.yaml`。

```yaml
name: 复现：添加待办后勾选
base_url: http://127.0.0.1:3000
viewport: { width: 1280, height: 720 }
timeout_ms: 8000
# allowed_hosts: [127.0.0.1]      # 可选: 只允许访问这些主机，其它请求被拦截并记入 steps.md
steps:
  - note: "复现步骤：先添加，再勾选"        # 在视频里显示一条蓝色说明字幕
  - goto: /index.html
  - name: 输入待办
    fill: { selector: "#new-item", value: "买牛奶" }
  - press: { selector: "#new-item", key: "Enter" }
  - click: "#list li:first-child input[type=checkbox]"
  - scroll: bottom
  - screenshot: final-state
```

| 动作 | 写法 | 说明 |
|---|---|---|
| `note` | `note: "文字"`，可加 `duration_ms`（默认 1800） | 视频里显示说明字幕，用来解释"接下来要看什么" |
| `goto` | `goto: /path` 或完整 URL | 打开页面 |
| `click` | `click: "<selector>"` | 点击，selector 用 Playwright 语法（CSS、`text=...`、`role=button[name="..."]`）；有光标/点击高亮 |
| `fill` | `fill: {selector, value}` | 输入；密码用 `value_env: VAR` 或 `secret: true`，字幕和时间线里显示 `***` |
| `press` | `press: {selector, key}` 或 `press: Enter` | 按键 |
| `select` | `select: {selector, value}` | 下拉选择 |
| `wait_for` | `wait_for: "<selector>"` 或 `{selector, state}` | 等元素出现；等不到会报错并停止 |
| `wait_ms` | `wait_ms: 800` | 固定停顿，让观众看清 |
| `scroll` | `scroll: down \| up \| top \| bottom`，或 `{selector: "..."}` | 平滑滚动 |
| `screenshot` | `screenshot: name` | 额外命名截图（每步本来就会自动截一张） |

每步的字幕默认是 `Step 3/10: <动作或 name>`，想让观众看懂就给重要步骤写 `name`，在关键位置插 `note`。

## 运行

```bash
python scripts/record_session.py spec.yaml --out ./recording --mp4 --slow-mo 250
```

| 参数 | 作用 |
|---|---|
| `--out DIR` | 输出目录（每次运行会清空重建） |
| `--mp4` / `--gif` | 用 ffmpeg 额外生成 `video.mp4` / `video.gif` |
| `--slow-mo MS` | 每个浏览器动作之间放慢 MS 毫秒，演示用，建议 200–400 |
| `--hold-ms MS` | 每步结束后字幕停留时间（默认 700） |
| `--headed` | 有界面运行 |
| `--no-cursor` | 关掉光标和点击高亮（默认开启：红点跟随鼠标，点击时有红色涟漪） |
| `--base-url URL` | 覆盖 spec 里的 base_url |

某一步执行出错（找不到元素、超时等）时，脚本把错误写进时间线、视频里字幕变红，然后**停止**，退出码 1。这只是"没跑完"的记录，不是断言。退出码 `0` 表示所有步骤都执行完，`2` 表示 spec 或环境有问题。

输出：

```
recording/
├── video.webm / video.mp4 / video.gif   # 带字幕和光标高亮的录像
├── steps.md                             # 时间线：步骤、视频内时间戳、动作详情、结果、截图
├── steps.json                           # 同上，结构化
└── screenshots/                         # 每步一张：01-done.png … ；出错那步是 NN-error.png
```

`steps.md` 里的"Video time"是近似值（误差约 ±1 秒），方便你跳到视频的对应位置。

## 汇报时怎么说

1. **发 mp4**（`--mp4`），加上关键截图；不要只给本地路径，要让人能打开看。
2. 用一两句话说清**视频展示了什么**，例如"视频展示了：打开页面 → 添加两项待办 → 勾选第一项，最后列表显示 1 / 2 完成"。
3. **不要仅凭视频就说"已验证正确"。** 视频是过程记录。如果需要对错结论，说明还没有做程序化断言，或配合 `step-assertions` 给出报告。
4. 出错停止的情况如实说：停在第几步、错误信息、对应截图。

## 密钥与隐私

- 密码、token 用 `value_env` 或 `secret: true`，从环境变量传入，不要写进 spec。脚本会在字幕和时间线里显示 `***`，但**视频和截图拍到的是真实屏幕**：普通文本框里输入的内容会被录下来。录登录步骤时优先用 `type=password` 的输入框（浏览器显示为圆点），或者先登录好再录后面的步骤。
- 用测试账号和测试数据，不要用用户的真实账号。录制前确认页面上没有别人的个人信息。
- **不要对生产环境的写操作（下单、发消息、删除、付款）直接录**，除非用户明确批准；默认对本地或 staging，必要时用 `allowed_hosts` 限定范围。
- 视频和截图可能含敏感信息，**不要提交进公开仓库**。输出目录放在仓库之外，或加进 `.gitignore`；分享之前自己先过一遍。

## 路线二：agent-browser 自由探索录屏

不想先写 spec、只想"边摸索边录"时，用 [agent-browser](https://github.com/vercel-labs/agent-browser)（Vercel Labs，给 agent 用的浏览器命令行工具）：

```bash
npm install -g agent-browser && agent-browser install     # Linux 缺系统库: agent-browser install --with-deps
agent-browser open http://127.0.0.1:3000
agent-browser record start ./demo.webm --cursor           # 开始录像，--cursor 显示光标（需要 ffmpeg）
agent-browser snapshot -i                                 # 列出可交互元素，带 @e1、@e2 引用
agent-browser click @e3
agent-browser fill @e4 "测试内容"
agent-browser record stop                                 # 结束并写出 demo.webm
agent-browser close
```

这条路线灵活、省 token，适合探索和一次性演示；缺点是没有每步字幕和时间线，操作不可重复（`@eN` 引用每次快照都可能变）。要稳定、可重复、带字幕的录像，把探索到的步骤写成 spec，用 `record_session.py` 重录一遍。同样的汇报和隐私规则适用。

## 路线三：终端 / CLI 录制

- **asciinema**（推荐，文本可回放）：`asciinema rec session.cast`，操作完 `exit`；`asciinema play session.cast` 回放；装了 `agg` 可以 `agg session.cast session.gif`。也可以录一条命令：`asciinema rec -c "your-cli --flag" session.cast`。
- **tmux 抓屏**（交互式程序 / TUI）：`tmux new -d -s v 'your-cli'`；用 `tmux send-keys -t v '输入' Enter` 驱动；`tmux capture-pane -t v -p > screen-01.txt` 每步存一份当前屏幕文本。这是文本证据，可以附在汇报里。
- **ffmpeg x11grab**（有 X 显示的桌面环境）：`ffmpeg -f x11grab -video_size 1280x720 -framerate 15 -i :0 -t 30 -pix_fmt yuv420p out.mp4`；无头环境没有画面可录，用上面两种。

终端录制同样要留意：命令和输出里不要有密钥，别对生产环境跑破坏性命令，录像别提交进公开仓库。
