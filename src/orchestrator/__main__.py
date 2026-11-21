"""Run the Soony sync, extraction, readiness, decision and supplier workflows."""
import argparse
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from src import chaser
from src.decide import authorize, choose, decisions
from src.docs import documents, extract, reconcile_handwriting
from src.ingest.store import DB, ROOT, connect, get_state, ingest, now, save_state
from src.truth import LOCAL, readiness

DIST = ROOT / "web" / "dist"
CONTROL_ROOM = Path(__file__).resolve().parent


def drop_summary(previous, current, previous_options, options):
    risk_kinds = {"artwork", "dock_hold", "handwriting", "quality_hold", "short_ship"}
    previous_issues = {(issue["kind"], issue["title"]) for issue in previous["issues"]}
    updates = list(dict.fromkeys(
        issue["title"] for issue in current["issues"]
        if issue["kind"] in risk_kinds and (issue["kind"], issue["title"]) not in previous_issues
    ))[:2]

    # Decision IDs also change when estimates are updated. Identify new options by
    # their action, component and supplier so a revised estimate stays the same option.
    def action(option):
        return option["title"], option.get("material"), option.get("supplier_id")

    previous_actions = {action(option) for option in previous_options}
    new_option = next((option for option in options if action(option) not in previous_actions), None)
    if new_option:
        updates.append(f'New option: {new_option["title"]}')

    for part, row in current["parts"].items():
        old = previous["parts"].get(part)
        if old and old["shortfall"] != row["shortfall"]:
            updates.append(f'{part}: {old["shortfall"]:,} to {row["shortfall"]:,} short')
    return " · ".join(updates)


def cite_text(source):
    path = source["file"]
    location = f' · p. {source["page"]}' if "page" in source else ""
    if source.get("sheet"):
        location += f' · {source["sheet"]}'
    if "row" in source:
        location += f' · row {source["row"]}'
    if source.get("quote"):
        location += ' · ' + " ".join(source["quote"].split())[:450]
    return path + location


