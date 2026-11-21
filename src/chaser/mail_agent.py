"""Mail agent: the team mailbox behind the Supplier Chaser.

    python3 -m src.chaser.mail_agent check     # config + SMTP/IMAP sign-in test, sends nothing
    python3 -m src.chaser.mail_agent status    # what the agent would do, no network

Sending itself happens in the control room: a person reviews a supplier draft,
confirms, and the orchestrator sends it from CHASER_SENDER. Each orchestrator
cycle reads replies ("[SOONY-..." subjects) from the IMAP inbox.
Real mail only goes to the supplier allowlist (see allowlist.py).
"""
import argparse
import imaplib
import os
import smtplib
import ssl
import sys

from .allowlist import DEFAULT_DOMAINS

REQUIRED = ["CHASER_SENDER", "CHASER_SMTP_HOST", "CHASER_SMTP_USERNAME", "CHASER_SMTP_PASSWORD",
            "SOONY_IMAP_HOST", "SOONY_IMAP_USER", "SOONY_IMAP_PASSWORD"]


def status():
    missing = [name for name in REQUIRED if not os.getenv(name)]
    return {
        "sender": os.getenv("CHASER_SENDER") or None,
        "real_sending_enabled": os.getenv("CHASER_REAL_SMTP") == "1",
        "allowed_domains": os.getenv("CHASER_ALLOWED_DOMAINS", DEFAULT_DOMAINS),
        "missing": missing,
    }


def check_smtp():
    host, port = os.environ["CHASER_SMTP_HOST"], int(os.getenv("CHASER_SMTP_PORT", "587"))
    context = ssl.create_default_context()
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=20)
        client.starttls(context=context)
    with client:
        client.login(os.environ["CHASER_SMTP_USERNAME"], os.environ["CHASER_SMTP_PASSWORD"])


def check_imap():
    host, port = os.environ["SOONY_IMAP_HOST"], int(os.getenv("SOONY_IMAP_PORT", "993"))
    with imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=20) as inbox:
        inbox.login(os.environ["SOONY_IMAP_USER"], os.environ["SOONY_IMAP_PASSWORD"])
        inbox.select("INBOX", readonly=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m src.chaser.mail_agent")
    parser.add_argument("command", choices=["status", "check"])
    args = parser.parse_args(argv)
    info = status()
    print(f"Mail agent sender: {info['sender'] or '(not set)'}")
    print(f"Real sending: {'ON' if info['real_sending_enabled'] else 'off (dry-run)'}; suppliers only: {info['allowed_domains']}")
    if info["missing"]:
        print("Missing in .env: " + ", ".join(info["missing"]))
        return 1
    if args.command == "status":
        return 0
    ok = True
    for name, step in (("SMTP sign-in (sending)", check_smtp), ("IMAP sign-in (replies)", check_imap)):
        try:
            step()
            print(f"OK   {name}")
        except (OSError, smtplib.SMTPException, imaplib.IMAP4.error) as exc:
            ok = False
            print(f"FAIL {name}: {exc.__class__.__name__}. Check the app password and that IMAP is on.")
    print("Ready. Remember: the sender must be listed under Mail senders in the portal." if ok else "Not ready.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
