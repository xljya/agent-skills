#!/usr/bin/env bash
# assert_terminal.sh: 验证 CLI/终端程序: 逐条执行命令、断言输出、留下日志和报告 (不录屏)。
#
# 用法:   assert_terminal.sh <输出目录> <断言文件>
# 断言文件每行一条:   <命令> || <期望输出里包含的字符串>      ('#' 开头为注释)
#   例:   echo hello || hello
# 产物:   session.log (完整输出)  report.md (逐条 PASS/FAIL)
# 退出码: 0 全部通过, 1 有失败。命令会被真实执行，别写密钥，别对生产环境跑写操作。
set -u
OUT="${1:?usage: assert_terminal.sh <out_dir> <assertions_file>}"
SPEC="$(cd "$(dirname "${2:?usage: assert_terminal.sh <out_dir> <assertions_file>}")" && pwd)/$(basename "$2")"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
LOG="$OUT/session.log"; REPORT="$OUT/report.md"; FAILFILE="$OUT/.failed"
rm -f "$FAILFILE"; : > "$LOG"
{ echo "# Terminal verification report"; echo; echo "| # | Status | Command | Expect |"; echo "|---|---|---|---|"; } > "$REPORT"

run_all() {
  local n=0 line cmd expect outp code st
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue;; esac
    cmd="${line%%||*}"; expect="${line#*||}"
    cmd="$(echo "$cmd" | sed 's/[[:space:]]*$//')"
    expect="$(echo "$expect" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    n=$((n+1))
    echo "\$ $cmd"
    outp="$(bash -c "$cmd" 2>&1)"; code=$?
    echo "$outp"
    if [ $code -eq 0 ] && printf '%s' "$outp" | grep -qF -- "$expect"; then st="✅ PASS"
    else st="❌ FAIL (exit=$code)"; touch "$FAILFILE"; fi
    echo "| $n | $st | \`$cmd\` | \`$expect\` |" >> "$REPORT"
    echo "[$st] $cmd"
  done < "$SPEC"
}
run_all 2>&1 | tee -a "$LOG"
if [ -e "$FAILFILE" ]; then rm -f "$FAILFILE"; echo "SOME FAILED  (report: $REPORT)"; exit 1; fi
echo "ALL PASS  (report: $REPORT)"
