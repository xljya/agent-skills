import argparse
import ctypes
import hashlib
import io
import json
import re
import sqlite3
import wave
from collections import Counter, defaultdict
from pathlib import Path


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def extension(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:6] in (b"GIF89a", b"GIF87a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b.startswith((b"\x02#!SILK", b"#!SILK")):
        return "silk"
    if b[4:8] == b"ftyp":
        return "mp4"
    if b[:3] == b"ID3" or b[:2] == b"\xff\xfb":
        return "mp3"
    return "bin"


def make_wav(raw):
    import pysilk

    pcm = io.BytesIO()
    with raw.open("rb") as f:
        pysilk.decode(f, pcm, 24000)
    if not pcm.tell():
        raise ValueError("Empty SILK audio")
    dest = raw.with_suffix(".wav")
    with wave.open(str(dest), "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm.getvalue())
    return dest


def extract(args):
    # Unqualified filenames in filecontext are resolved only inside the selected backup.
    external = defaultdict(list)
    for p in args.source.rglob("*"):
        if p.is_file():
            external[p.name.casefold()].append(p)
    shards = {}
    for p in args.catalog.parent.glob("*.sqlite"):
        db = readonly(p)
        if db.execute("select 1 from sqlite_master where name='resfile'").fetchone():
            for (rid,) in db.execute("select resId from resfile"):
                if rid in shards:
                    raise ValueError("Ambiguous resource shard; isolate one backup set")
                shards[rid] = db
        else:
            db.close()
    lib = ctypes.CDLL(str(args.cipher.resolve()))
    lib.block.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    lib.block.restype = None
    media = args.out / "媒体"
    media.mkdir(parents=True, exist_ok=False)
    records, report = {}, Counter()
    db = readonly(args.catalog)
    for rid, md5, size, name, key, ref in db.execute(
        "select resId,md5,filesize,filename,filekey,dbfileResid from filecontext"
    ):
        if ref and ref in shards:
            data = (
                shards[ref]
                .execute("select filedata from resfile where resId=?", (ref,))
                .fetchone()[0]
            )
        elif not ref and len(external.get(str(name).casefold(), [])) == 1:
            data = bytearray(external[name.casefold()][0].read_bytes())
            width = 524288
            if (
                len(data) != size
                or len(data) < 2 * width
                or not isinstance(key, bytes)
                or len(key) != 16
            ):
                report["unsupported external layout"] += 1
                continue
            for offset in [0, size - width]:
                block = (ctypes.c_char * width).from_buffer(data, offset)
                lib.block(block, width // 4, key)
        else:
            report["unresolved resource"] += 1
            continue
        if len(data) != size:
            report["size mismatch"] += 1
            continue
        if (
            re.fullmatch("[0-9a-fA-F]{32}", str(md5))
            and hashlib.md5(data).hexdigest() != md5.lower()
        ):
            if not ref:
                report["external MD5 mismatch; withheld from viewer"] += 1
                if args.review:
                    args.review.mkdir(parents=True, exist_ok=True)
                    candidate = args.review / (
                        hashlib.sha256(data).hexdigest() + "." + extension(data)
                    )
                    if not candidate.exists():
                        candidate.write_bytes(data)
                continue
            # Embedded variants can carry the original image's MD5. Preserve the
            # exact blob under its own SHA-256 and retain its resource-table link.
            report["embedded representation differs from metadata MD5"] += 1
        raw = media / (hashlib.sha256(data).hexdigest() + "." + extension(data))
        if not raw.exists():
            raw.write_bytes(data)
        dest = raw
        if raw.suffix == ".silk":
            try:
                dest = raw.with_suffix(".wav")
                if not dest.exists():
                    make_wav(raw)
            except (RuntimeError, ValueError, OSError):
                report["SILK decode failed"] += 1
                continue
        records[str(rid)] = [dest.name, size]
    args.map.write_text(json.dumps(records), encoding="utf-8")
    print("Mapped resources:", len(records), dict(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ["catalog", "source", "out", "map", "cipher"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument(
        "--review",
        type=Path,
        help="Private directory for unverified external candidates",
    )
    extract(p.parse_args())
