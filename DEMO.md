# Final Offline Demo Script

This is a truthful 15-minute demonstration plan. Run it from the repository root with Wi-Fi disconnected.

## Before the judge arrives

Use a clean terminal and verify:

```bash
python3 -m unittest -v
python3 -m py_compile kvdb.py cli.py torture.py test_kvdb.py
```

The repository contains no third-party database or storage library. The implementation imports only Python standard-library modules.

## Suggested 15-minute flow

### 0:00–1:30 — State the invariant

Say:

> “My database has one authoritative append-only file. A successful write is not acknowledged until the file is flushed and fsync has returned. A batch is invisible during recovery until its commit marker and checksum validate. If a process dies before acknowledgment, the operation may be absent or present, but it cannot be partially visible.”

Point to `kvdb.py`: `put`, `delete`, `batch`, `_durable_append`, and `_recover`.

### 1:30–3:00 — Show the CLI

```bash
python3 cli.py open judge-demo.kdb
python3 cli.py put judge-demo.kdb Y2FjaGU= ZHVyYWJsZQ==
python3 cli.py get judge-demo.kdb Y2FjaGU=
```

Explain that the CLI uses base64 so keys and values are arbitrary byte strings. The output should show the value `ZHVyYWJsZQ==`.

### 3:00–4:30 — Show atomic batch ordering

```bash
python3 cli.py batch judge-demo.kdb '[["put","eA==","b25l"],["put","eQ==","dHdv"],["delete","eA=="]]'
python3 cli.py get judge-demo.kdb eA==
python3 cli.py get judge-demo.kdb eQ==
```

Explain that batch operations are applied in listed order, so `x` is absent and `y` is `two`. The batch is written as operation frames followed by one commit frame.

### 4:30–6:00 — Show recovery from an incomplete tail

The unit test demonstrates this without relying on the database's own dump as expected truth:

```bash
python3 -m unittest test_kvdb.KVDatabaseTests.test_incomplete_tail_is_ignored_and_truncated -v
```

Explain that recovery stops at the last complete valid frame, truncates the invalid tail, and reopens for append.

### 6:00–9:00 — Run the independent kill test

```bash
python3 torture.py run --iterations 100 --seed 424242
```

The verified run produced 100 iterations, 36 killed child processes, 64 acknowledged operations, and 160/160 successful threaded writes. Explain that the parent owns the oracle and that an unacknowledged batch must recover to exactly the complete before or complete after state.

Do not call this 500-kill coverage; the current verified run is 100 iterations.

### 9:00–10:30 — Show compaction and size-limit behavior

```bash
python3 cli.py compact judge-demo.kdb
python3 cli.py put judge-demo.kdb Yg== dHdv --max-bytes 40
```

The second command should return a `DiskFullError` JSON error after the cap is reached. Explain that the size check occurs before appending, so the previous acknowledged data remains readable.

### 10:30–12:00 — Explain the architecture

Show the Mermaid flow in `ARCHITECTURE.md` and explain:

1. Frame and CRC validation.
2. Staging of batch records by transaction id.
3. Commit count and digest validation.
4. Sync-before-index-update and sync-before-ACK.
5. Temp-file sync followed by atomic replacement during compaction.

### 12:00–15:00 — Answer honestly

State the measured scale result:

> “I wrote and recovered 1,000,000 keys successfully. On this environment the 48,003,800-byte log reopened in 4.574 seconds, so I did not meet the stated two-second recovery target. I have not claimed that requirement as verified.”

This is stronger than presenting an unmeasured claim: the correctness result is real, and the optimization gap is identified.

## Likely judge questions

### Why append-only instead of a B-tree?

The append-only log makes crash boundaries visible and keeps the implementation small enough to reason about. The in-memory index gives direct reads. Compaction bounds growth. A production version would need a checkpoint or indexed pages for faster recovery.

### Why is a successful put durable?

`_durable_append()` writes the complete frame, flushes the file object, calls `os.fsync()`, and only then does `put()` update the index and return. The caller never receives success before the durability call returns.

### How do you prevent a partial batch?

Recovery stores batch records in a pending structure. It applies them only when it sees a valid commit record with the expected operation count and CRC32 over the exact operation frames. The in-memory index is updated only after the complete durable append.

### What happens if the commit marker is torn?

The frame length or CRC check fails, so recovery stops at the previous valid boundary. The staged operations are never applied.

### Can a reader see a half-applied batch?

No in this implementation. `get()` and `batch()` use the same global `RLock`, and the index update occurs while the lock is held. A reader sees the state before or after the batch.

### What happens during compaction if the process dies?

Before replacement, the old authoritative file remains at the database path. The replacement is written and fsynced first. `os.replace()` then swaps in the complete file. A leftover temporary file is ignored and removed on the next open.

### Did you test every required crash point?

No. The randomized torture test and unit tests cover important related cases, but exact fsync, recovery, and rename failpoints are marked partial or unverified in `ARCHITECTURE.md`. I would add deterministic failpoints next.

### Did you meet the one-million-key recovery target?

The database recovered all one million keys correctly. A bounded memory-mapped recovery optimization reduced the measured time from 4.574 seconds to 3.027 seconds on the same workload, but that is still above the required two seconds. I would add a durable index checkpoint or optimized snapshot format next; I will not claim the target is met.

### Is the database safe for two independent processes?

The tested guarantee is for concurrent threads inside one `KVDatabase` instance, protected by one global lock. The current implementation does not provide a cross-process lock for multiple independent openers of the same file.
