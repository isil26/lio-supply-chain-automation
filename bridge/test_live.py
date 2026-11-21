import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import unquote

from .live import PortalError, PortalMirror


CONTEXT = "soony/context/onboarding_notes.md"
STOCK = "soony/erp/stock_snapshot.csv"
OLD = "suppliers/a/old.txt"
NEW = "suppliers/a/revised file.txt"


class PortalMirrorTest(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        seed = root / "case-data"
        self.files = {CONTEXT: b"launch notes", STOCK: b"original", OLD: b"old"}
        for name, body in self.files.items():
            target = seed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        self.mirror = PortalMirror(root / "private", seed)
        self.mirror.workspace.mkdir()
        self.mirror.token_file.write_text("test-only-bearer")
        self.get = patch("bridge.live.fetch", side_effect=self.portal).start()
        self.addCleanup(patch.stopall)

    def portal(self, path, token):
        self.assertEqual(token, "test-only-bearer")
        if path == "/api/v1/files":
            return json.dumps({"files": [{"path": name, "sha256": sha256(body).hexdigest(), "bytes": len(body)}
                                         for name, body in self.files.items()]}).encode()
        return self.files[unquote(path.removeprefix("/api/v1/files/"))]

    def test_incremental_snapshot_and_removal_without_mutating_seed(self):
        start = self.mirror.refresh()
        self.assertEqual(self.get.call_count, 1)
        self.mirror.accept(start)
        self.files = {CONTEXT: b"launch notes", STOCK: b"revised", NEW: b"new"}
        self.get.reset_mock()
        end = self.mirror.refresh()
        self.assertEqual(self.get.call_count, 3)  # inventory plus two changed files
        self.assertEqual(self.mirror.current(), start)
        self.mirror.accept(end)
        self.assertEqual(self.mirror.current(), end)
        self.assertEqual((start / STOCK).read_bytes(), b"original")
        self.assertEqual((end / STOCK).read_bytes(), b"revised")
        self.assertTrue((start / OLD).is_file())
        self.assertFalse((end / OLD).exists())

    def test_hash_mismatch_or_bad_inventory_leaves_previous_snapshot(self):
        start = self.mirror.refresh()
        self.mirror.accept(start)
        self.files[NEW] = b"new"
        self.get.side_effect = lambda path, token: self.portal(path, token) if path == "/api/v1/files" else b"bad"
        with self.assertRaisesRegex(PortalError, "hash check"):
            self.mirror.refresh()
        self.assertEqual(self.mirror.current(), start)
        self.get.side_effect = self.portal
        self.files["suppliers/../token"] = b"unsafe path"
        with self.assertRaisesRegex(PortalError, "inventory is invalid"):
            self.mirror.refresh()
        self.assertEqual(self.mirror.current(), start)
