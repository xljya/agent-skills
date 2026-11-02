import hashlib
import json
import re
from collections import defaultdict

from media import extension, make_wav


def get_face(n):
    if not isinstance(n, int):
        return None
    dst = face_dir / f"{n}.png"
    if dst.exists():
        return n
    paths = (
        [
            global_dir / "sysface_res" / variant / f"s{n}.png"
            for variant in ("apng", "static")
        ]
        if global_dir
        else []
    )
    if default:
        paths.append(default / f"{n}.png")
    for p in paths:
        if p.is_file() and (d := p.read_bytes()).startswith(b"\x89PNG\r\n\x1a\n"):
            face_dir.mkdir(exist_ok=True)
            dst.write_bytes(d)
            return n
    return None


suffixes = {2: ("jpg", "png", "gif", "webp"), 4: ("wav", "mp3"), 5: ("mp4",)}
expected = {2: 1, 4: 3, 5: 2}


def md5file(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "md5").hexdigest()


def build_lookup(db, table, mapping):
    # Prefer the exact original bytes, then a same-MD5 representation identified by QQ.
    lookup = {}

    def put(kind, h, fn, rank):
        if (
            not re.fullmatch(r"[0-9a-f]{32}", h)
            or fn.rsplit(".", 1)[-1] not in suffixes[kind]
        ):
            return
        k = (kind, h)
        if k not in lookup or rank > lookup[k][1]:
            lookup[k] = (fn, rank)

    for seq, rnd, typ, sub, extra, rid in db.execute(
        f'select msgSeq,msgRandom,msgType,msgSubType,extraData,resinfoId from "{table}"'
    ):
        if str(rid) not in mapping or typ not in (1, 2, 3) or not extra:
            continue
        try:
            h = json.loads(extra).get("md5", "").lower()
        except (ValueError, AttributeError):
            continue
        fn, size = mapping[str(rid)]
        put({1: 2, 2: 5, 3: 4}[typ], h, fn, (1, sub in (1, 4, 15), size))
    for p in directory.iterdir():
        ext = p.suffix[1:]
        if ext == "wav":
            continue
        kind = (
            2
            if ext in suffixes[2]
            else 4
            if ext in ("silk", "mp3")
            else 5
            if ext == "mp4"
            else None
        )
        if kind:
            fn = p.with_suffix(".wav").name if ext == "silk" else p.name
            if (directory / fn).is_file():
                put(kind, md5file(p), fn, (2, True, p.stat().st_size))
    return lookup


def configure(args):
    global directory, global_dir, default, face_dir, face_names
    directory = args.out / "媒体"
    global_dir, default, face_dir = (
        args.faces,
        args.default_faces,
        args.out / "系统表情",
    )
    face_names = {}
    if global_dir and (global_dir / "face_config.json").is_file():
        cfg = json.loads(
            (global_dir / "face_config.json").read_text(encoding="utf-8-sig")
        )
        face_names = {
            str(e["QSid"]): e.get("QDes", "").lstrip("/") for e in cfg["sysface"]
        }
    if args.cache:
        for dirname in ["Ptt", "Pic", "Video", "Emoji"]:
            for f in (args.cache / dirname).rglob("*"):
                if f.is_file():
                    for h in re.findall("[a-fA-F0-9]{32}", f.name):
                        cache[h.lower()].append(f)


lookup = {}
cache = defaultdict(list)
checked = {}
cache_hits = set()


def choose_asset(kind, raw):
    if not isinstance(raw, bytes) or len(raw) != 16:
        return None
    h = raw.hex()
    pair = (kind, h)
    if pair in checked:
        return checked[pair]
    result = lookup.get(pair)
    if not result or result[1][0] < 2:
        for p in cache.get(h, []):
            if md5file(p) != h:
                continue
            data = p.read_bytes()
            ext = extension(data)
            if not ext or ("wav" if ext == "silk" else ext) not in suffixes[kind]:
                continue
            dst = directory / (hashlib.sha256(data).hexdigest() + "." + ext)
            if not dst.exists():
                dst.write_bytes(data)
            if ext == "silk":
                dst = make_wav(dst)
            if dst:
                result = (dst.name, (2, True, len(data)))
                cache_hits.add(pair)
                break
    checked[pair] = result[0] if result else None
    return checked[pair]
