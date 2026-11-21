"""Only an explicit, first Approve sends the option's message (codex-card-replay, 22 Nov)."""
import tempfile
import unittest
from contextlib import closing
from email.message import Message
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.decide import authorize
from src.ingest.store import connect, save_state
from src.orchestrator.__main__ import handler

OPTION = {"id": "abc", "title": "Check stock", "kind": "alternate", "supplier_id": "SUP-1", "material": "CMP-X"}


def post(database, path):
    request = object.__new__(handler(SimpleNamespace(database=database, args=SimpleNamespace(demo=True))))
    request.headers = Message()
    request.headers["Host"] = "127.0.0.1"
    request.headers["Content-Length"] = "2"
    request.headers["Content-Type"] = "application/json"
    request.path, request.rfile = path, BytesIO(b"{}")
    responses = []
    request.out = lambda payload, status=200: responses.append((payload, status))
    request.do_POST()
    return responses[0]


class OptionDispatchTest(unittest.TestCase):
    def test_review_and_repeat_never_send(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "api.db"
            with closing(connect(database)) as con, con:
                save_state(con, "options", [OPTION])
            with mock.patch("src.chaser.option_mail.send", return_value={"status": "sent"}) as send, \
                 mock.patch("src.chaser.option_mail.preview", return_value={"mode": "send"}):
                with closing(connect(database)) as con:
                    authorize(con, OPTION, "approve")          # approved elsewhere (forecast, another user)
                payload, status = post(database, "/api/decisions/abc/review")
                self.assertEqual((status, payload["status"]), (200, "approved"))
                post(database, "/api/decisions/abc/approve")   # repeat approve
                send.assert_not_called()

    def test_first_approve_sends_once(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "api.db"
            with closing(connect(database)) as con, con:
                save_state(con, "options", [OPTION])
            with mock.patch("src.chaser.option_mail.send", return_value={"status": "sent"}) as send, \
                 mock.patch("src.chaser.option_mail.preview", return_value={"mode": "send"}):
                post(database, "/api/decisions/abc/approve")
                post(database, "/api/decisions/abc/approve")
                post(database, "/api/decisions/abc/review")
                self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
