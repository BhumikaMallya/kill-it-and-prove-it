import tempfile
import unittest
from pathlib import Path

from kvdb import DiskFullError, KVDatabase


class KVDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "data.kdb"

    def tearDown(self):
        self.tempdir.cleanup()

    def open_db(self):
        return KVDatabase(self.path).open()

    def test_put_get_overwrite_delete_survives_reopen(self):
        db = self.open_db()
        db.put(b"a", b"one")
        self.assertEqual(db.get(b"a"), b"one")
        db.put(b"a", b"two")
        db.delete(b"missing")
        db.delete(b"a")
        self.assertIsNone(db.get(b"a"))
        db.close()

        db = self.open_db()
        self.assertIsNone(db.get(b"a"))
        db.close()

    def test_batch_is_applied_in_order_and_survives_reopen(self):
        db = self.open_db()
        db.put(b"keep", b"old")
        db.batch([
            ("put", b"a", b"1"),
            ("put", b"keep", b"new"),
            ("delete", b"a", None),
        ])
        self.assertIsNone(db.get(b"a"))
        self.assertEqual(db.get(b"keep"), b"new")
        db.close()

        db = self.open_db()
        self.assertIsNone(db.get(b"a"))
        self.assertEqual(db.get(b"keep"), b"new")
        db.close()

    def test_incomplete_tail_is_ignored_and_truncated(self):
        db = self.open_db()
        db.put(b"safe", b"value")
        db.close()
        with self.path.open("ab") as file:
            file.write(b"KDB1\x01\x01partial")

        db = self.open_db()
        self.assertEqual(db.get(b"safe"), b"value")
        db.put(b"after", b"tail")
        db.close()

        db = self.open_db()
        self.assertEqual(db.get(b"safe"), b"value")
        self.assertEqual(db.get(b"after"), b"tail")
        db.close()

    def test_batch_without_commit_is_not_visible_after_reopen(self):
        db = self.open_db()
        db.put(b"existing", b"yes")
        db.close()
        with self.path.open("ab") as file:
            # A valid operation record with a nonzero transaction id but no commit.
            from kvdb import _make_frame, PUT
            file.write(_make_frame(PUT, 99, 0, 2, b"ghost", b"value"))

        db = self.open_db()
        self.assertEqual(db.get(b"existing"), b"yes")
        self.assertIsNone(db.get(b"ghost"))
        db.close()

    def test_compaction_shrinks_file_and_preserves_live_data(self):
        db = self.open_db()
        for index in range(30):
            db.put(f"key-{index}".encode(), b"value")
        for index in range(30):
            db.delete(f"key-{index}".encode())
        db.put(b"live", b"yes")
        before = self.path.stat().st_size
        db.compact()
        after = self.path.stat().st_size
        self.assertLess(after, before)
        self.assertEqual(db.get(b"live"), b"yes")
        db.close()

        db = self.open_db()
        self.assertEqual(db.get(b"live"), b"yes")
        self.assertIsNone(db.get(b"key-0"))
        db.close()

    def test_size_limit_rejects_put_and_batch_without_changing_state(self):
        db = KVDatabase(self.path, max_bytes=50).open()
        db.put(b"old", b"value")
        with self.assertRaises(DiskFullError):
            db.put(b"new", b"value")
        self.assertEqual(db.get(b"old"), b"value")
        self.assertIsNone(db.get(b"new"))
        with self.assertRaises(DiskFullError):
            db.batch([("put", b"a", b"1"), ("put", b"b", b"2")])
        self.assertIsNone(db.get(b"a"))
        self.assertIsNone(db.get(b"b"))
        db.close()

        db = KVDatabase(self.path, max_bytes=50).open()
        self.assertEqual(db.get(b"old"), b"value")
        self.assertIsNone(db.get(b"new"))
        db.close()

    def test_checkpoint_accelerates_clean_reopen_and_stale_cache_falls_back(self):
        db = self.open_db()
        db.put(b"cached", b"before")
        db.close()
        checkpoint = self.path.with_name(self.path.name + ".index")
        self.assertTrue(checkpoint.exists())

        db = self.open_db()
        self.assertEqual(db.get(b"cached"), b"before")
        db.put(b"after", b"append")
        db.close()

        checkpoint.unlink()
        db = self.open_db()
        self.assertEqual(db.get(b"cached"), b"before")
        self.assertEqual(db.get(b"after"), b"append")
        db.close()


if __name__ == "__main__":
    unittest.main()
