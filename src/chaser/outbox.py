import os
import smtplib
from email.message import EmailMessage
from typing import Protocol


class Outbox(Protocol):
    def send(self, *, thread_id: str, sender: str, recipient: str, subject: str, body: str) -> dict:
        ...


class DryRunOutbox:
    def send(self, *, thread_id: str, sender: str, recipient: str, subject: str, body: str) -> dict:
        return {
            "mode": "dry-run",
            "thread_id": thread_id,
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "sent": False,
        }


class MockOutbox:
    def __init__(self, inbox):
        self.inbox = inbox

    def send(self, *, thread_id: str, sender: str, recipient: str, subject: str, body: str) -> dict:
        message_id = self.inbox.receive(
            thread_id=thread_id, sender=sender, recipient=recipient, subject=subject, body=body
        )
        return {"mode": "mock", "thread_id": thread_id, "message_id": message_id, "sent": True}


class SMTPOutbox:
    def send(self, *, thread_id: str, sender: str, recipient: str, subject: str, body: str) -> dict:
        host = os.environ.get("CHASER_SMTP_HOST")
        port = int(os.environ.get("CHASER_SMTP_PORT", "587"))
        username = os.environ.get("CHASER_SMTP_USERNAME")
        password = os.environ.get("CHASER_SMTP_PASSWORD")
        if not host:
            raise RuntimeError("CHASER_SMTP_HOST is required for real SMTP")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if username:
                smtp.login(username, password or "")
            smtp.send_message(message)
        return {"mode": "smtp", "thread_id": thread_id, "sent": True}
