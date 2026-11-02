"""Pack and verify only viewer files referenced by the chosen private-chat HTML pages."""

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path


def package(view, dest):
    files = set()
    pages = sorted(
        p for p in view.glob("msg_3_*.html") if re.fullmatch(r"msg_3_\d+\.html", p.name)
    )
    if not pages:
        raise ValueError("No generated chat pages")
    decoder = json.JSONDecoder()
    for p in pages:
        files.add(p)
        text = p.read_text(encoding="utf-8").split("const peer=", 1)[1]
        start = text.index(", files=") + len(", files=")
        media, end = decoder.raw_decode(text, start)
        marker = ", rows="
        if not text.startswith(marker, end):
            raise ValueError("Unknown page format")
        rows, _ = decoder.raw_decode(text, end + len(marker))
        if len(rows) != len({r[0] for r in rows}):
            raise ValueError("Duplicate message ID")
        for name in media:
            if not re.fullmatch(r"[0-9a-f]{64}\.[a-z0-9]+", name):
                raise ValueError("Invalid media filename")
            files.add(view / "媒体" / name)
        for _, _, _, parts, _ in rows:
            for part in parts:
                if part[0] == "e":
                    number = part[2]
                    if not isinstance(number, int):
                        raise ValueError("Invalid face ID")
                    files.add(view / "系统表情" / f"{number}.png")
        print("Messages:", len(rows))
    if dest.exists():
        raise FileExistsError(dest)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        candidate = Path(tmp) / "portable.zip"
        with zipfile.ZipFile(candidate, "x") as archive:
            for path in sorted(files):
                method = (
                    zipfile.ZIP_DEFLATED
                    if path.suffix in {".html", ".wav"}
                    else zipfile.ZIP_STORED
                )
                archive.write(
                    path, path.relative_to(view).as_posix(), compress_type=method
                )
        with zipfile.ZipFile(candidate) as archive:
            if archive.testzip() is not None:
                raise IOError("ZIP CRC failed")
            for page in pages:
                if archive.read(page.name) != page.read_bytes():
                    raise IOError("Packed HTML differs")
        candidate.rename(dest)
    print("Verified archive entries:", len(files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", type=Path)
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    package(args.view, args.zip)
