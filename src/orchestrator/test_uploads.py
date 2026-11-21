from base64 import b64encode
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from zipfile import ZipFile, ZipInfo

from src.orchestrator.uploads import UploadError, Uploads, stage_upload


class UploadTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.seed = self.root / "case"
        self.seed.mkdir()

    def test_routes_flat_receipt_and_wrapped_zip_to_case_paths(self):
        path = self.root / "payload"
        path.write_bytes(b"receipt")
        expected = "soony/erp/goods_receipts_update.csv"
        flat = stage_upload(path, Path(expected).name, self.seed, self.root / "flat")
        self.assertEqual(list(flat), [expected])
        with ZipFile(path, "w") as archive:
            archive.writestr("case-data/" + expected, b"receipt")
            archive.writestr("__MACOSX/case-data/._receipt", b"metadata")
        files = stage_upload(path, "delivery.zip", self.seed, self.root / "zip")
        self.assertEqual({name: file.read_bytes() for name, file in files.items()}, {expected: b"receipt"})

    def test_archive_cannot_escape_the_case_or_create_links(self):
        path = self.root / "payload"
        for member in ("../../goods_receipts_update.csv", "soony/erp/goods_receipts_update.csv"):
            with self.subTest(member=member):
                with ZipFile(path, "w") as archive:
                    info = ZipInfo(member)
                    if not member.startswith(".."):
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, b"private")
                with self.assertRaises(UploadError):
                    stage_upload(path, "delivery.zip", self.seed, self.root / "zip")

    def test_session_retries_are_idempotent_and_rejection_preserves_result(self):
        def evaluate(seed, candidate, files):
            target = candidate / "data"
            target.mkdir(parents=True)
            for path, source in files.items():
                if source.read_bytes() == b"invalid":
                    raise UploadError("Invalid source data.")
                output = target / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(source.read_bytes())
            return {"dashboard": {"source": seed.name}}

        service = Uploads(lambda: self.seed, evaluate)
        session = "a" * 22
        self.addCleanup(service.remove, session)
        self.addCleanup(service.worker.shutdown)

        def chunk(upload_id, offset, size, body):
            return service.request(session, {
                "id": upload_id, "name": "goods_receipts_update.csv", "offset": offset,
                "size": size, "chunk": b64encode(body).decode(),
            })

        def finished():
            end = monotonic() + 4
            while monotonic() < end:
                state = service.request(session)
                if state["status"] != "processing":
                    return state
                sleep(.01)
            self.fail("Upload worker did not finish")

        first = "b" * 22
        self.assertEqual(chunk(first, 0, 6, b"rec")["received"], 3)
        self.assertEqual(chunk(first, 0, 6, b"rec")["received"], 3)
        chunk(first, 3, 6, b"eip")
        accepted = finished()
        self.assertEqual(accepted["status"], "ready")
        self.assertEqual(service.request("z" * 22), {"status": "idle"})
        chunk("c" * 22, 0, 7, b"invalid")
        rejected = finished()
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["result"], accepted["result"])
        self.assertEqual(service.request(session, {"reset": True}), {"status": "idle"})
