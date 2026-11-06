"""A small crash-safe append-only key-value database.

Phase 1 intentionally focuses on the durability and atomicity core. The public
API uses bytes for keys and values and is safe for concurrent callers through a
single re-entrant lock.
"""

from __future__ import annotations

import os
import mmap
import struct
import threading
import zlib
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


MAGIC = b"KDB1"
VERSION = 1
PUT = 1
DELETE = 2
COMMIT = 3
HEADER = struct.Struct(">4sBBQIIII")
# Magic, version, record type, transaction id, and four uint32 fields.
CRC = struct.Struct(">I")
CHECKPOINT_MAGIC = b"KIDX1"
CHECKPOINT_HEADER = struct.Struct(">5sQQQI")
CHECKPOINT_ENTRY = struct.Struct(">II")
MAX_KEY = 1024
MAX_VALUE = 1024 * 1024


class DatabaseError(Exception):
    """Base class for database errors."""


class InvalidKey(DatabaseError, ValueError):
    pass


class InvalidValue(DatabaseError, ValueError):
    pass


class DiskFullError(DatabaseError, OSError):
    """The configured logical database size limit would be exceeded."""


Operation = Tuple[str, bytes, Optional[bytes]]


class KVDatabase:
    """Single-file append-only key-value database with crash recovery."""

    def __init__(self, path: str | os.PathLike[str], max_bytes: int | None = None):
        self.path = Path(path)
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._file = None
        self._index: dict[bytes, bytes] = {}
        self._lock = threading.RLock()
        self._next_txid = 1
        self._closed = True

    def open(self, max_bytes: int | None = None) -> "KVDatabase":
        with self._lock:
            if not self._closed:
                return self
            if max_bytes is not None:
                if max_bytes <= 0:
                    raise ValueError("max_bytes must be positive")
                self.max_bytes = max_bytes
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".compact.tmp")
            if temporary.exists():
                temporary.unlink()
            self._file = open(self.path, "a+b", buffering=0)
            self._index.clear()
            if not self._load_checkpoint():
                self._recover()
            self._file.seek(0, os.SEEK_END)
            self._closed = False
            return self

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            assert self._file is not None
            self._file.flush()
            os.fsync(self._file.fileno())
            self._write_checkpoint()
            self._file.close()
            self._file = None
            self._closed = True

    def put(self, key: bytes, value: bytes) -> None:
        key = _check_key(key)
        value = _check_value(value)
        with self._lock:
            self._ensure_open()
            frame = _make_frame(PUT, 0, 0, 1, key, value)
            self._durable_append([frame])
            self._index[key] = value

    def get(self, key: bytes) -> Optional[bytes]:
        key = _check_key(key)
        with self._lock:
            self._ensure_open()
            return self._index.get(key)

    def delete(self, key: bytes) -> None:
        key = _check_key(key)
        with self._lock:
            self._ensure_open()
            frame = _make_frame(DELETE, 0, 0, 1, key, b"")
            self._durable_append([frame])
            self._index.pop(key, None)

    def batch(self, operations: Sequence[Operation]) -> None:
        if not operations:
            return
        if len(operations) > 10_000:
            raise ValueError("batch cannot contain more than 10,000 operations")
        checked: list[Operation] = []
        for operation in operations:
            if not isinstance(operation, tuple) or len(operation) != 3:
                raise ValueError("operations must be (put|delete, key, value) tuples")
            kind, key, value = operation
            key = _check_key(key)
            if kind == "put":
                value = _check_value(value)
            elif kind == "delete":
                if value is not None:
                    raise ValueError("delete value must be None")
            else:
                raise ValueError(f"unknown operation: {kind!r}")
            checked.append((kind, key, value))

        with self._lock:
            self._ensure_open()
            txid = self._next_txid
            self._next_txid += 1
            frames: list[bytes] = []
            for index, (kind, key, value) in enumerate(checked):
                record_type = PUT if kind == "put" else DELETE
                frames.append(_make_frame(record_type, txid, index, len(checked), key, value or b""))
            digest = zlib.crc32(b"".join(frames)) & 0xFFFFFFFF
            commit = _make_frame(COMMIT, txid, len(checked), len(checked), b"", CRC.pack(digest))
            self._durable_append([*frames, commit])
            for kind, key, value in checked:
                if kind == "put":
                    assert value is not None
                    self._index[key] = value
                else:
                    self._index.pop(key, None)

    def compact(self) -> None:
        """Rewrite live records and atomically replace the authoritative file."""
        with self._lock:
            self._ensure_open()
            assert self._file is not None
            temporary = self.path.with_name(self.path.name + ".compact.tmp")
            items = list(self._index.items())
            new_file = None
            replaced = False
            try:
                if temporary.exists():
                    temporary.unlink()
                new_file = open(temporary, "wb", buffering=0)
                total = 0
                for key, value in items:
                    frame = _make_frame(PUT, 0, 0, 1, key, value)
                    total += len(frame)
                    if self.max_bytes is not None and total > self.max_bytes:
                        raise DiskFullError("compacted database exceeds max_bytes")
                    if new_file.write(frame) != len(frame):
                        raise OSError("short write during compaction")
                new_file.flush()
                os.fsync(new_file.fileno())
                new_file.close()
                new_file = None
                self._file.close()
                self._file = None
                os.replace(temporary, self.path)
                replaced = True
                _fsync_directory(self.path.parent)
                self._file = open(self.path, "a+b", buffering=0)
                self._file.seek(0, os.SEEK_END)
            except Exception:
                if new_file is not None:
                    new_file.close()
                if self._file is None and self.path.exists():
                    self._file = open(self.path, "a+b", buffering=0)
                    self._file.seek(0, os.SEEK_END)
                if not replaced and temporary.exists():
                    temporary.unlink()
                raise

    def _durable_append(self, frames: Iterable[bytes]) -> None:
        assert self._file is not None
        frames = list(frames)
        current_size = self._file.seek(0, os.SEEK_END)
        projected_size = current_size + sum(len(frame) for frame in frames)
        if self.max_bytes is not None and projected_size > self.max_bytes:
            raise DiskFullError("write would exceed max_bytes")
        try:
            for frame in frames:
                written = self._file.write(frame)
                if written != len(frame):
                    raise OSError("short write")
            self._file.flush()
            os.fsync(self._file.fileno())
        except Exception:
            # A failed append may have left a complete or partial tail. Rebuild
            # the in-memory view so the current process remains readable; the
            # next open performs the same recovery independently.
            try:
                self._recover()
                self._file.seek(0, os.SEEK_END)
            except Exception:
                pass
            raise

    def _recover(self) -> None:
        assert self._file is not None
        file_size = os.fstat(self._file.fileno()).st_size
        if file_size == 0:
            self._next_txid = 1
            return
        last_good = 0
        pending: dict[int, tuple[int, list[tuple[int, bytes, bytes]], int]] = {}
        max_txid = 0
        mapped = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            offset = 0
            while offset < file_size:
                start = offset
                if file_size - offset < HEADER.size:
                    break
                try:
                    fields = HEADER.unpack_from(mapped, offset)
                except struct.error:
                    break
                magic, version, record_type, txid, key_len, value_len, op_index, op_count = fields
                if magic != MAGIC or version != VERSION or record_type not in (PUT, DELETE, COMMIT):
                    break
                if key_len > MAX_KEY or value_len > MAX_VALUE + CRC.size:
                    break
                payload_start = offset + HEADER.size
                payload_end = payload_start + key_len + value_len
                frame_end = payload_end + CRC.size
                if frame_end > file_size:
                    break
                expected_crc = CRC.unpack_from(mapped, payload_end)[0]
                if zlib.crc32(mapped[start:payload_end]) & 0xFFFFFFFF != expected_crc:
                    break

                offset = frame_end
                max_txid = max(max_txid, txid)
                if record_type in (PUT, DELETE):
                    if txid == 0:
                        if op_count != 1 or op_index != 0:
                            break
                        # Ordinary records never participate in a commit digest;
                        # avoid copying the complete frame just to discard it.
                        self._apply(record_type,
                                    bytes(mapped[payload_start:payload_start + key_len]),
                                    bytes(mapped[payload_start + key_len:payload_end]))
                    else:
                        if op_count == 0 or op_index >= op_count:
                            break
                        if txid not in pending:
                            pending[txid] = (op_count, [], 0)
                        expected, records, digest = pending[txid]
                        if expected != op_count or len(records) != op_index:
                            break
                        payload = bytes(mapped[payload_start:payload_end])
                        records.append((record_type, payload[:key_len], payload[key_len:]))
                        digest = zlib.crc32(mapped[start:frame_end], digest) & 0xFFFFFFFF
                        pending[txid] = (expected, records, digest)
                else:
                    if txid == 0 or key_len != 0 or value_len != CRC.size or op_count == 0 or op_index != op_count:
                        break
                    item = pending.get(txid)
                    if item is None:
                        break
                    expected, records, digest = item
                    if expected != op_count or len(records) != expected:
                        break
                    payload = bytes(mapped[payload_start:payload_end])
                    if CRC.unpack(payload)[0] != digest:
                        break
                    for record_type2, key, value in records:
                        self._apply(record_type2, key, value)
                    del pending[txid]
                last_good = offset
        finally:
            mapped.close()

        if file_size != last_good:
            self._file.truncate(last_good)
            self._file.flush()
            os.fsync(self._file.fileno())
        self._next_txid = max(max_txid + 1, 1)

    @property
    def _checkpoint_path(self) -> Path:
        return self.path.with_name(self.path.name + ".index")

    def _load_checkpoint(self) -> bool:
        """Load an advisory clean-close index cache, otherwise return False."""
        assert self._file is not None
        checkpoint = self._checkpoint_path
        try:
            stat = os.fstat(self._file.fileno())
            with checkpoint.open("rb") as source:
                header = source.read(CHECKPOINT_HEADER.size)
                if len(header) != CHECKPOINT_HEADER.size:
                    return False
                magic, db_size, db_mtime_ns, next_txid, count = CHECKPOINT_HEADER.unpack(header)
                if magic != CHECKPOINT_MAGIC or db_size != stat.st_size or db_mtime_ns != stat.st_mtime_ns:
                    return False
                loaded: dict[bytes, bytes] = {}
                for _ in range(count):
                    entry = source.read(CHECKPOINT_ENTRY.size)
                    if len(entry) != CHECKPOINT_ENTRY.size:
                        return False
                    key_len, value_len = CHECKPOINT_ENTRY.unpack(entry)
                    if not 1 <= key_len <= MAX_KEY or value_len > MAX_VALUE:
                        return False
                    key = source.read(key_len)
                    value = source.read(value_len)
                    if len(key) != key_len or len(value) != value_len:
                        return False
                    loaded[key] = value
                if source.read(1):
                    return False
            self._index = loaded
            self._next_txid = max(next_txid, 1)
            return True
        except (OSError, struct.error):
            return False

    def _write_checkpoint(self) -> None:
        """Best-effort durable cache; the database file remains authoritative."""
        assert self._file is not None
        temporary = self._checkpoint_path.with_name(self._checkpoint_path.name + ".tmp")
        try:
            stat = os.fstat(self._file.fileno())
            with temporary.open("wb", buffering=0) as target:
                target.write(CHECKPOINT_HEADER.pack(
                    CHECKPOINT_MAGIC, stat.st_size, stat.st_mtime_ns,
                    self._next_txid, len(self._index)))
                for key, value in self._index.items():
                    target.write(CHECKPOINT_ENTRY.pack(len(key), len(value)))
                    target.write(key)
                    target.write(value)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self._checkpoint_path)
            _fsync_directory(self._checkpoint_path.parent)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _apply(self, record_type: int, key: bytes, value: bytes) -> None:
        if not 1 <= len(key) <= MAX_KEY or len(value) > MAX_VALUE:
            raise DatabaseError("invalid record payload")
        if record_type == PUT:
            self._index[key] = value
        else:
            self._index.pop(key, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DatabaseError("database is closed")


def _fsync_directory(directory: Path) -> None:
    """Persist the rename on filesystems that expose directory fsync."""
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # Windows and some filesystems do not permit opening directories this
        # way. The file itself was already fsynced before replacement.
        pass


def _check_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or not 1 <= len(key) <= MAX_KEY:
        raise InvalidKey("key must be bytes of length 1..1024")
    return key


def _check_value(value: Optional[bytes]) -> bytes:
    if not isinstance(value, bytes) or len(value) > MAX_VALUE:
        raise InvalidValue("value must be bytes of length 0..1 MiB")
    return value


def _make_frame(record_type: int, txid: int, op_index: int, op_count: int, key: bytes, value: bytes) -> bytes:
    header = HEADER.pack(MAGIC, VERSION, record_type, txid, len(key), len(value), op_index, op_count)
    return header + key + value + CRC.pack(zlib.crc32(header + key + value) & 0xFFFFFFFF)
