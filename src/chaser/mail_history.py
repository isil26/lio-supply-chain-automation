"""Read-only Gmail reconciliation for the protected live dashboard."""

from contextlib import closing
import email
from email.policy import default
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
import imaplib
import json
import os
from pathlib import Path
import re
import ssl

from src import chaser
from src.chaser.allowlist import DEFAULT_DOMAINS
from src.ingest.store import connect, get_state, now, save_state

THREAD_ID = re.compile(r"\[SOONY-([A-F0-9]+)\]")


def _email(raw):
    return email.message_from_bytes(raw, policy=default)


def _raw(inbox, uid, fields):
    status, payload = inbox.uid("fetch", uid, fields)
    if status != "OK":
        return None
    return next((entry[1] for entry in payload if isinstance(entry, tuple)), None)


def _candidates(inbox, mailbox, matches):
    if inbox.select(mailbox, readonly=True)[0] != "OK":
        raise RuntimeError("Cannot open the supplier mailbox read-only")
    status, ids = inbox.uid("search", None, '(HEADER Subject "SOONY-")')
    if status != "OK":
        raise RuntimeError("Cannot search the supplier mailbox")
    for uid in (ids[0] or b"").split()[-200:]:
        header = _raw(inbox, uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT MESSAGE-ID IN-REPLY-TO)])")
        if header and matches(_email(header)):
            body = _raw(inbox, uid, "(BODY.PEEK[])")
            if body:
                yield _email(body)


def _thread(message, threads, sent_threads):
    known = sent_threads.get(str(message["Message-ID"] or ""))
    if known:
        return threads.get(known)
    subject = str(message["Subject"] or "")
    match = THREAD_ID.search(subject)
    return threads.get(match[1]) if match else None


def _address(value):
    return parseaddr(str(value or ""))[1].casefold()


def _belongs_to_sent(message, threads, sent_threads, sender):
    thread = _thread(message, threads, sent_threads)
    return (thread and _address(thread["address"]).endswith("@" + DEFAULT_DOMAINS)
            and _address(message["From"]) == sender.casefold()
            and [_address(addr) for _, addr in getaddresses([str(message["To"] or "")])]
            == [thread["address"].casefold()]
            and str(message["Subject"]) == thread["subject"] and bool(message["Message-ID"]))


def _sent_at(message):
    try:
        date = parsedate_to_datetime(str(message["Date"] or ""))
        if date.tzinfo:
            return date.isoformat()
    except (TypeError, ValueError, AttributeError):
        pass
    return now()


def sync(inbox, sent_folder, *, source_db, history_db, sender):
    """Import only supplier mail tied to a known Chaser thread and Sent record."""
    with closing(connect(source_db)) as source:
        threads = {row["id"]: dict(row) for row in source.execute("SELECT * FROM chases")}
        sent_threads = {row["external_id"]: row["chase_id"] for row in source.execute("""
            SELECT external_id,chase_id FROM messages WHERE side='out'
              AND json_extract(transport,'$.mode') IN ('smtp','gmail')
        """)}
        truth = get_state(source, "truth", {})
        options = get_state(source, "options", [])
    with closing(connect(history_db)) as history:
        chaser.schema(history)
        with history:
            save_state(history, "truth", truth)
            save_state(history, "options", options)
            for message in _candidates(inbox, sent_folder, lambda header: _belongs_to_sent(header, threads, sent_threads, sender)):
                thread = _thread(message, threads, sent_threads)
                body = message.get_body(preferencelist=("plain",))
                if not thread or not body:
                    continue
                text = body.get_content()
                # Legacy mail needs the stored draft as additional evidence.
                if message.get("X-Soony-Chaser") != "1" and text.strip() != thread["body"].strip():
                    continue
                external_id = str(message["Message-ID"])
                history.execute("""INSERT OR IGNORE INTO chases
                   (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,message_id,parent_thread_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (thread["id"], thread["supplier_id"], thread["supplier"], thread["address"], thread["language"],
                    thread["subject"], "awaiting reply", thread["material"], thread["qty"], thread["body"],
                    thread["deadline"], external_id, thread.get("parent_thread_id")))
                metadata = {"from": str(message["From"]), "to": str(message["To"]), "subject": str(message["Subject"]),
                            "messageId": external_id, "inReplyTo": str(message.get("In-Reply-To") or ""),
                            "mode": "gmail", "status": "gmail_sent"}
                history.execute("""INSERT OR IGNORE INTO messages(chase_id,external_id,side,sender,body,time,transport)
                                   VALUES(?,?,?,?,?,?,?)""",
                                (thread["id"], external_id, "out", sender, text, _sent_at(message), json.dumps(metadata)))
        sent = {row["external_id"]: (row["chase_id"], row["address"].casefold()) for row in history.execute(
            """SELECT messages.external_id,messages.chase_id,chases.address
               FROM messages JOIN chases ON chases.id=messages.chase_id WHERE messages.side='out'""")}
        for message in _candidates(inbox, "INBOX", lambda header: (
            str(header["In-Reply-To"] or "") in sent
            and _address(header["From"]) == sent[str(header["In-Reply-To"])][1]
        )):
            chase_id = sent[str(message["In-Reply-To"])][0]
            chaser.receive(history, message, matched_thread_id=chase_id)
        chaser.reconcile_reply_constraints(history)
        chaser.supplier_loop.advance(history, truth, options, scope="verified")
        with history:
            save_state(history, "mailCheck", {"status": "ready", "checkedAt": now()})


def run(stop, source_db, history_db, settings):
    while not stop.is_set():
        try:
            user = settings["user"]
            with imaplib.IMAP4_SSL("imap.gmail.com", ssl_context=ssl.create_default_context(), timeout=15) as inbox:
                inbox.login(user, settings["password"])
                status, folders = inbox.list()
                folder = next((item.rsplit(b' "/" ', 1)[-1].decode() for item in folders or []
                               if isinstance(item, bytes) and re.search(rb'\\Sent\b', item)), None)
                if status != "OK" or not folder:
                    raise RuntimeError("Gmail Sent unavailable")
                sync(inbox, folder, source_db=source_db, history_db=history_db, sender=user)
        except (OSError, ValueError, imaplib.IMAP4.error, RuntimeError):
            with closing(connect(history_db)) as history, history:
                save_state(history, "mailCheck", {"status": "unavailable", "checkedAt": now()})
        stop.wait(60)


def view(clock):
    path = os.getenv("SOONY_MAIL_HISTORY_DB")
    if not path:
        return None
    if not Path(path).is_file():
        return {"status": "checking", "threads": []}
    with closing(connect(path)) as history:
        check = get_state(history, "mailCheck", {"status": "checking"})
        return {**check, "actions": chaser.supplier_loop.view(history, "verified"), "threads": [
            {**thread, "initials": "".join(word[0] for word in thread["supplier"].split()[:2]),
             "messages": [dict(message, timestamp=message["time"], time=clock(message["time"]))
                          for message in thread["messages"]]}
            for thread in chaser.list_threads(history)
        ]}
