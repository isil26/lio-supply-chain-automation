"""Check the private service boundary and attribution in the real settings store."""
import base64
import json
import unittest
from contextlib import closing
from email.message import Message
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.ingest.store import connect, get_state
from src.orchestrator.__main__ import handler


class AccountTest(unittest.TestCase):
    def test_private_api_records_only_the_gateway_account(self):
        with TemporaryDirectory() as tmp:
            database = Path(tmp) / "replay.db"
            loop = SimpleNamespace(database=database, args=SimpleNamespace(demo=True))
            cls = handler(loop, "private-test-token")
            req = object.__new__(cls)
            req.path = "/api/auto-approve"
            req.headers = Message()
            req.headers["Host"] = "localhost"
            req.headers["Content-Type"] = "application/json"
            body = json.dumps({"setBy": "another account", "limitEur": 0}).encode()
            req.headers["Content-Length"] = str(len(body))
            req.rfile = BytesIO(body)
            result = []
            req.out = lambda data, status=200: result.append(status)
            req.do_GET()
            req.do_POST()
            req.headers["Authorization"] = "Bearer private-test-token"
            req.do_POST()
            self.assertEqual(result, [401, 401, 401])
            req.headers["X-Soony-User"] = base64.urlsafe_b64encode(b"murat").decode()
            req.do_POST()
            self.assertEqual(result[-1], 200)
            with closing(connect(database)) as con:
                self.assertEqual(get_state(con, "autoApprove")["setBy"], "murat")
