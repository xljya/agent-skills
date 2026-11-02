import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import resources as rich
from media import readonly

w = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
for arg in ("catalog", "map", "out", "faces", "default-faces", "cache"):
    parser.add_argument(
        "--" + arg, type=Path, required=arg in ("catalog", "map", "out")
    )
parser.add_argument("--self", dest="owner", required=True)
parser.add_argument("--table", required=True)
args = parser.parse_args()
messages = args.table
if not re.fullmatch(r"msg_3_[0-9]+", messages):
    parser.error("Expected a private conversation table")
resources = "res" + messages[3:]
peer = messages.split("_")[-1]
own = args.owner
out = args.out
tm = timezone(timedelta(hours=8))
rich.configure(args)
con = readonly(args.catalog)
res = json.loads(args.map.read_text(encoding="utf-8"))
media = []
media_index = {}
by_seq = defaultdict(list)
by_time = defaultdict(list)


class ParseError(ValueError):
    pass


def read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            break
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ParseError("invalid varint")


for seq, rnd, kind, sub, rid, extra in con.execute(
    f'select msgSeq,msgRandom,msgType,msgSubType,resinfoId,extraData from "{resources}"'
):
    item = res.get(str(rid))
    if not item:
        continue
    file, size = item
    if file not in media_index:
        media_index[file] = len(media)
        media.append(file)
    entry = (kind, sub, media_index[file], size)
    by_seq[(seq, rnd)].append(entry)
    if extra:
        try:
            by_time[(seq, rnd, int(json.loads(extra)["msgTime"]))].append(entry)
        except (KeyError, ValueError, TypeError):
            pass
unique_pairs = {
    tuple(row)
    for row in con.execute(
        f'select msgSeq,msgRandom from "{messages}" group by msgSeq,msgRandom having count(*)=1'
    )
}
rich.lookup = rich.build_lookup(con, resources, res)
coverage = Counter()


def media_id(fn):
    if fn not in media_index:
        media_index[fn] = len(media)
        media.append(fn)
    return media_index[fn]


def unpack(data):
    fields = defaultdict(list)
    i = 0
    while i < len(data):
        tag, i = read_varint(data, i)
        n, wire = divmod(tag, 8)
        if wire == 0:
            val, i = read_varint(data, i)
        elif wire == 2:
            ln, i = read_varint(data, i)
            val = data[i : i + ln]
            i += ln
        elif wire in (1, 5):
            ln = 8 if wire == 1 else 4
            val = int.from_bytes(data[i : i + ln], "little")
            i += ln
        else:
            raise ParseError("wire type")
        if i > len(data) or n == 0:
            raise ParseError("field boundary")
        fields[n].append(val)
    return fields


def strings(fields, n):
    return [
        val.decode("utf-8", errors="replace")
        for val in fields.get(n, [])
        if isinstance(val, bytes) and val
    ]


def first(fields, n, default=None):
    return next(iter(fields.get(n, ())), default)


def quote_text(el):
    direct = strings(el, 47413)
    if direct:
        return "".join(direct)
    parts = []
    for source in el.get(47423, []):
        if not isinstance(source, bytes):
            continue
        try:
            parts += strings(unpack(source), 45101)
        except ParseError:
            pass
    return "".join(parts)


def unpack_msg(blob):
    message = unpack(blob)
    sender = str(first(unpack(first(message, 1, b"")), 1, ""))
    parts = []
    types = []
    for payload in message.get(5, []):
        for elem in unpack(payload).get(40800, []):
            el = unpack(elem)
            kind = first(el, 45002)
            types.append(kind)
            if kind == 1:
                for s in strings(el, 45101):
                    parts.append(["t", s])
            elif kind == 7:
                parts.append(["q", quote_text(el) or "引用消息"])
            elif kind == 6:
                num = first(el, 47601)
                name = (
                    "".join(strings(el, 47602))
                    or rich.face_names.get(str(num))
                    or (
                        f"QQ 表情 #{num}"
                        if num is not None
                        else "QQ 表情（备份未记录编号）"
                    )
                )
                face = rich.get_face(num)
                parts.append(["e", name, face] if face is not None else ["c", name])
                coverage["faces_shown" if face is not None else "faces_no_art"] += 1
            elif kind in (2, 3, 4, 5):
                label = {2: "图片", 3: "文件", 4: "语音", 5: "视频"}[kind]
                desc = "".join(strings(el, 45402)) if kind == 3 else ""
                fn = (
                    rich.choose_asset(kind, first(el, 45406))
                    if kind in rich.suffixes
                    else None
                )
                parts.append(
                    [
                        "m",
                        label + (" · " + desc if desc else ""),
                        kind,
                        media_id(fn) if fn else None,
                    ]
                )
            elif kind == 8:
                try:
                    items = json.loads(first(el, 48271, b"{}")).get("items", [])
                    tip = "".join(
                        i["txt"]
                        for i in items
                        if isinstance(i, dict) and isinstance(i.get("txt"), str)
                    )
                except (ValueError, AttributeError):
                    tip = ""
                parts.append(["c", tip or "系统提示（保留原始数据）"])
            elif kind == 10:
                try:
                    title = json.loads(first(el, 47901, b"{}")).get("prompt")
                except (ValueError, AttributeError):
                    title = None
                parts.append(
                    [
                        "c",
                        title
                        if isinstance(title, str) and title
                        else "应用卡片（保留原始数据）",
                    ]
                )
            elif kind == 21:
                summary = "".join(strings(el, 48157)) or "".join(strings(el, 48153))
                parts.append(["call", summary or "通话记录"])
                coverage["calls_with_detail"] += bool(summary)
            elif kind == 11:
                parts.append(["c", "".join(strings(el, 80900)) or "商城表情"])
            else:
                parts.append(
                    ["c", {21: "通话记录"}.get(kind, "特殊消息") + "（保留原始数据）"]
                )
    return sender, parts, types


