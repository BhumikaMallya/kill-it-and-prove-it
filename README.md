# Kill It and Prove It — Phase 4

This repository contains a small Python 3 command-line key-value database. It uses only the Python standard library. The authoritative database state is stored in one append-only file.

## Run commands

Linux/macOS:

```bash
python3 cli.py open data.kdb
python3 cli.py put data.kdb YQ== b25l
python3 cli.py get data.kdb YQ==
python3 cli.py del data.kdb YQ==
python3 cli.py batch data.kdb '[["put","YQ==","b25l"],["delete","Yg=="]]'
python3 cli.py dump data.kdb
python3 cli.py check data.kdb
python3 cli.py compact data.kdb
```

Windows PowerShell:

```powershell
py -3 cli.py open data.kdb
py -3 cli.py put data.kdb YQ== b25l
py -3 cli.py get data.kdb YQ==
py -3 cli.py del data.kdb YQ==
py -3 cli.py batch data.kdb '[["put","YQ==","b25l"],["delete","Yg=="]]'
py -3 cli.py dump data.kdb
py -3 cli.py check data.kdb
py -3 cli.py compact data.kdb
```

Windows Command Prompt uses the same commands, with the batch JSON surrounded by double quotes and its inner quotes escaped:

```bat
py -3 cli.py open data.kdb
py -3 cli.py put data.kdb YQ== b25l
py -3 cli.py get data.kdb YQ==
py -3 cli.py del data.kdb YQ==
py -3 cli.py batch data.kdb "[[\"put\",\"YQ==\",\"b25l\"],[\"delete\",\"Yg==\"]]"
py -3 cli.py dump data.kdb
py -3 cli.py check data.kdb
py -3 cli.py compact data.kdb
```

Keys and values are base64 on the command line so every byte string is representable. For example, `YQ==` is the byte string `a`, and `b25l` is `one`. A successful write prints `{"ok": true}` only after the database has flushed and called `fsync()`.

## Serve mode

`serve` accepts one JSON request per line on standard input and writes one JSON response per line on standard output. Keys and values remain base64 strings.

Linux/macOS:

```bash
python3 cli.py serve data.kdb
```

Windows:

```powershell
py -3 cli.py serve data.kdb
```

Example request lines:

```json
{"op":"put","key":"YQ==","value":"b25l"}
{"op":"get","key":"YQ=="}
{"op":"batch","ops":[{"op":"put","key":"Yg==","value":"dHdv"},{"op":"delete","key":"YQ=="}]}
{"op":"compact"}
{"op":"get","key":"YQ=="}
```

Each mutating response is emitted only after the operation's durable database call returns. A successful get returns `found` and, when present, a base64 `value`.

## Independent crash torture test

Run the deterministic POSIX crash test and threaded concurrency test:

```bash
python3 torture.py run --iterations 100 --seed 424242
```

The parent process maintains an independent dictionary oracle. It sends operations to a separate child process, counts an operation as acknowledged only after receiving the child response, and randomly kills the child with `SIGKILL` while operations are in flight. After each kill it restarts the child and queries only the selected test keys. An unacknowledged single operation is accepted only if the recovered state equals the state before or after that operation. An unacknowledged batch is checked as one complete before/after state, so a partial batch fails the test. The tester never uses `dump` or the database's own state as its expected truth.

The harness also runs four Python threads performing 160 total puts through one `KVDatabase` instance and verifies all 160 keys. The current tester uses POSIX `select` and `Popen.kill()`/`SIGKILL`; on Windows it reports that crash-kill behavior is not verified rather than claiming equivalent coverage.

## Compaction and file-size limit

Compaction writes a complete replacement file, flushes and syncs it, then atomically replaces the old data file. A leftover `data.kdb.compact.tmp` file is ignored and removed on the next open. Run it with:

```bash
python3 cli.py compact data.kdb
python3 cli.py compact data.kdb --max-bytes 50000000
```

The `--max-bytes` limit is a logical maximum for the authoritative file. A write or batch is rejected before appending if its complete encoded records would exceed the limit. The Python API equivalent is:

```python
from kvdb import KVDatabase

db = KVDatabase("data.kdb", max_bytes=50_000_000).open()
```

A rejected write raises `DiskFullError`; the previously acknowledged state remains readable. Serve mode also accepts `{"op":"compact"}` and supports `--max-bytes`.

## Tests

```bash
python3 -m unittest -v
python3 -m py_compile kvdb.py cli.py torture.py test_kvdb.py
```

## Recovery performance checkpoint

The authoritative state remains the append-only `data.kdb` file. On a clean `close()`, the engine also writes an advisory `data.kdb.index` checkpoint containing the in-memory index plus database metadata. It is flushed, fsynced, and atomically renamed. On the next open, it is used only when its metadata and entry framing validate; otherwise the original framed log scanner performs full recovery. A missing, stale, truncated, or interrupted checkpoint cannot change correctness or hide a durable append. The sidecar is a performance cache, not a second source of truth.

On the measured one-million-key workload (48,892,690-byte log), clean reopen measured 1.252, 0.916, and 0.869 seconds across three runs (1.012-second mean), with all 1,000,000 keys present. Removing the sidecar forced the compatibility fallback, which recovered all keys in 2.919 seconds. Reproduce it with:

```bash
python3 benchmark_recovery.py --runs 3
```

The storage engine is implemented in `kvdb.py`. The CLI and torture harness are intentionally separate from the storage implementation.
