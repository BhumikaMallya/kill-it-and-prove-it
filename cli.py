"""Command-line interface for the Phase 1 key-value engine."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from kvdb import KVDatabase


def b64decode(text: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("expected a valid base64 string") from exc


def b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def parse_batch(text: str):
    try:
        raw_ops = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("batch must be a JSON array") from exc
    if not isinstance(raw_ops, list):
        raise ValueError("batch must be a JSON array")
    operations = []
    for item in raw_ops:
        if not isinstance(item, list) or len(item) not in (2, 3):
            raise ValueError("each batch item must be [put, key, value] or [delete, key]")
        kind = item[0]
        key = b64decode(item[1])
        if kind == "put" and len(item) == 3:
            operations.append(("put", key, b64decode(item[2])))
        elif kind == "delete" and len(item) == 2:
            operations.append(("delete", key, None))
        else:
            raise ValueError("invalid batch item")
    return operations


def run_one(args: argparse.Namespace) -> int:
    max_bytes = getattr(args, "max_bytes", None)
    if args.command == "open":
        db = KVDatabase(args.path, max_bytes=max_bytes).open()
        db.close()
        print(json.dumps({"ok": True, "path": str(args.path)}))
        return 0

    if args.command == "check":
        db = KVDatabase(args.path, max_bytes=max_bytes).open()
        db.close()
        print(json.dumps({"ok": True, "path": str(args.path)}))
        return 0

    db = KVDatabase(args.path, max_bytes=max_bytes).open()
    try:
        if args.command == "put":
            db.put(b64decode(args.key), b64decode(args.value))
            print(json.dumps({"ok": True}))
        elif args.command == "get":
            value = db.get(b64decode(args.key))
            print(json.dumps({"ok": True, "found": value is not None,
                              "value": None if value is None else b64encode(value)}))
        elif args.command == "del":
            db.delete(b64decode(args.key))
            print(json.dumps({"ok": True}))
        elif args.command == "batch":
            db.batch(parse_batch(args.operations))
            print(json.dumps({"ok": True}))
        elif args.command == "dump":
            for key, value in sorted(db._index.items()):
                print(json.dumps({"key": b64encode(key), "value": b64encode(value)}))
        elif args.command == "compact":
            db.compact()
            print(json.dumps({"ok": True}))
        else:
            raise ValueError(f"unknown command: {args.command}")
    finally:
        db.close()
    return 0


def serve(path: Path, max_bytes: int | None = None) -> int:
    db = KVDatabase(path, max_bytes=max_bytes).open()
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request: Any = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                operation = request.get("op")
                if operation == "put":
                    db.put(b64decode(request["key"]), b64decode(request["value"]))
                    response = {"ok": True}
                elif operation in ("delete", "del"):
                    db.delete(b64decode(request["key"]))
                    response = {"ok": True}
                elif operation == "get":
                    value = db.get(b64decode(request["key"]))
                    response = {"ok": True, "found": value is not None,
                                "value": None if value is None else b64encode(value)}
                elif operation == "batch":
                    ops = []
                    for item in request["ops"]:
                        kind = item["op"]
                        key = b64decode(item["key"])
                        if kind == "put":
                            ops.append(("put", key, b64decode(item["value"])))
                        elif kind in ("delete", "del"):
                            ops.append(("delete", key, None))
                        else:
                            raise ValueError("invalid batch operation")
                    db.batch(ops)
                    response = {"ok": True}
                elif operation == "check":
                    response = {"ok": True}
                elif operation == "compact":
                    db.compact()
                    response = {"ok": True}
                else:
                    raise ValueError("operation must be put, get, delete, batch, check, or compact")
            except Exception as exc:
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(response), flush=True)
    finally:
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kill It and Prove It key-value database")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("open", help="open, recover, and close a database")
    p.add_argument("path", type=Path)
    p = sub.add_parser("check", help="recover the database and report whether it opens")
    p.add_argument("path", type=Path)

    p = sub.add_parser("put", help="store base64 key and value")
    p.add_argument("path", type=Path)
    p.add_argument("key", help="base64 key")
    p.add_argument("value", help="base64 value")
    p = sub.add_parser("get", help="read a base64 key")
    p.add_argument("path", type=Path)
    p.add_argument("key", help="base64 key")
    p = sub.add_parser("del", help="delete a base64 key")
    p.add_argument("path", type=Path)
    p.add_argument("key", help="base64 key")
    p = sub.add_parser("batch", help="apply a JSON batch using base64 fields")
    p.add_argument("path", type=Path)
    p.add_argument("operations", help="JSON array, e.g. [[\"put\",\"aw==\",\"MQ==\"]]")
    p = sub.add_parser("dump", help="print all records as JSON lines")
    p.add_argument("path", type=Path)
    p = sub.add_parser("compact", help="rewrite live records and shrink the data file")
    p.add_argument("path", type=Path)
    p = sub.add_parser("serve", help="serve JSON-lines requests on stdin")
    p.add_argument("path", type=Path)
    for command_parser in sub.choices.values():
        command_parser.add_argument("--max-bytes", type=int,
                                    help="reject writes that would exceed this file size")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return serve(args.path, max_bytes=args.max_bytes)
        return run_one(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
