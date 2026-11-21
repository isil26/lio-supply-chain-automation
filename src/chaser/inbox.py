import uuid
from datetime import datetime, timezone

from .store import ChaserStore


class MockSupplierInbox:
    def __init__(self, store: ChaserStore):
        self.store = store

    def receive(self, *, thread_id: str, sender: str, recipient: str, subject: str, body: str) -> str:
        message_id = str(uuid.uuid4())
        at = datetime.now(timezone.utc).isoformat()
        self.store.add_inbox({
            "inbox_id": message_id,
            "thread_id": thread_id,
            "sender": recipient,
            "recipient": sender,
            "subject": f"Re: {subject}",
            "body": body,
            "created_at": at,
        })
        self.store.log(thread_id, "mock_inbox_received", {"inbox_id": message_id}, at)
        return message_id

    def add_reply(self, *, thread_id: str, supplier_email: str, text: str) -> str:
        reply_id = str(uuid.uuid4())
        at = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO inbox(inbox_id,thread_id,sender,recipient,subject,body,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (reply_id, thread_id, supplier_email, "portal@localhost", "Supplier reply", text, at),
            )
        return reply_id
