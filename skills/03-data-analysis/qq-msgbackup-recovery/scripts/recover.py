"""Recover MSG0 copies. Run from a private directory outside the skills repository."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path

WRAPPER = "0d8b94448f4dafe7337b88d6a568b004224c37fcbe2bd1142c1af7624fbd534c"
DLL = "b39f79c6cf43a5665dabb587f31784c713fbfda55ef0ebdd4a51ac1d0a0ec4e9"
SCRIPTS = Path(__file__).resolve().parent


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_databases(source, target):
    found = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(36)
        if header.startswith(b"SQLite header 3\0") and header[32:36] == b"MSG0":
            found.append(path)
    if not found or len({p.name.casefold() for p in found}) != len(found):
        raise ValueError("Select one backup set containing uniquely named MSG0 files")
    target.mkdir(parents=True, exist_ok=False)
    for path in found:
        copied = target / path.name
        shutil.copyfile(path, copied)
        if digest(path) != digest(copied):
            raise IOError("Copy verification failed")
    print("MSG0 copies:", len(found))


def run_native(args, mode, path, key):
    return subprocess.run(
        [str(args.helper), mode, str(args.dll), str(path)], input=key, timeout=600
    ).returncode


def capture(args, copies):
    import frida

    if digest(args.wrapper) != WRAPPER:
        raise ValueError("Unsupported wrapper.node build")
    done = threading.Event()
    verified = set()
    errors = []

    def receive(message, data):
        try:
            if message["type"] == "error":
                raise RuntimeError(message.get("description", "Frida error"))
            if message.get("payload") != "backup-response" or not data:
                return
            if len(data) == 32:
                try:
                    key = bytes.fromhex(data.decode("ascii"))
                except ValueError:
                    return
            else:
                key = data
            if len(key) != 16:
                return
            for p in copies:
                if p in verified:
                    continue
                rc = run_native(args, "check", p, key)
                if rc == 0:
                    dest = args.work / "keys" / (p.name + ".verified-key")
                    if dest.exists():
                        if dest.read_bytes() != key:
                            raise ValueError("Conflicting verified key")
                    else:
                        with dest.open("xb") as f:
                            f.write(key)
                    verified.add(p)
                elif rc != 26:  # SQLite NOTADB normally indicates a different key.
                    print("Candidate rejected, helper status", rc, flush=True)
            print("Matched", len(verified), "/", len(copies), flush=True)
            if len(verified) == len(copies):
                done.set()
        except Exception as err:
            errors.append(str(err))
            done.set()

    (args.work / "keys").mkdir(exist_ok=True)
    session = frida.attach(args.pid)
    try:
        code = (SCRIPTS / "capture.js").read_text(encoding="utf-8")
        script = session.create_script(
            "const wrapperPath="
            + json.dumps(str(args.wrapper.resolve()))
            + ";\n"
            + code
        )
        script.on("message", receive)
        script.load()
        script.exports_sync.arm()
        print("ARMED: reopen the backup details in QQ (180 seconds)", flush=True)
        done.wait(180)
    finally:
        session.detach()
    if errors or len(verified) != len(copies):
        raise SystemExit("Detached; capture incomplete. " + " ".join(errors))


def decrypt(args, copies):
    out = args.work / "plain"
    out.mkdir(exist_ok=True)
    for path in copies:
        dest = out / (path.name + ".sqlite")
        if dest.exists():
            raise FileExistsError(dest)
        key = (args.work / "keys" / (path.name + ".verified-key")).read_bytes()
        if len(key) != 16:
            raise ValueError("Unexpected key length")
        with tempfile.TemporaryDirectory(dir=out) as tmp:
            working = Path(tmp) / "rekey.db"
            shutil.copyfile(path, working)
            if run_native(args, "rekey", working, key):
                raise ValueError("Rekey failed")
            candidate = Path(tmp) / "standard.db"
            with working.open("rb") as src, candidate.open("xb") as dst:
                if src.read(16) != b"SQLite header 3\0":
                    raise ValueError("Missing extended header")
                src.seek(1024)
                if src.read(16) != b"SQLite format 3\0":
                    raise ValueError("Missing plaintext SQLite header")
                src.seek(1024)
                shutil.copyfileobj(src, dst)
            db = sqlite3.connect(candidate.as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("SQLite integrity check failed")
            finally:
                db.close()
            candidate.rename(dest)
        db = sqlite3.connect(dest.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            tables = [
                r[0]
                for r in db.execute("select name from sqlite_master where type='table'")
            ]
            print("Verified SQLite:", dest.name, ", ".join(tables))
        finally:
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    for cmd in [
        prepare,
        commands.add_parser("capture"),
        commands.add_parser("decrypt"),
    ]:
        cmd.add_argument("--work", type=Path, required=True)
        if cmd != prepare:
            cmd.add_argument("--dll", type=Path, required=True)
            cmd.add_argument("--helper", type=Path, required=True)
        if cmd.prog.endswith(" capture"):
            cmd.add_argument("--wrapper", type=Path, required=True)
            cmd.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    args.work = args.work.resolve()
    folder = args.work / "copies"
    if args.command == "prepare":
        if args.work.is_relative_to(args.source.resolve()):
            parser.error("Place the work directory outside the source")
        copy_databases(args.source.resolve(), folder)
    else:
        copies = sorted(p for p in folder.iterdir() if p.is_file())
        if not copies or digest(args.dll) != DLL:
            parser.error("Missing copies or unsupported KernelUtil.dll")
        args.helper = args.helper.resolve()
        if args.command == "capture":
            capture(args, copies)
        else:
            decrypt(args, copies)
