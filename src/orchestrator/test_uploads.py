from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path
import shutil
from unittest.mock import Mock, patch
from uuid import uuid4
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

    def test_zip_and_portal_share_files_and_ignore_duplicates(self):
        session = uuid4().hex
        def evaluate(seed, candidate, files):
            target = candidate / "data"
            shutil.copytree(seed, target)
            for name, source in files.items():
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            return {"dashboard": {}}

        service = Uploads(lambda: self.seed, Mock(wraps=evaluate), lambda: "fixture")
        self.addCleanup(service.remove, session)
        self.addCleanup(service.worker.shutdown)

        name = "soony/context/onboarding_notes.md"
        other = "soony/context/arrival.md"
        raw = b"first batch"
        payload = self.root / "case.zip"
        with ZipFile(payload, "w") as archive:
            archive.writestr(name, raw)
            archive.writestr("case/" + name, raw)
            archive.writestr("soony/context/renamed.md", raw)

        def upload():
            body = payload.read_bytes()
            service.request(session, {"id": uuid4().hex, "name": payload.name, "size": len(body),
                                      "offset": 0, "chunk": b64encode(body).decode()})

        def finish():
            service.worker.submit(lambda: None).result(timeout=5)
            state = service.request(session)
            self.assertEqual(state["status"], "ready", state.get("error"))
            return [row["status"] for row in state["report"]["files"]]

        upload()
        self.assertCountEqual(finish(), ["ingested", "unchanged", "unchanged"])
        expected = {name: raw, other: b"second batch"}
        def fetch(path, token, *, limit):
            self.assertEqual(token, "fixture")
            if path == "/api/v1/files":
                return json.dumps({"files": [{"path": key, "bytes": len(value),
                                              "sha256": sha256(value).hexdigest()}
                                             for key, value in expected.items()]}).encode()
            return expected[path.removeprefix("/api/v1/files/")]

        with patch("bridge.live.fetch", side_effect=fetch) as get:
            service.request(session, {"id": uuid4().hex, "source": "portal"})
            self.assertCountEqual(finish(), ["unchanged", "ingested"])
            self.assertEqual(get.call_count, 2)
            get.reset_mock()
            service.request(session, {"id": uuid4().hex, "source": "portal"})
            self.assertEqual(finish(), ["unchanged", "unchanged"])
            self.assertEqual(get.call_count, 1)
        with ZipFile(payload, "w") as archive:
            archive.writestr(other, expected[other])
        upload()
        self.assertEqual(finish(), ["unchanged"])
        self.assertEqual(service.evaluate.call_count, 2)

    def test_conflicting_zip_paths_do_not_replace_each_other(self):
        payload = self.root / "case.zip"
        with ZipFile(payload, "w") as archive:
            archive.writestr("soony/context/example.md", b"one")
            archive.writestr("wrapper/soony/context/example.md", b"two")
        with self.assertRaisesRegex(UploadError, "conflicting versions"):
            stage_upload(payload, payload.name, self.seed, self.root / "stage")

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
        self.assertEqual(service.request("z" * 22)["status"], "idle")
        chunk("c" * 22, 0, 7, b"invalid")
        rejected = finished()
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["result"], accepted["result"])
        self.assertEqual(service.request(session, {"reset": True}), {"status": "idle"})
