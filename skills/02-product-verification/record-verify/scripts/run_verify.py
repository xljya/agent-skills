#!/usr/bin/env python3
"""record-verify runner: 用 Playwright 跑一份 step spec，录视频、逐步断言、产出证据包。

用法:
    python run_verify.py spec.yaml --out ./evidence [--headed] [--keep-going]
                         [--trace] [--mp4] [--gif] [--strict] [--base-url URL]

退出码: 0 = 全部通过, 1 = 有步骤失败 (或 --strict 下有 console 错误/请求失败), 2 = spec 或环境错误。
依赖: playwright (必需), pyyaml (仅当 spec 是 .yaml/.yml), ffmpeg (可选，用于 mp4/gif)。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

ACTIONS = [
    "goto", "click", "fill", "press", "select", "wait_for", "wait_ms",
    "assert_visible", "assert_not_visible", "assert_text", "assert_url",
    "assert_count", "assert_eval", "screenshot",
]


class StepError(Exception):
    """断言或动作失败。"""


class SpecError(Exception):
    """spec 写错了。"""


# ----------------------------------------------------------------- spec 加载
def load_spec(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SpecError("读取 YAML 需要 pyyaml: pip install pyyaml (或改用 .json spec)")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        raise SpecError("spec 顶层必须是对象，且包含非空的 steps 列表")
    return data


def expand_env(value):
    """把字符串里的 ${VAR} 换成环境变量；变量缺失直接报错，避免静默用空值。"""
    if isinstance(value, str):
        def repl(m):
            if m.group(1) not in os.environ:
                raise SpecError(f"环境变量 {m.group(1)} 未设置 (spec 里用了 ${{{m.group(1)}}})")
            return os.environ[m.group(1)]
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)
    return value


def split_step(step: dict, idx: int):
    if not isinstance(step, dict):
        raise SpecError(f"第 {idx} 步必须是对象")
    found = [k for k in step if k in ACTIONS]
    if len(found) != 1:
        raise SpecError(f"第 {idx} 步必须恰好有一个动作键 {ACTIONS}，实际: {found or list(step)}")
    action = found[0]
    return action, step[action], step


def as_dict(arg, default_key: str) -> dict:
    return dict(arg) if isinstance(arg, dict) else {default_key: arg}


# ----------------------------------------------------------------- 步骤执行
def run_action(page, action, arg, step, ctx) -> str:
    """执行一步，返回给报告用的简短说明 (已脱敏)。失败抛 StepError。"""
    timeout = step.get("timeout_ms", ctx["timeout_ms"])
    base = ctx["base_url"]

    if action == "goto":
        url = urljoin(base + "/", arg) if base and not re.match(r"^\w+://", arg) else arg
        page.goto(url, timeout=max(timeout, 15000), wait_until=step.get("wait_until", "load"))
        return f"goto {url}"

    if action == "click":
        page.click(arg, timeout=timeout)
        return f"click {arg}"

    if action == "fill":
        a = as_dict(arg, "selector")
        if "value_env" in a:
            if a["value_env"] not in os.environ:
                raise SpecError(f"环境变量 {a['value_env']} 未设置")
            value, secret = os.environ[a["value_env"]], True
        else:
            raw_v = str(a.get("value", ""))
            value, secret = expand_env(raw_v), bool(a.get("secret")) or "${" in raw_v
        page.fill(a["selector"], value, timeout=timeout)
        return f"fill {a['selector']} = {'***' if secret else repr(value)}"

    if action == "press":
        a = as_dict(arg, "key")
        if a.get("selector"):
            page.press(a["selector"], a["key"], timeout=timeout)
        else:
            page.keyboard.press(a["key"])
        return f"press {a['key']}" + (f" on {a['selector']}" if a.get("selector") else "")

    if action == "select":
        a = as_dict(arg, "selector")
        page.select_option(a["selector"], a["value"], timeout=timeout)
        return f"select {a['selector']} = {a['value']}"

    if action == "wait_for":
        a = as_dict(arg, "selector")
        page.wait_for_selector(a["selector"], state=a.get("state", "visible"), timeout=a.get("timeout_ms", timeout))
        return f"wait_for {a['selector']} ({a.get('state', 'visible')})"

    if action == "wait_ms":
        page.wait_for_timeout(int(arg))
        return f"wait {int(arg)}ms"

    if action == "assert_visible":
        try:
            page.wait_for_selector(arg, state="visible", timeout=timeout)
        except Exception as e:
            raise StepError(f"元素不可见: {arg} ({first_line(e)})")
        return f"visible {arg}"

    if action == "assert_not_visible":
        try:
            page.wait_for_selector(arg, state="hidden", timeout=timeout)
        except Exception as e:
            raise StepError(f"元素仍然可见: {arg} ({first_line(e)})")
        return f"not visible {arg}"

    if action == "assert_text":
        a = as_dict(arg, "selector")
        sel = a["selector"]
        try:
            page.wait_for_selector(sel, state="attached", timeout=timeout)
        except Exception as e:
            raise StepError(f"找不到元素: {sel} ({first_line(e)})")
        # 轮询到超时，容忍异步渲染
        deadline = time.time() + timeout / 1000
        actual = ""
        while True:
            actual = (page.inner_text(sel) or "").strip()
            ok, expect = match_text(actual, a)
            if ok or time.time() > deadline:
                break
            page.wait_for_timeout(100)
        if not ok:
            raise StepError(f"文本不符: 期望 {expect}，实际 {actual[:200]!r}")
        return f"text of {sel} {expect}"

    if action == "assert_url":
        a = as_dict(arg, "contains")
        deadline = time.time() + timeout / 1000
        while True:
            ok, expect = match_text(page.url, a)
            if ok or time.time() > deadline:
                break
            page.wait_for_timeout(100)
        if not ok:
            raise StepError(f"URL 不符: 期望 {expect}，实际 {page.url}")
        return f"url {expect}"

    if action == "assert_count":
        a = as_dict(arg, "selector")
        deadline = time.time() + timeout / 1000
        while True:
            n = page.locator(a["selector"]).count()
            ok, expect = check_number(n, a)
            if ok or time.time() > deadline:
                break
            page.wait_for_timeout(100)
        if not ok:
            raise StepError(f"数量不符: {a['selector']} 期望 {expect}，实际 {n}")
        return f"count {a['selector']} {expect} (actual {n})"

    if action == "assert_eval":
        a = as_dict(arg, "js")
        deadline = time.time() + timeout / 1000
        while True:
            val = page.evaluate(a["js"])
            if "equals" in a:
                ok, expect = val == a["equals"], f"== {a['equals']!r}"
            elif "contains" in a:
                ok, expect = str(a["contains"]) in str(val), f"contains {a['contains']!r}"
            else:
                ok, expect = bool(val), "truthy"
            if ok or time.time() > deadline:
                break
            page.wait_for_timeout(100)
        if not ok:
            raise StepError(f"JS 断言失败: {a['js']} 得到 {val!r}，期望 {expect}")
        return f"eval {a['js']} {expect}"

    if action == "screenshot":  # 额外的命名截图，主截图由 runner 每步自动拍
        name = re.sub(r"[^\w.-]+", "_", str(arg))
        page.screenshot(path=str(ctx["shots_dir"] / f"extra-{name}.png"), full_page=bool(step.get("full_page")))
        return f"screenshot {name}"

    raise SpecError(f"未知动作 {action}")


def default_label(action, arg) -> str:
    if isinstance(arg, dict):
        arg = arg.get("selector") or arg.get("js") or arg.get("key") or arg.get("contains") or arg.get("equals") or ""
    return f"{action} {str(arg)[:60]}".strip()


def first_line(e) -> str:
    return str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__


def match_text(actual: str, a: dict):
    if "equals" in a:
        return actual == str(a["equals"]), f"== {a['equals']!r}"
    if "regex" in a:
        return re.search(a["regex"], actual) is not None, f"matches /{a['regex']}/"
    if "contains" in a:
        return str(a["contains"]) in actual, f"contains {a['contains']!r}"
    raise SpecError("文本断言需要 equals / contains / regex 之一")


def check_number(n: int, a: dict):
    if "equals" in a:
        return n == a["equals"], f"== {a['equals']}"
    parts, ok = [], True
    if "min" in a:
        ok &= n >= a["min"]; parts.append(f">= {a['min']}")
    if "max" in a:
        ok &= n <= a["max"]; parts.append(f"<= {a['max']}")
    if not parts:
        raise SpecError("assert_count 需要 equals / min / max")
    return ok, " and ".join(parts)


# ----------------------------------------------------------------- 视频字幕 (页面内 overlay)
CAPTION_JS = """
(args) => {
  let el = document.getElementById('__rv_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__rv_caption';
    el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:8px 14px;' +
      'font:600 15px/1.3 system-ui,sans-serif;color:#fff;pointer-events:none;';
    (document.documentElement || document.body).appendChild(el);
  }
  el.style.background = args.status === 'FAIL' ? 'rgba(200,30,30,.92)' :
                        args.status === 'PASS' ? 'rgba(20,130,60,.92)' : 'rgba(30,30,30,.88)';
  el.textContent = args.text;
}
"""


def set_caption(page, text, status="RUN"):
    try:
        page.evaluate(CAPTION_JS, {"text": text, "status": status})
    except Exception:
        pass  # 页面正在跳转时忽略


# ----------------------------------------------------------------- 报告
def write_reports(out: Path, report: dict):
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    icon = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️"}
    L = [f"# Verification report: {report['name']}", "",
         f"- **Result: {'✅ PASS' if report['status'] == 'PASS' else '❌ FAIL'}**",
         f"- Steps: {report['summary']['passed']} passed / {report['summary']['failed']} failed / "
         f"{report['summary']['skipped']} skipped (total {report['summary']['total']})",
         f"- Console errors: {len(report['console_errors'])} · Failed requests: {len(report['failed_requests'])}",
         f"- Started: {report['started_at']} · Duration: {report['duration_s']}s",
         *([f"- Reason: {report['fail_reason']}"] if report.get("fail_reason") else []),
         f"- Base URL: {report['base_url'] or '(none)'}", ""]
    arts = report["artifacts"]
    L += ["## Artifacts", ""] + [f"- {k}: `{v}`" for k, v in arts.items() if v] + [""]
    L += ["## Steps", "", "| # | Status | Step | Detail | Time | Screenshot |", "|---|---|---|---|---|---|"]
    for s in report["steps"]:
        shot = f"[img]({s['screenshot']})" if s.get("screenshot") else ""
        detail = (s.get("error") or s.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        L.append(f"| {s['index']} | {icon.get(s['status'], s['status'])} {s['status']} | {s['name']} | {detail} | {s['duration_ms']}ms | {shot} |")
    L += ["", "## Console errors", ""]
    L += [f"- `[{e['step']}]` {e['type']}: {e['text']}" for e in report["console_errors"]] or ["_none_"]
    L += ["", "## Failed network requests", ""]
    L += [f"- `[{r['step']}]` {r['method']} {r['url']} → {r['failure']}" for r in report["failed_requests"]] or ["_none_"]
    L.append("")
    (out / "report.md").write_text("\n".join(L), encoding="utf-8")


# ----------------------------------------------------------------- ffmpeg
def ffmpeg_convert(webm: Path, out: Path, want_mp4: bool, want_gif: bool) -> dict:
    res = {}
    if not (want_mp4 or want_gif):
        return res
    if not shutil.which("ffmpeg"):
        print("[warn] 没找到 ffmpeg，跳过 mp4/gif 转换", file=sys.stderr)
        return res
    if want_mp4:
        mp4 = out / "video.mp4"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(mp4)])
        if r.returncode == 0:
            res["mp4"] = mp4.name
    if want_gif:
        gif = out / "video.gif"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf",
                            "fps=8,scale=800:-1:flags=lanczos", str(gif)])
        if r.returncode == 0:
            res["gif"] = gif.name
    return res


# ----------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="record-verify: 录像 + 逐步断言 + 证据包")
    ap.add_argument("spec", help="spec 文件 (.yaml/.yml/.json)")
    ap.add_argument("--out", default="evidence", help="证据输出目录 (默认 ./evidence)")
    ap.add_argument("--base-url", help="覆盖 spec 里的 base_url")
    ap.add_argument("--headed", action="store_true", help="有界面运行 (默认 headless)")
    ap.add_argument("--keep-going", action="store_true", help="断言失败后继续跑后面的步骤")
    ap.add_argument("--strict", action="store_true", help="console 错误或请求失败也算 FAIL")
    ap.add_argument("--trace", action="store_true", help="额外保存 Playwright trace.zip")
    ap.add_argument("--mp4", action="store_true", help="用 ffmpeg 额外转 video.mp4")
    ap.add_argument("--gif", action="store_true", help="用 ffmpeg 额外生成 video.gif")
    ap.add_argument("--no-caption", action="store_true", help="视频里不叠加步骤字幕")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    try:
        spec = load_spec(Path(args.spec))
        steps = [split_step(s, i + 1) for i, s in enumerate(spec["steps"])]
    except (SpecError, json.JSONDecodeError, OSError) as e:
        print(f"[spec error] {e}", file=sys.stderr)
        return 2

    base_url = (args.base_url or spec.get("base_url") or "").rstrip("/")
    viewport = spec.get("viewport", {"width": 1280, "height": 720})
    allowed_hosts = spec.get("allowed_hosts") or []
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    shots_dir, raw_video = out / "screenshots", out / "_video_raw"
    shots_dir.mkdir(parents=True); raw_video.mkdir()

    ctx_info = {"base_url": base_url, "timeout_ms": int(spec.get("timeout_ms", 5000)), "shots_dir": shots_dir}
    report = {"name": spec.get("name", Path(args.spec).stem), "base_url": base_url,
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": "PASS", "steps": [], "console_errors": [], "failed_requests": [],
              "blocked_requests": [], "artifacts": {}}
    t_start = time.time()
    state = {"step": "setup"}
    stop = False

    with sync_playwright() as p:
        browser = getattr(p, args.browser).launch(headless=not args.headed, slow_mo=int(spec.get("slow_mo_ms", 0)))
        context = browser.new_context(viewport=viewport, record_video_dir=str(raw_video),
                                      record_video_size=viewport, ignore_https_errors=bool(spec.get("ignore_https_errors")))
        if args.trace:
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
        if allowed_hosts:
            def guard(route):
                host = urlparse(route.request.url).hostname or ""
                if route.request.url.startswith(("data:", "blob:", "about:")) or host in allowed_hosts:
                    route.continue_()
                else:
                    report["blocked_requests"].append({"step": state["step"], "url": route.request.url})
                    route.abort("blockedbyclient")
            context.route("**/*", guard)
        page = context.new_page()
        page.on("console", lambda m: m.type == "error" and report["console_errors"].append(
            {"step": state["step"], "type": "console.error", "text": m.text[:500]}))
        page.on("pageerror", lambda e: report["console_errors"].append(
            {"step": state["step"], "type": "pageerror", "text": str(e)[:500]}))
        page.on("requestfailed", lambda r: report["failed_requests"].append(
            {"step": state["step"], "method": r.method, "url": r.url[:300], "failure": (r.failure or "failed")}))
        page.on("response", lambda r: r.status >= 400 and report["failed_requests"].append(
            {"step": state["step"], "method": r.request.method, "url": r.url[:300], "failure": f"HTTP {r.status}"}))

        for i, (action, arg, raw) in enumerate(steps, 1):
            name = raw.get("name") or default_label(action, arg)
            rec = {"index": i, "name": name, "action": action, "status": "PASS", "detail": "", "error": None,
                   "duration_ms": 0, "screenshot": None}
            state["step"] = i
            if stop:
                rec["status"] = "SKIPPED"
                report["steps"].append(rec)
                continue
            if not args.no_caption:
                set_caption(page, f"Step {i}/{len(steps)}: {name}")
            t0 = time.time()
            try:
                rec["detail"] = run_action(page, action, arg, raw, ctx_info)
            except SpecError as e:
                rec["status"], rec["error"] = "FAIL", f"spec error: {e}"
                stop = True
            except StepError as e:
                rec["status"], rec["error"] = "FAIL", str(e)
            except Exception as e:  # Playwright 超时等
                rec["status"], rec["error"] = "FAIL", f"{type(e).__name__}: {first_line(e)}"
            rec["duration_ms"] = int((time.time() - t0) * 1000)
            if not args.no_caption:
                set_caption(page, f"Step {i}/{len(steps)}: {name} — {rec['status']}", rec["status"])
                page.wait_for_timeout(350)  # 让结果字幕在视频里停留一下
            shot = shots_dir / f"{i:02d}-{rec['status'].lower()}.png"
            try:
                page.screenshot(path=str(shot))
                rec["screenshot"] = f"screenshots/{shot.name}"
            except Exception:
                pass
            report["steps"].append(rec)
            if rec["status"] == "FAIL":
                report["status"] = "FAIL"
                print(f"  ✗ step {i} {name}: {rec['error']}")
                if not args.keep_going:
                    stop = True
            else:
                print(f"  ✓ step {i} {name}")

        video = page.video
        if args.trace:
            context.tracing.stop(path=str(out / "trace.zip"))
        context.close()  # 关闭后视频才会落盘
        vpath = Path(video.path()) if video else None
        browser.close()

    if vpath and vpath.exists():
        shutil.move(str(vpath), out / "video.webm")
        report["artifacts"]["video"] = "video.webm"
    shutil.rmtree(raw_video, ignore_errors=True)
    report["artifacts"].update(ffmpeg_convert(out / "video.webm", out, args.mp4, args.gif))
    if args.trace:
        report["artifacts"]["trace"] = "trace.zip (npx playwright show-trace / playwright show-trace)"
    report["artifacts"]["screenshots"] = "screenshots/"

    if args.strict and (report["console_errors"] or report["failed_requests"]):
        report["status"] = "FAIL"
        report["fail_reason"] = "--strict: console 错误或网络请求失败"
    s = report["steps"]
    report["summary"] = {"total": len(s), "passed": sum(x["status"] == "PASS" for x in s),
                         "failed": sum(x["status"] == "FAIL" for x in s),
                         "skipped": sum(x["status"] == "SKIPPED" for x in s)}
    report["duration_s"] = round(time.time() - t_start, 1)
    write_reports(out, report)
    print(f"\n{report['status']}  {report['summary']}  console_errors={len(report['console_errors'])} "
          f"failed_requests={len(report['failed_requests'])}\n证据包: {out}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
