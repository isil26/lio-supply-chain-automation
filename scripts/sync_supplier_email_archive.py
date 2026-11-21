"""Refresh the private supplier-email archive from the live team Gmail mailbox."""

import argparse
from collections import Counter
from contextlib import closing, suppress
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
import fcntl
import imaplib
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


REPO = "isil26/lio-supply-chain-automation"
ORIGIN = f"https://github.com/{REPO}.git"
SENDER = "manti.starthackathon@gmail.com"
DOMAIN = "suppliers.juliansibbing.de"
ARCHIVE = Path("docs/supplier-email-archive")
BERLIN = ZoneInfo("Europe/Berlin")
TAG = re.compile(r"\[SOONY-([A-F0-9]{10})\]", re.I)
MSG_ID = re.compile(r"<[^<>\s]+>")
UID = re.compile(rb"\bUID (\d+)")
MAIL_ADDED = re.compile(rb"^\* \d+ EXISTS$")
IDLE_DURATION = 25 * 60
ARCHIVE_NOTE = (
    "New Gmail messages trigger an archive refresh while the mail host is online. "
    "Use the [live supplier mailbox](https://soony-manti-live.vercel.app/?mail=1) "
    "for attachment files."
)
CREDENTIAL = re.compile(
    r"(?i)(?:\b(?:password|passwd|api[_ -]?key|access[_ -]?token|authorization)\s*[:=]\s*\S"
    r"|\b(?:gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|sk-[a-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
COMPONENTS = {
    "CMP-GAM-001": "Game cards", "CMP-GAM-004": "Sleeves",
    "CMP-GAM-008": "Art books", "CMP-GAM-010": "Statues",
}


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=90,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout.strip()


def verify_destination():
    info = json.loads(run("gh", "repo", "view", REPO, "--json", "nameWithOwner,visibility,defaultBranchRef"))
    if info["nameWithOwner"].lower() != REPO or info["visibility"] != "PRIVATE" or info["defaultBranchRef"]["name"] != "main":
        raise ValueError("The configured GitHub destination is no longer the private team repository on main.")


def local_registry(backend):
    chases, ids = {}, {}
    for source in (backend / "live-mail/soony.db", backend / "mail-history.db"):
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            for row in db.execute("SELECT id,supplier_id,supplier,address,material FROM chases"):
                if row["address"].casefold().endswith("@" + DOMAIN):
                    chases[row["id"]] = dict(row)
            ids.update(db.execute("""
                SELECT external_id,chase_id FROM messages
                WHERE (side = 'out' AND json_extract(transport,'$.status') IN ('gmail_sent','smtp_accepted'))
                   OR (side = 'in' AND json_extract(transport,'$.status') = 'received')
            """).fetchall())
    return chases, ids


def header(mail, name):
    return str(mail.get(name) or "")


def address(value):
    return parseaddr(value)[1].casefold()


def candidate(mail, side, chases, ids):
    subject = TAG.search(header(mail, "Subject"))
    external_id = header(mail, "Message-ID").strip()
    if not subject or not MSG_ID.fullmatch(external_id):
        return None
    chain_id = subject[1].upper()
    # Agents sometimes allocate a new chase record while preserving the original email subject.
    chase_id = ids.get(external_id)
    root = chases.get(chain_id)
    chase = chases.get(chase_id) if chase_id else root
    if not root or not chase:
        return None
    if any(root[field] != chase[field] for field in ("supplier_id", "address", "material")):
        raise ValueError("Mailbox metadata links unrelated supplier records.")
    supplier = root["address"].casefold()
    sender = address(header(mail, "From"))
    recipients = [email.casefold() for _, email in getaddresses([header(mail, "To")])]
    matches = (sender == SENDER and recipients == [supplier]) if side == "outbound" else (sender == supplier and SENDER in recipients)
    if matches:
        return chain_id, external_id, chase_id
    return None


def fetch(inbox, uids, fields):
    for start in range(0, len(uids), 30):
        status, payload = inbox.uid("fetch", b",".join(uids[start:start + 30]), fields)
        if status != "OK":
            raise ValueError("Gmail could not fetch the scoped supplier emails.")
        for item in payload:
            if isinstance(item, tuple):
                uid = UID.search(item[0])
                if uid:
                    yield uid[1], BytesParser(policy=policy.default).parsebytes(item[1])


def select_folder(inbox, folders, flag):
    folder = next((line.rsplit(b' "/" ', 1)[-1].decode() for line in folders
                   if isinstance(line, bytes) and flag in line.split(b")", 1)[0].lstrip(b"(").split()), None)
    if not folder or inbox.select(folder, readonly=True)[0] != "OK":
        raise ValueError("Gmail could not open a required folder read-only.")


def tagged_uids(inbox, folders, flag):
    select_folder(inbox, folders, flag)
    status, result = inbox.uid("search", None, '(HEADER Subject "SOONY-")')
    if status != "OK":
        raise ValueError("Gmail could not search the scoped supplier emails.")
    return (result[0] or b"").split()


def exported_message(mail, side, identity, secrets):
    chain_id, external_id, chase_id = identity
    body = mail.get_body(preferencelist=("plain", "html"))
    if body is None:
        raise ValueError(f"Email body is unavailable in supplier chain {chain_id}.")
    date = parsedate_to_datetime(header(mail, "Date"))
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    entry = {
        "direction": side,
        "date": date.isoformat(timespec="seconds"),
        "from": header(mail, "From"),
        "to": header(mail, "To"),
        "subject": header(mail, "Subject"),
        "message_id": external_id,
        "chase_id": chase_id,
        "in_reply_to": header(mail, "In-Reply-To").strip() or None,
        "references": MSG_ID.findall(header(mail, "References")),
        "body_content_type": body.get_content_type(),
        "body": body.get_content().replace("\r\n", "\n").replace("\r", "\n"),
    }
    if cc := header(mail, "Cc"):
        entry["cc"] = cc
    attachments = [{"filename": part.get_filename(), "content_type": part.get_content_type()}
                   for part in mail.walk()
                   if part.get_content_disposition() == "attachment" or part.get_filename()]
    if attachments:
        entry["attachments"] = attachments
    serialized = json.dumps(entry, ensure_ascii=False)
    if CREDENTIAL.search(serialized) or any(secret in serialized for secret in secrets):
        raise ValueError(f"Credential-like text in supplier chain {chain_id} requires review.")
    return entry


def merge_mail(inbox, folders, archive, chases, ids, secrets):
    existing = {message["message_id"]: (key, message["direction"])
                for key, chain in archive.items() for message in chain["messages"]}
    touched = set()
    total = 0
    for side, flag in (("outbound", b"\\Sent"), ("inbound", b"\\All")):
        uids = tagged_uids(inbox, folders, flag)
        fields = "(UID BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT MESSAGE-ID IN-REPLY-TO)])"
        selected = {}
        for uid, mail in fetch(inbox, uids, fields):
            identity = candidate(mail, side, chases, ids)
            if not identity or identity[1] in existing:
                continue
            if side == "inbound" and existing.get(header(mail, "In-Reply-To").strip()) != (identity[0], "outbound"):
                continue
            selected[uid] = identity
        for uid, mail in fetch(inbox, list(selected), "(UID BODY.PEEK[])"):
            identity = selected[uid]
            if candidate(mail, side, chases, ids) != identity:
                raise ValueError("Supplier message headers changed during the read-only fetch.")
            key, external_id, _ = identity
            if external_id in existing:
                continue
            entry = exported_message(mail, side, identity, secrets)
            chase = chases[key]
            chain = archive.setdefault(key, {
                "thread_id": key, "supplier_id": chase["supplier_id"], "supplier": chase["supplier"],
                "material": chase["material"], "messages": [],
            })
            chain["messages"].append(entry)
            touched.add(key)
            existing[external_id] = key, side
            total += 1
    return touched, total


def read_archive(checkout):
    archive = {}
    for path in (checkout / ARCHIVE).glob("*.json"):
        chain = json.loads(path.read_text(encoding="utf-8"))
        if path.stem != chain["thread_id"] or not re.fullmatch(r"[A-F0-9]{10}", path.stem):
            raise ValueError("The existing GitHub archive has an invalid thread file.")
        archive[path.stem] = chain
    if not archive:
        raise ValueError("The existing GitHub archive is missing.")
    return archive


def write_archive(checkout, archive, touched, captured):
    path = checkout / ARCHIVE
    tick = "\x60"
    rows = [
        "# Supplier Chaser email archive", "",
        "SNAPSHOT", "",
        f"Each JSON file contains the original-language bodies, sender and recipient, email timestamps, "
        f"Message-IDs and reply headers. Files group messages by the {tick}[SOONY-…]{tick} tag in the email "
        f"subject. The {tick}chase_id{tick} field links a message to its internal Supplier Chaser record when "
        f"available. Use {tick}in_reply_to{tick} and {tick}references{tick} to trace replies within a chain.",
        "",
        "| Component | Supplier | Email chain | Messages | Latest email |",
        "| --- | --- | --- | ---: | --- |",
    ]
    counts = Counter()
    for key, chain in sorted(archive.items(), key=lambda item: (
        item[1]["material"], item[1]["supplier_id"], item[0]
    )):
        messages = chain["messages"]
        if key in touched:
            messages.sort(key=lambda m: (datetime.fromisoformat(m["date"]), m["message_id"]))
            (path / f"{key}.json").write_text(json.dumps(chain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts.update(m["direction"] for m in messages)
        stamp = datetime.fromisoformat(messages[-1]["date"]).astimezone(BERLIN).strftime("%d %b %H:%M:%S %Z")
        component = chain["material"]
        rows.append(f"| {COMPONENTS.get(component, component)} ({tick}{component}{tick}) | {chain['supplier']} "
                    f"({tick}{chain['supplier_id']}{tick}) | [{key}]({key}.json) | {len(messages)} | {stamp} |")
    stamp = captured.astimezone(BERLIN).strftime("%d %b %Y at %H:%M:%S %Z").lstrip("0")
    suppliers = len({chain["supplier_id"] for chain in archive.values()})
    rows[2] = (f"Team Gmail snapshot taken on **{stamp}**. It contains **{len(archive)} email chains and "
               f"{sum(counts.values())} messages** across {suppliers} suppliers "
               f"({counts['outbound']} sent messages and {counts['inbound']} supplier replies).")
    rows.extend([
        "",
        ARCHIVE_NOTE,
        "",
    ])
    (path / "README.md").write_text("\n".join(rows), encoding="utf-8")
    return sum(counts.values())


def mail_password(backend):
    settings = json.loads((backend / "mail-history.json").read_text(encoding="utf-8"))
    if settings["user"] != SENDER or not settings["password"]:
        raise ValueError("The private team Gmail settings are incomplete.")
    return settings["password"]


def refresh(checkout, backend, publish):
    run("git", "fetch", "--no-tags", "origin", "main", cwd=checkout)
    run("git", "reset", "--hard", "FETCH_HEAD", cwd=checkout)
    archive = read_archive(checkout)
    dashboard_secret = (checkout / "deploy/vercel/team-password.txt").read_text(encoding="utf-8").strip()
    password = mail_password(backend)
    secrets = {secret for secret in (dashboard_secret, password, password.replace(" ", "")) if secret}
    chases, ids = local_registry(backend)
    captured = datetime.now(timezone.utc)
    with imaplib.IMAP4_SSL("imap.gmail.com", ssl_context=ssl.create_default_context(), timeout=20) as inbox:
        inbox.login(SENDER, password)
        status, folders = inbox.list()
        if status != "OK":
            raise ValueError("Gmail could not list the team mailbox folders.")
        touched, added = merge_mail(inbox, folders, archive, chases, ids, secrets)
    if not added:
        print("No new verified supplier emails.")
        return True
    if not publish:
        print(f"Found {added} new verified emails across {len(touched)} chains.")
        return True
    total = write_archive(checkout, archive, touched, captured)
    run("git", "add", "--", str(ARCHIVE), cwd=checkout)
    run("git", "diff", "--cached", "--check", cwd=checkout)
    run("git", "-c", "user.name=codex-mail-archive", "-c",
        "user.email=codex-mail-archive@users.noreply.github.com", "commit",
        "-m", "T93-Mail-Archive: Sync new supplier emails [codex-mail-archive]", cwd=checkout)
    verify_destination()
    result = subprocess.run(["git", "push", "--porcelain", "origin", "HEAD:refs/heads/main"], cwd=checkout,
                            capture_output=True, text=True, timeout=90,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        if "(fetch first)" in result.stdout or "(non-fast-forward)" in result.stdout:
            return False
        raise ValueError("GitHub rejected the private archive update.")
    sha = run("git", "rev-parse", "--short", "HEAD", cwd=checkout)
    print(f"Published {added} new verified emails. The archive now has {total} messages across {len(archive)} chains ({sha}).")
    return True


def sync(backend, publish):
    state = backend / "supplier-email-sync"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        verify_destination()
        checkout = state / "checkout"
        if not (checkout / ".git").is_dir():
            run("git", "clone", "--quiet", "--no-checkout", ORIGIN, str(checkout))
        if run("git", "remote", "get-url", "origin", cwd=checkout) != ORIGIN:
            raise ValueError("The dedicated archive checkout has an unexpected GitHub remote.")
        for _ in range(3):
            if refresh(checkout, backend, publish):
                return
        raise ValueError("GitHub main changed during each attempt to publish. The next sync will retry.")


def idle(inbox, refresh_archive):
    # Python 3.12 and 3.13 expose the IMAP parser without the IDLE context manager.
    # This connection only receives notifications. The refresh uses a separate connection.
    tag = inbox._new_tag()
    inbox.send(tag + b" IDLE\r\n")
    while inbox._get_response() is not None:
        inbox._check_bye()
        if inbox.tagged_commands[tag] is not None:
            raise ValueError("Gmail refused the IDLE subscription.")

    deadline = time.monotonic() + IDLE_DURATION
    print("Gmail IDLE subscribed to All Mail.", flush=True)
    refresh_archive()
    while (remaining := deadline - time.monotonic()) > 0:
        inbox.sock.settimeout(remaining)
        try:
            response = inbox._get_response()
        except TimeoutError:
            return
        inbox._check_bye()
        if inbox.tagged_commands[tag] is not None:
            raise ValueError("Gmail closed the IDLE subscription.")
        if response and MAIL_ADDED.fullmatch(response):
            print("Gmail reported new mail. Refreshing the archive.", flush=True)
            time.sleep(1)
            refresh_archive()


def safe_error(error):
    # The underlying mail parser may include original message content in its errors.
    if type(error) is ValueError and str(error).startswith((
        "The ", "Gmail ", "Mailbox ", "Email body ", "Supplier message ", "Credential-like ", "GitHub ",
    )):
        return str(error)
    return f"Supplier archive sync failed ({type(error).__name__}). Check local mailbox and GitHub access."


SYNC_ERRORS = (ValueError, OSError, KeyError, imaplib.IMAP4.error, sqlite3.Error, subprocess.SubprocessError)


def watch(backend):
    retry_delay = 2
    while True:
        try:
            inbox = imaplib.IMAP4_SSL("imap.gmail.com", ssl_context=ssl.create_default_context(), timeout=20)
            try:
                inbox.login(SENDER, mail_password(backend))
                status, folders = inbox.list()
                if status != "OK":
                    raise ValueError("Gmail could not list the team mailbox folders.")
                select_folder(inbox, folders, b"\\All")
                idle(inbox, lambda: sync(backend, publish=True))
            finally:
                with suppress(OSError):
                    inbox.shutdown()
            retry_delay = 2
        except SYNC_ERRORS as error:
            print(safe_error(error), file=sys.stderr, flush=True)
            time.sleep(retry_delay)
            retry_delay = min(60, 2 * retry_delay)


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, default=project.parent / "soony-case/hosted-backend")
    parser.add_argument("--publish", action="store_true", help="Commit newly verified email to private GitHub main.")
    parser.add_argument("--watch", action="store_true", help="Refresh when Gmail reports new mail over IMAP IDLE.")
    args = parser.parse_args()
    backend = args.backend.resolve()
    if args.watch:
        if not args.publish:
            parser.error("--watch requires --publish")
        watch(backend)
    else:
        sync(backend, args.publish)


if __name__ == "__main__":
    try:
        main()
    except SYNC_ERRORS as error:
        sys.exit(safe_error(error))
