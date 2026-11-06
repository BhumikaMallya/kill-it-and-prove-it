"""Independent crash/recovery tester for the key-value database.

The parent process owns the oracle. The child only executes requests against the
real database. A request is counted as acknowledged only after its response is
received, and an abruptly killed request is checked against both legal outcomes.
This harness uses POSIX select and SIGKILL; Windows process-kill behavior is not
claimed by this tool.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from kvdb import KVDatabase


def enc(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def dec(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def child_main(path: Path) -> int:
    db = KVDatabase(path).open()
    try:
        for line in sys.stdin:
            try:
                req = json.loads(line)
                op = req["op"]
                if op == "put":
                    db.put(dec(req["key"]), dec(req["value"]))
                    result = {"ok": True}
                elif op == "delete":
                    db.delete(dec(req["key"]))
                    result = {"ok": True}
                elif op == "batch":
                    operations = []
                    for item in req["ops"]:
                        key = dec(item["key"])
                        if item["kind"] == "put":
                            operations.append(("put", key, dec(item["value"])))
                        else:
                            operations.append(("delete", key, None))
                    db.batch(operations)
                    result = {"ok": True}
                elif op == "state":
                    result = {"ok": True, "values": {
                        key: None if (value := db.get(dec(key))) is None else enc(value)
                        for key in req["keys"]
                    }}
                elif op == "stop":
                    result = {"ok": True}
                    print(json.dumps(result), flush=True)
                    return 0
                else:
                    raise ValueError("unknown child operation")
                print(json.dumps(result), flush=True)
            except Exception as exc:
                print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    finally:
        db.close()
    return 0


def start_child(path: Path):
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "worker", str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def send_and_wait(proc, request: dict, timeout: float = 1.0):
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        return None
    line = proc.stdout.readline()
    return json.loads(line) if line else None


def stop_child(proc) -> None:
    if proc.poll() is None:
        try:
            response = send_and_wait(proc, {"op": "stop"}, timeout=1.0)
            if response is None:
                proc.kill()
        except (BrokenPipeError, OSError):
            proc.kill()
    proc.wait(timeout=2)


def state_from_child(proc, keys: set[bytes]) -> dict[bytes, bytes]:
    response = send_and_wait(proc, {"op": "state", "keys": [enc(k) for k in sorted(keys)]})
    if not response or not response.get("ok"):
        raise RuntimeError(f"state query failed: {response}")
    observed = {}
    for key_text, value_text in response["values"].items():
        if value_text is not None:
            observed[dec(key_text)] = dec(value_text)
    return observed


def apply_oracle(oracle: dict[bytes, bytes], operations) -> dict[bytes, bytes]:
    result = dict(oracle)
    for kind, key, value in operations:
        if kind == "put":
            result[key] = value
        else:
            result.pop(key, None)
    return result


def random_operation(rng: random.Random, keys: list[bytes]):
    def one():
        key = rng.choice(keys)
        if rng.random() < 0.65:
            return ("put", key, f"value-{rng.randrange(1_000_000)}".encode())
        return ("delete", key, None)

    if rng.random() < 0.35:
        return [one() for _ in range(rng.randint(2, 8))]
    return [one()]


def request_for(operations):
    if len(operations) == 1:
        kind, key, value = operations[0]
        if kind == "put":
            return {"op": "put", "key": enc(key), "value": enc(value)}
        return {"op": "delete", "key": enc(key)}
    return {"op": "batch", "ops": [
        {"kind": kind, "key": enc(key), **({"value": enc(value)} if kind == "put" else {})}
        for kind, key, value in operations
    ]}


def run_crash_test(path: Path, iterations: int, seed: int) -> dict:
    rng = random.Random(seed)
    keys = [f"key-{i}".encode() for i in range(12)]
    known_keys: set[bytes] = set()
    oracle: dict[bytes, bytes] = {}
    proc = start_child(path)
    acknowledged = 0
    killed = 0
    try:
        for step in range(iterations):
            operations = random_operation(rng, keys)
            known_keys.update(key for _, key, _ in operations)
            before = dict(oracle)
            after = apply_oracle(before, operations)
            request = request_for(operations)
            response = None
            # A short randomized delay creates genuine in-flight kill points;
            # some operations finish and are acknowledged before the kill.
            if rng.random() < 0.70:
                delay = rng.choice((0.0, 0.0001, 0.0005, 0.002))
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                time.sleep(delay)
                if proc.poll() is None:
                    ready, _, _ = select.select([proc.stdout], [], [], 0)
                    if ready:
                        response = json.loads(proc.stdout.readline())
                    else:
                        proc.kill()
                        killed += 1
            else:
                response = send_and_wait(proc, request)

            if response is not None and response.get("ok"):
                oracle = after
                acknowledged += 1
                continue

            if response is not None and not response.get("ok"):
                raise AssertionError(f"child operation failed at step {step}: {response}")

            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            observed_proc = start_child(path)
            observed = state_from_child(observed_proc, known_keys)
            if observed != before and observed != after:
                raise AssertionError(
                    f"mismatch at step {step}, seed {seed}: observed={observed!r}, "
                    f"allowed_before={before!r}, allowed_after={after!r}"
                )
            oracle = observed
            proc = observed_proc
        final = state_from_child(proc, known_keys)
        if final != oracle:
            raise AssertionError(f"final mismatch: observed={final!r}, oracle={oracle!r}")
    finally:
        stop_child(proc)
    return {"iterations": iterations, "seed": seed, "acknowledged": acknowledged,
            "killed": killed, "keys_checked": len(known_keys)}


def run_thread_test() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "threaded.kdb"
        db = KVDatabase(path).open()
        errors = []
        barrier = threading.Barrier(4)

        def writer(worker: int):
            try:
                barrier.wait()
                for index in range(40):
                    db.put(f"thread-{worker}-{index}".encode(), str(index).encode())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        count = sum(db.get(f"thread-{worker}-{index}".encode()) is not None
                    for worker in range(4) for index in range(40))
        db.close()
        if errors or count != 160:
            raise AssertionError(f"thread test failed: errors={errors}, count={count}")
        return {"threads": 4, "writes": 160, "present": count}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Independent crash torture tester")
    sub = parser.add_subparsers(dest="mode", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("path", type=Path)
    run = sub.add_parser("run")
    run.add_argument("--db", type=Path)
    run.add_argument("--iterations", type=int, default=100)
    run.add_argument("--seed", type=int, default=20261106)
    args = parser.parse_args(argv)
    if args.mode == "worker":
        return child_main(args.path)
    if os.name == "nt":
        print("SKIPPED crash test: this harness uses POSIX select/SIGKILL; Windows kill behavior is not verified.")
        return 2
    temporary = None
    if args.db is None:
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "torture.kdb"
    else:
        path = args.db
    try:
        crash = run_crash_test(path, args.iterations, args.seed)
        threads = run_thread_test()
        print(json.dumps({"ok": True, "crash_test": crash, "thread_test": threads}, sort_keys=True))
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
