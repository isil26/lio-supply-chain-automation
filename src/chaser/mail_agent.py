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
    parser.add_argument("command", choices=["status", "check", "compare", "remind"])
    parser.add_argument("--db", default=None, help="compare: SQLite store (default store/soony.db)")
    parser.add_argument("--material", default=None, help="compare: one material only")
    parser.add_argument("--save-drafts", action="store_true", help="compare: store negotiation drafts for approval")
    parser.add_argument("--json", action="store_true", help="compare: print JSON")
    args = parser.parse_args(argv)
    if args.command == "compare":
        return compare_command(args)
    if args.command == "remind":
        return remind_command(args)
    from .mailenv import load_team_mail_env
    load_team_mail_env()
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
        except (smtplib.SMTPAuthenticationError, imaplib.IMAP4.error) as exc:
            ok = False
            print(f"FAIL {name}: login refused ({exc.__class__.__name__}). Check the app password and that IMAP is on.")
        except (OSError, smtplib.SMTPException) as exc:
            ok = False
            print(f"FAIL {name}: cannot reach the mail server ({exc.__class__.__name__}). Check this machine's network.")
    print("Ready. Remember: the sender must be listed under Mail senders in the portal." if ok else "Not ready.")
    return 0 if ok else 1


def compare_command(args):
    import json
    import sqlite3
    from src.ingest.store import DB
    from .negotiate import compare, to_text

    con = sqlite3.connect(args.db or DB)
    row = con.execute("SELECT deadline FROM chases LIMIT 1").fetchone()
    if not row:
        print("No supplier threads yet.")
        return 1
    report = compare(con, row[0], args.material, save=args.save_drafts)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str) if args.json else to_text(report))
    if args.save_drafts:
        print("Negotiation drafts saved. They wait in the control room until a person reviews and sends them.")
    return 0


def remind_command(args):
    import sqlite3
    from src.ingest.store import DB
    from .followup import due_reminders

    con = sqlite3.connect(args.db or DB)
    items = due_reminders(con, save=args.save_drafts)
    if not items:
        print("No supplier is overdue for an answer.")
    for item in items:
        what = "call them" if item["action"] == "call" else f"reminder draft {item['draft_id']}"
        print(f"{item['supplier']}: silent for {item['waited_hours']} h (limit {item['wait_limit_hours']} h) -> {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
