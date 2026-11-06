"""Reproduce the one-million-key recovery benchmark.

The checkpoint is an advisory cache. Removing it measures the compatibility
full-scan fallback without changing the authoritative database file.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from kvdb import KVDatabase


def time_open(path: Path) -> float:
    started = time.perf_counter()
    db = KVDatabase(path).open()
    elapsed = time.perf_counter() - started
    if len(db._index) != 1_000_000:
        raise AssertionError(f"expected 1,000,000 keys, got {len(db._index)}")
    db.close()
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "million.kdb"
        db = KVDatabase(path).open()
        for start in range(0, 1_000_000, 10_000):
            db.batch([("put", f"key-{i}".encode(), b"value")
                      for i in range(start, start + 10_000)])
        db.close()
        checkpointed = [time_open(path) for _ in range(args.runs)]
        checkpoint = path.with_name(path.name + ".index")
        checkpoint.unlink()
        fallback = time_open(path)
        print(f"file_bytes={path.stat().st_size}")
        print("checkpointed_seconds=" + ",".join(f"{x:.6f}" for x in checkpointed))
        print(f"checkpointed_min={min(checkpointed):.6f}")
        print(f"checkpointed_mean={statistics.mean(checkpointed):.6f}")
        print(f"full_scan_fallback_seconds={fallback:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