rows = []
counts = Counter()
parts_count = Counter()
months = Counter()
seen_ids = set()
for rid, ts, seq, rnd, b in con.execute(
    f'select _id,msgTime,msgSeq,msgRandom,extensionData from "{messages}" order by msgTime,msgSeq,msgRandom,_id'
):
    try:
        sender, parts, kinds = unpack_msg(b)
    except (ValueError, TypeError, ParseError):
        sender = ""
        parts = []
        kinds = []
        counts["decode_error"] += 1
    if not parts:
        parts = [["c", "未解析消息（保留原始数据）"]]
        counts["no_elements"] += 1
    date = datetime.fromtimestamp(ts, tm).strftime("%Y-%m-%d %H:%M:%S")
    months[date[:7]] += 1
    attached = by_time.get((seq, rnd, ts)) or (
        by_seq.get((seq, rnd), []) if (seq, rnd) in unique_pairs else []
    )
    attached = sorted(attached, key=lambda x: (x[0] == 4, x[1] in (3, 7, 12), -x[3]))
    ids = list(dict.fromkeys(e[2] for e in attached))
    seen_ids.update(ids)
    n_by_kind = Counter(part[2] for part in parts if part[0] == "m")
    for part in parts:
        if part[0] != "m":
            continue
        kind = part[2]
        if part[3] is None and n_by_kind[kind] == 1:
            expected = rich.expected.get(kind, 5)
            exts = rich.suffixes.get(kind, ())
            match = next(
                (
                    i
                    for typ, sub, i, _ in attached
                    if typ == expected
                    and (kind == 3 or media[i].rsplit(".", 1)[-1] in exts)
                ),
                None,
            )
            part[3] = match
        if part[3] is not None:
            coverage[f"media_{kind}_shown"] += 1
        else:
            coverage[f"media_{kind}_missing"] += 1
    who = (
        1
        if sender == own
        else 2
        if sender == peer
        else 0
        if sender == "0"
        else sender or "?"
    )
    rows.append([rid, date, who, parts, ids])
    counts["with_text"] += int(any(x[0] == "t" and x[1] for x in parts))
    counts["with_media"] += bool(ids)
    parts_count.update(kinds)


def js(obj):
    return (
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


markup = (w / "viewer_rich.html").read_text(encoding="utf-8-sig")
dest = out / (messages + ".html")
if dest.exists():
    raise FileExistsError(dest)
tmp = dest.with_suffix(".new")
import wave

voice_seconds = {}
for name in media:
    if name.endswith(".wav"):
        with wave.open(str(out / "媒体" / name), "rb") as f:
            voice_seconds[name] = max(1, round(f.getnframes() / f.getframerate()))
with tmp.open("x", encoding="utf-8") as f:
    a, b = markup.split("/*ARCHIVE_DATA*/")
    f.write(a)
    f.write("const voiceSeconds=" + js(voice_seconds) + ";\n")
    f.write(
        "const peer="
        + js(peer)
        + ", own="
        + js(own)
        + ", files="
        + js(media)
        + ", rows="
        + js(rows)
        + ";\n"
    )
    f.write(b)
tmp.replace(dest)
print("coverage", dict(coverage), "cache matches", len(rich.cache_hits))
print(
    "RESULT",
    len(rows),
    rows[0][1] if rows else None,
    rows[-1][1] if rows else None,
    dict(counts),
    "months",
    len(months),
    "media targets",
    len(seen_ids),
    "media types",
    parts_count,
    "html bytes",
    dest.stat().st_size,
)