def dashboard(con):
    truth = get_state(con, "truth")
    if not truth:
        return None
    chosen = get_state(con, "options", [])
    states = decisions(con)
    actions = [dict(option, status=states.get(option["id"], "pending")) for option in chosen]
    approval = actions[0] if actions else None
    risks = []
    for part in truth["parts"].values():
        flagged = [issue for issue in truth["issues"] if issue["material"] == part["material"] and issue["kind"] in
                   {"quality_hold", "handwriting", "dock_hold", "short_ship", "tracker", "artwork"}]
        first = sum(edition.get("first_stop") == part["material"] for edition in truth["editions"].values())
        if not part["shortfall"] and not first and not flagged:
            continue
        sources = [source for item in flagged for source in item["evidence"]] + part["evidence"]
        suppliers = [rate["supplier"].get("name") for rate in part["suppliers"] if rate.get("supplier")]
        risks.append({"rank": 0, "id": part["material"], "component": part["label"],
                      "supplier": " / ".join(filter(None, suppliers)) or "Unresolved source",
                      "shortfall": f'{part["shortfall"]:,}' if part["shortfall"] else "—", "gap": part["shortfall"],
                      "firstStop": first, "required": part["required"], "onHand": part["on_hand"], "inbound": part["inbound"],
                      "severity": "Critical" if first or part["shortfall"] else "High",
                      "detail": [item["title"] for item in flagged], "evidence": list(dict.fromkeys(map(cite_text, sources))),
                      "sources": sources})
    risks.sort(key=lambda risk: (-risk["firstStop"], -risk["gap"], risk["component"]))
    for rank, risk in enumerate(risks, 1):
        risk["rank"] = rank

    def clock(value):
        return datetime.fromisoformat(value).astimezone(LOCAL).strftime("%H:%M CET") if value else ""

    return {
        "launch": {"name": truth["name"].strip(" -–•"), "deadline": truth["deadline"], "location": truth["site"]},
        "readiness": [{"edition": "CE" if pid.endswith("-CE") else "STD", "percent": round(row["packed"] / row["target"] * 100, 1),
                       "packed": row["packed"], "target": row["target"], "probability": row["probability"], "p50": row["p50"],
                       "p10": row["p10"], "p90": row["p90"], "firstStop": truth["parts"].get(row["first_stop"], {}).get("label"),
                       "status": "At risk" if row["probability"] < .8 else "On track", "tone": "red" if row["probability"] < .3 else "amber"}
                      for pid, row in truth["editions"].items()],
        "risks": risks, "activity": [dict(row, id=str(row["id"]), time=clock(row["time"])) for row in
                                    con.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 15")],
        "threads": [{**thread, "initials": "".join(word[0] for word in thread["supplier"].split()[:2]),
                     "messages": [dict(msg, time=clock(msg["time"])) for msg in thread["messages"]]}
                    for thread in chaser.list_threads(con)],
        "approval": approval, "options": actions,
        "drop": get_state(con, "drop"),
        "sync": get_state(con, "sync"),
        "model": truth["model"], "dataQuality": truth["data_quality"],
    }


class Loop:
    def __init__(self, args):
        self.args = args
        if args.demo or os.getenv("CHASER_REAL_SMTP") != "1":
            os.environ.setdefault("CHASER_SENDER", "launch-team@example.invalid")
        self.lock = threading.Lock()
        self.trigger = threading.Event()
        self.stop = threading.Event()
        self.drop_files = []
        self.initialized = False
        if args.demo:
            demo_dir = ROOT / "runtime" / "replay"
            demo_dir.mkdir(parents=True, exist_ok=True)
            demo_id = str(time.time_ns())
            self.root = demo_dir / demo_id / "data"
            self.database = demo_dir / demo_id / "soony.db"
            baseline = args.data
            pending = {source.relative_to(baseline).as_posix() for source in baseline.rglob("*")
                       if source.is_file() and ("shipping_advice" in source.name.casefold() or "oferta_" in source.name.casefold())}
            for source in baseline.rglob("*"):
                if source.is_file():
                    key = source.relative_to(baseline).as_posix()
                    if key in pending:
                        self.drop_files.append((source, self.root / key))
                    else:
                        self.copy(source, self.root / key)
            cache = ROOT / "store" / "docs_cache.sqlite3"
            if cache.is_file():
                replay_store = self.root.parent / "store"
                replay_store.mkdir(exist_ok=True)
                with closing(sqlite3.connect(cache)) as source, closing(sqlite3.connect(replay_store / cache.name)) as dest:
                    source.backup(dest)
            language_data = ROOT / "runtime" / "tessdata"
            if language_data.is_dir():
                replay_runtime = self.root.parent / "runtime"
                replay_runtime.mkdir(exist_ok=True)
                (replay_runtime / "tessdata").symlink_to(language_data, target_is_directory=True)
        else:
            self.root = args.data
            self.database = args.db

    @staticmethod
    def copy(source, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name("." + dest.name + ".partial")
        shutil.copyfile(source, temp)
        temp.replace(dest)

    def cycle(self, sync=False):
        with self.lock, closing(connect(self.database)) as con:
            chaser.schema(con)
            sync_error = None
            if sync and self.args.online:
                try:
                    subprocess.run([sys.executable, str(ROOT / "bridge" / "sync.py")], cwd=ROOT,
                                   capture_output=True, text=True, timeout=180, check=True)
                except (OSError, subprocess.SubprocessError) as exc:
                    sync_error = f"Portal sync failed ({exc.__class__.__name__}). Last local snapshot remains available."
            before = get_state(con, "truth")
            events = ingest(con, self.root, ROOT / "bridge" / "state.json" if self.args.online else None)
            successful = [event for event in events if event["action"] != "error"]
            with con:
                if successful:
                    save_state(con, "pendingEvents", [*get_state(con, "pendingEvents", []), *successful])
            extracted = extract(con, self.root)
            handwriting = reconcile_handwriting(con, self.root)
            successful = get_state(con, "pendingEvents", [])
            if not self.initialized or before is None or successful or extracted or handwriting or get_state(con, "pendingRecompute", False):
                previous_options = get_state(con, "options", [])
                with con:
                    save_state(con, "pendingRecompute", True)
                truth = readiness(con, self.root)
                options = choose(con, truth)
                draft_count = chaser.draft(con, truth)
                with con:
                    save_state(con, "truth", truth)
                    save_state(con, "options", options)
                    save_state(con, "pendingRecompute", False)
                    save_state(con, "pendingEvents", [])
                    chaser.activity(con, "Readiness Engine", f'Recomputed {len(truth["parts"])} component positions for {len(truth["editions"])} editions.')
                    if extracted:
                        chaser.activity(con, "Document Agent", f'Processed {extracted} documents and reconciled cited fields.')
                    if options:
                        chaser.activity(con, "Decision Copilot", f'Prepared {len(options)} options for Procurement review.')
                    if successful:
                        changed = [{"file": event["source"], "action": event["action"], **event["detail"]} for event in successful]
                        detail = drop_summary(before, truth, previous_options, options) if before else ""
                        detail = detail or f'{len(successful)} sources · {extracted} documents processed'
                        title = "Portal drop processed" if before else "Launch snapshot ready"
                        if self.args.demo and before:
                            title = "Replayed portal drop processed"
                        drop = {"id": now(), "title": title, "detail": detail, "time": now(), "changes": changed, "drafts": draft_count}
                        save_state(con, "drop", drop)
                        chaser.activity(con, "Data Bridge", detail)
            if not self.args.demo:
                try:
                    chaser.poll(con)
                except (OSError, chaser.imaplib.IMAP4.error) as exc:
                    sync_error = (sync_error + " " if sync_error else "") + f"Inbox polling failed ({exc.__class__.__name__})."
            chaser.expire(con)
            with con:
                save_state(con, "sync", {"time": now(), "error": sync_error, "mode": "replay" if self.args.demo else "portal" if self.args.online else "local",
                                        "pendingDrop": len(self.drop_files), "mailMode": "dry-run" if self.args.demo or os.getenv("CHASER_REAL_SMTP") != "1" else "live", "events": [item for item in events if item["action"] == "error"]})
            self.initialized = True
            return len(successful)

    def promote_drop(self):
        with self.lock:
            for source, dest in self.drop_files:
                self.copy(source, dest)
            self.drop_files.clear()

    def background(self):
        while not self.stop.is_set():
            try:
                self.cycle(sync=True)
            except Exception as exc:
                print(f"Pipeline: {exc}", file=sys.stderr, flush=True)
                with closing(connect(self.database)) as con, con:
                    save_state(con, "sync", {"time": now(), "error": str(exc), "mode": "replay" if self.args.demo else "local",
                                            "pendingDrop": len(self.drop_files)})
            self.trigger.wait(self.args.interval)
            self.trigger.clear()


def handler(loop):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not self.local_request():
                return self.out({"error": "Use the loopback address"}, 403)
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                with closing(connect(loop.database)) as con:
                    chaser.schema(con)
                    if path == "/api/dashboard":
                        value = dashboard(con)
                        return self.out(value) if value else self.out({"error": "Building launch snapshot", "sync": get_state(con, "sync")}, 503)
                    if path == "/api/truth":
                        return self.out(get_state(con, "truth"))
                    if path == "/api/documents":
                        return self.out(list(documents(con)))
                    if path.startswith("/api/source/"):
                        return self.file(loop.root, unquote(path[len("/api/source/"):]))
                return self.out({"error": "Unknown API endpoint"}, 404)
            if path == "/live" or (path == "/" and not (DIST / "index.html").is_file()):
                return self.file(CONTROL_ROOM, "control-room.html")
            if path in {"/", "/react"}:
                return self.file(DIST, "index.html")
            return self.file(DIST, unquote(path).lstrip("/"))

        def file(self, base, relative):
            target = (base / relative).resolve()
            if relative.startswith(".") or not target.is_relative_to(base.resolve()) or not target.is_file():
                return self.out({"error": "File unavailable. Build the dashboard in web/ if needed."}, 404)
            body = target.read_bytes()
            content = mimetypes.guess_type(target)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if base == loop.root:
                self.send_header("Content-Security-Policy", "sandbox")
                if content in {"text/html", "application/javascript", "image/svg+xml"}:
                    self.send_header("Content-Disposition", "attachment")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.local_request() or self.headers.get_content_type() != "application/json":
                return self.out({"error": "Local JSON request required"}, 403)
            path = urlsplit(self.path).path
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 4096 or length < 0:
                    return self.out({"error": "Invalid request size"}, 400)
                body = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body, dict):
                    raise ValueError("Request body must be an object")
                if path == "/api/sync":
                    if loop.args.demo:
                        loop.promote_drop()
                    loop.trigger.set()
                    return self.out({"ok": True}, 202)
                with closing(connect(loop.database)) as con:
                    chaser.schema(con)
                    match = re.fullmatch(r"/api/decisions/([a-f0-9]+)/(approve|review)", path)
                    if match:
                        decision = next((item for item in get_state(con, "options", []) if item["id"] == match[1]), None)
                        if not decision:
                            return self.out({"error": "Decision changed. Refresh before approving."}, 409)
                        status = authorize(con, decision, match[2])
                        with con:
                            chaser.activity(con, "Procurement", f'{decision["title"]}: {status}. Purchasing remains subject to its approval chain.')
                        return self.out({"ok": True, "approvalId": match[1], "status": status})
                    match = re.fullmatch(r"/api/threads/([A-F0-9]+)/(send|demo-reply)", path)
                    if match and match[2] == "send":
                        if body.get("confirm") is not True:
                            return self.out({"error": "Review and confirm this supplier message before sending"}, 409)
                        draft = con.execute("SELECT material,qty,status FROM chases WHERE id=?", (match[1],)).fetchone()
                        truth = get_state(con, "truth", {})
                        if draft and draft["status"] == "draft":
                            current = truth.get("parts", {}).get(draft["material"], {})
                            if current.get("shortfall", 0) != draft["qty"]:
                                return self.out({"error": "The quantity has changed. Refresh the launch snapshot before sending."}, 409)
                        chaser.send(con, match[1], demo=loop.args.demo or os.getenv("CHASER_REAL_SMTP") != "1")
                        return self.out({"ok": True})
                    if match and loop.args.demo:
                        message = con.execute("SELECT * FROM chases WHERE id=?", (match[1],)).fetchone()
                        reply_text = body.get("text")
                        if not message or message["status"] != "awaiting reply" or not isinstance(reply_text, str) or not reply_text.strip():
                            raise ValueError("A sent demo thread and reply text are required")
                        reply = EmailMessage()
                        reply["From"], reply["Subject"], reply["In-Reply-To"] = message["address"], message["subject"], message["message_id"]
                        reply.set_content(reply_text)
                        return self.out({"ok": chaser.receive(con, reply)})
                return self.out({"error": "Unknown API endpoint"}, 404)
            except (ValueError, sqlite3.Error) as exc:
                return self.out({"error": str(exc)}, 400)

        def local_request(self):
            host = self.headers.get("Host", "").split(":")[0]
            origin = self.headers.get("Origin")
            return host in {"127.0.0.1", "localhost"} and (not origin or urlsplit(origin).hostname in {"127.0.0.1", "localhost"})

        def out(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--interval", type=float, default=45)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--online", action="store_true", help="poll the private portal")
    modes.add_argument("--demo", action="store_true", help="isolate and replay previously downloaded documents")
    parser.add_argument("--once", action="store_true", help="evaluate once and print the result")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.online and args.data.resolve() != (ROOT / "data").resolve():
        parser.error("online bridge sync requires the default data directory")
    loop = Loop(args)
    if args.once:
        loop.cycle(sync=True)
        with closing(connect(loop.database)) as con:
            print(json.dumps(dashboard(con), ensure_ascii=False, indent=2))
        return
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler(loop)) as server:
        thread = threading.Thread(target=loop.background, daemon=True)
        thread.start()
        print(f"Launch Control Room at http://127.0.0.1:{args.port} (Ctrl-C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            loop.stop.set()
            loop.trigger.set()


if __name__ == "__main__":
    main()
