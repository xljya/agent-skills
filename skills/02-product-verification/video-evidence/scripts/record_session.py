#!/usr/bin/env python3
"""video-evidence 录屏器: 按 step spec 驱动浏览器，录下带字幕的视频，留下逐步截图和时间线。

这里没有 pass/fail 断言: 它只是把 agent 做过的事忠实录下来给人看。
某一步报错时，把错误写进时间线并停止（不是断言系统）。

用法:
    python record_session.py spec.yaml --out ./recording [--mp4] [--gif] [--slow-mo 300]
                             [--headed] [--no-cursor] [--base-url URL]

退出码: 0 = 所有步骤都执行完, 1 = 某步执行出错并已停止, 2 = spec 或环境错误。
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

ACTIONS = ["goto", "click", "fill", "press", "select", "wait_for", "wait_ms", "scroll", "screenshot", "note"]


class SpecError(Exception):
    pass


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


def expand_env(value: str) -> str:
    def repl(m):
        if m.group(1) not in os.environ:
            raise SpecError(f"环境变量 {m.group(1)} 未设置")
        return os.environ[m.group(1)]
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)


def as_dict(arg, default_key):
    return dict(arg) if isinstance(arg, dict) else {default_key: arg}


def split_step(step, idx):
    if not isinstance(step, dict):
        raise SpecError(f"第 {idx} 步必须是对象")
    found = [k for k in step if k in ACTIONS]
    if len(found) != 1:
        raise SpecError(f"第 {idx} 步必须恰好有一个动作键 {ACTIONS}，实际: {found or list(step)}")
    return found[0], step[found[0]], step


def first_line(e) -> str:
    t = str(e).strip()
    return t.splitlines()[0][:200] if t else type(e).__name__


# ------------------------------------------------------------ 动作 (只执行，不断言)
def run_action(page, action, arg, step, ctx) -> str:
    timeout = step.get("timeout_ms", ctx["timeout_ms"])
    base = ctx["base_url"]
    if action == "goto":
        url = urljoin(base + "/", arg) if base and not re.match(r"^\w+://", arg) else arg
        page.goto(url, timeout=max(timeout, 15000))
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
            raw = str(a.get("value", ""))
            value, secret = expand_env(raw), bool(a.get("secret")) or "${" in raw
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
    if action == "scroll":
        a = as_dict(arg, "to")
        if a.get("selector"):
            page.locator(a["selector"]).first.scroll_into_view_if_needed(timeout=timeout)
            return f"scroll to {a['selector']}"
        to = str(a.get("to", "down"))
        js = {"down": "window.scrollBy({top: window.innerHeight*0.8, behavior:'smooth'})",
              "up": "window.scrollBy({top: -window.innerHeight*0.8, behavior:'smooth'})",
              "top": "window.scrollTo({top: 0, behavior:'smooth'})",
              "bottom": "window.scrollTo({top: document.documentElement.scrollHeight, behavior:'smooth'})"}.get(to)
        if not js:
            raise SpecError("scroll 取值: down / up / top / bottom，或 {selector: ...}")
        page.evaluate(js)
        page.wait_for_timeout(500)
        return f"scroll {to}"
    if action == "screenshot":
        name = re.sub(r"[^\w.-]+", "_", str(arg))
        page.screenshot(path=str(ctx["shots_dir"] / f"extra-{name}.png"), full_page=bool(step.get("full_page")))
        return f"screenshot {name}"
    if action == "note":
        page.wait_for_timeout(int(step.get("duration_ms", 1800)))
        return f"note: {arg}"
    raise SpecError(f"未知动作 {action}")


def default_label(action, arg) -> str:
    if action == "note":
        return str(arg)
    if isinstance(arg, dict):
        arg = arg.get("selector") or arg.get("key") or arg.get("to") or ""
    return f"{action} {str(arg)[:60]}".strip()


# ------------------------------------------------------------ 页面内叠加: 字幕 + 光标/点击高亮
CAPTION_JS = """
(a) => {
  let el = document.getElementById('__rv_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__rv_caption';
    el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:8px 14px;' +
      'font:600 15px/1.3 system-ui,sans-serif;color:#fff;pointer-events:none;';
    (document.documentElement || document.body).appendChild(el);
  }
  el.style.background = a.kind === 'note' ? 'rgba(20,70,160,.93)' : a.kind === 'error' ? 'rgba(200,30,30,.93)' : 'rgba(30,30,30,.88)';
  el.style.fontSize = a.kind === 'note' ? '18px' : '15px';
  el.textContent = a.text;
}
"""

CURSOR_INIT_JS = """
(() => {
  const add = () => {
    if (document.getElementById('__rv_cursor')) return;
    const dot = document.createElement('div');
    dot.id = '__rv_cursor';
    dot.style.cssText = 'position:fixed;left:-30px;top:-30px;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;' +
      'background:rgba(255,60,60,.55);border:2px solid #fff;box-shadow:0 0 4px #000;z-index:2147483646;pointer-events:none;';
    (document.documentElement || document.body).appendChild(dot);
    addEventListener('mousemove', e => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;left:' + e.clientX + 'px;top:' + e.clientY + 'px;width:10px;height:10px;margin:-5px 0 0 -5px;' +
        'border-radius:50%;border:3px solid #f33;z-index:2147483646;pointer-events:none;transition:all .5s ease-out;opacity:1;';
      (document.documentElement || document.body).appendChild(r);
      requestAnimationFrame(() => { r.style.width = '56px'; r.style.height = '56px'; r.style.margin = '-28px 0 0 -28px'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


def set_caption(page, text, kind="step"):
    try:
        page.evaluate(CAPTION_JS, {"text": text, "kind": kind})
    except Exception:
        pass  # 页面正在跳转时忽略


def fmt_t(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


def ffmpeg_convert(webm: Path, out: Path, want_mp4: bool, want_gif: bool) -> dict:
    res = {}
    if not (want_mp4 or want_gif):
        return res
    if not shutil.which("ffmpeg"):
        print("[warn] 没找到 ffmpeg，跳过 mp4/gif 转换", file=sys.stderr)
        return res
    if want_mp4:
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(out / "video.mp4")])
        if r.returncode == 0:
            res["mp4"] = "video.mp4"
    if want_gif:
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf",
                            "fps=8,scale=800:-1:flags=lanczos", str(out / "video.gif")])
        if r.returncode == 0:
            res["gif"] = "video.gif"
    return res


def write_timeline(out: Path, name: str, meta: dict, steps: list, files: dict):
    (out / "steps.json").write_text(json.dumps({"name": name, **meta, "files": files, "steps": steps},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    L = [f"# Session recording: {name}", "",
         f"- Result: {'completed' if meta['completed'] else 'STOPPED on error (见下方 ERROR 行)'} "
         f"({meta['done']} / {meta['total']} steps executed)",
         f"- Started: {meta['started_at']} · Duration: {meta['duration_s']}s",
         f"- Base URL: {meta['base_url'] or '(none)'}",
         "- 这是一份「做了什么」的记录，**不是**正确性验证；视频时间戳误差约 ±1 秒。", ""]
    L += ["## Files", ""] + [f"- {k}: `{v}`" for k, v in files.items()] + [""]
    if meta["blocked_requests"]:
        L += ["## Blocked requests (allowed_hosts)", ""] + [f"- {u}" for u in meta["blocked_requests"]] + [""]
    L += ["## Timeline", "", "| # | Video time | Step | Detail | Result | Screenshot |", "|---|---|---|---|---|---|"]
    for s in steps:
        res = s["error"].replace("|", "\\|").replace("\n", " ") if s["error"] else s["status"]
        shot = f"[img]({s['screenshot']})" if s.get("screenshot") else ""
        L.append(f"| {s['index']} | {s['video_time']} | {s['label']} | {s['detail'].replace('|', '\\|')} | {res} | {shot} |")
    (out / "steps.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="video-evidence: 带字幕的录屏 + 时间线 (无断言)")
    ap.add_argument("spec")
    ap.add_argument("--out", default="recording", help="输出目录 (默认 ./recording，每次运行会清空重建)")
    ap.add_argument("--base-url")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--slow-mo", type=int, default=0, metavar="MS", help="每个浏览器动作之间放慢 MS 毫秒 (演示用，如 300)")
    ap.add_argument("--hold-ms", type=int, default=700, help="每步结束后字幕停留时间，方便观众读 (默认 700)")
    ap.add_argument("--mp4", action="store_true", help="ffmpeg 转 video.mp4")
    ap.add_argument("--gif", action="store_true", help="ffmpeg 生成 video.gif")
    ap.add_argument("--no-cursor", action="store_true", help="不显示光标/点击高亮")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2
    try:
        spec = load_spec(Path(args.spec))
        parsed = [split_step(s, i + 1) for i, s in enumerate(spec["steps"])]
    except (SpecError, json.JSONDecodeError, OSError) as e:
        print(f"[spec error] {e}", file=sys.stderr)
        return 2

    base_url = (args.base_url or spec.get("base_url") or "").rstrip("/")
    viewport = spec.get("viewport", {"width": 1280, "height": 720})
    allowed_hosts = spec.get("allowed_hosts") or []
    name = spec.get("name", Path(args.spec).stem)
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    shots_dir, raw = out / "screenshots", out / "_raw"
    shots_dir.mkdir(parents=True); raw.mkdir()
    ctx_info = {"base_url": base_url, "timeout_ms": int(spec.get("timeout_ms", 8000)), "shots_dir": shots_dir}
    blocked: list[str] = []
    steps_out: list[dict] = []
    completed = True
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t_wall = time.time()

    with sync_playwright() as p:
        browser = getattr(p, args.browser).launch(headless=not args.headed, slow_mo=args.slow_mo)
        context = browser.new_context(viewport=viewport, record_video_dir=str(raw), record_video_size=viewport,
                                      ignore_https_errors=bool(spec.get("ignore_https_errors")))
        if not args.no_cursor:
            context.add_init_script(CURSOR_INIT_JS)
        if allowed_hosts:
            def guard(route):
                url = route.request.url
                host = urlparse(url).hostname or ""
                if url.startswith(("data:", "blob:", "about:")) or host in allowed_hosts:
                    route.continue_()
                else:
                    blocked.append(url[:200])
                    route.abort("blockedbyclient")
            context.route("**/*", guard)
        page = context.new_page()
        t0 = time.time()  # 视频从这里开始计时 (近似)
        page.wait_for_timeout(400)

        total = len(parsed)
        for i, (action, arg, raw_step) in enumerate(parsed, 1):
            label = raw_step.get("name") or default_label(action, arg)
            rec = {"index": i, "action": action, "label": label, "video_time": fmt_t(time.time() - t0),
                   "status": "done", "error": None, "screenshot": None, "detail": ""}
            kind = "note" if action == "note" else "step"
            set_caption(page, f"Step {i}/{total}: {label}" if kind == "step" else f"📝 {label}", kind)
            try:
                rec["detail"] = run_action(page, action, arg, raw_step, ctx_info)
            except SpecError as e:
                rec["status"], rec["error"] = "ERROR", f"spec error: {e}"
            except Exception as e:
                rec["status"], rec["error"] = "ERROR", f"{type(e).__name__}: {first_line(e)}"
            if rec["status"] == "ERROR":
                set_caption(page, f"Step {i}/{total} ERROR: {rec['error'][:110]}", "error")
            else:
                page.wait_for_timeout(args.hold_ms)
            shot = shots_dir / f"{i:02d}-{rec['status'].lower()}.png"
            try:
                page.screenshot(path=str(shot))
                rec["screenshot"] = f"screenshots/{shot.name}"
            except Exception:
                pass
            steps_out.append(rec)
            if rec["status"] == "ERROR":
                print(f"  ✗ step {i} {label}: {rec['error']}")
                page.wait_for_timeout(1200)  # 让错误字幕留在视频里
                completed = False
                break
            print(f"  ✓ step {i} {label}")
        page.wait_for_timeout(500)
        video = page.video
        context.close()  # 关闭后视频才落盘
        vpath = Path(video.path()) if video else None
        browser.close()

    files = {}
    if vpath and vpath.exists():
        shutil.move(str(vpath), out / "video.webm")
        files["video"] = "video.webm"
    shutil.rmtree(raw, ignore_errors=True)
    files.update(ffmpeg_convert(out / "video.webm", out, args.mp4, args.gif))
    files["screenshots"] = "screenshots/"
    meta = {"completed": completed, "done": len(steps_out) - (0 if completed else 1), "total": len(parsed),
            "started_at": started, "duration_s": round(time.time() - t_wall, 1), "base_url": base_url,
            "blocked_requests": blocked}
    write_timeline(out, name, meta, steps_out, files)
    print(f"\n{'COMPLETED' if completed else 'STOPPED ON ERROR'}  {meta['done']}/{meta['total']} steps  → {out}")
    return 0 if completed else 1


if __name__ == "__main__":
    sys.exit(main())
