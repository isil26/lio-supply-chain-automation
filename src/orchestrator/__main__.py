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
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit

from bridge.live import PortalError, PortalMirror
from src import chaser
from src.chaser import actions as action_delivery
from src.chaser.reply_plan import demo_reply
from src.chaser import mail_history, recovery, supplier_loop
from src.decide import authorize, choose, decisions
from src.decide.actions import action_queue, mark_action, recovery_reviews, source_proposals
from src.decide.release_gate import release_gate
from src.docs import documents, extract, reconcile_handwriting
from src.ingest.store import DB, ROOT, connect, get_state, ingest, now, save_state
from src.orchestrator import action_approvals
from src.orchestrator.numbers import numbers_report
from src.truth import LOCAL, readiness
from src.agents.loop import AutonomyLoop

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
    for pid, row in current.get("editions", {}).items():
        prior = previous["editions"].get(pid, {}).get("p50")
        if prior is not None and row.get("p50") != prior:
            updates.insert(0, f'{row.get("edition", pid)} median forecast: {prior:,} → {row["p50"]:,}')
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


def dashboard_activity(con, blocked, clock, *, docs=None, reviews=()):
    general = [dict(row, id=str(row["id"]), tool=None, input_ref=None, output_ref=None, status=None, citation=None)
               for row in con.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 15")]
    traced = []
    pages = {}
    for doc in documents(con) if docs is None else docs:
        for index, event in enumerate(doc.get("activity", [])):
            item = dict(event, id=f'doc:{doc["source"]}:{index}',
                        type="warning" if event["status"] in {"error", "rejected"} else "analysis")
            traced.append(item)
            if doc["kind"] in {"notice", "receiving"}:
                pages.setdefault(event["input_ref"], []).append(item)
    escalation = []
    for action in blocked:
        block = action["approval_block"]
        escalation.append({
            "id": f'approval:{action["id"]}', "agent": "Decision Copilot", "tool": block.get("tool", "ppap_policy"),
            "input_ref": action["supplier_id"], "output_ref": f'options/{action["id"]}', "status": "blocked",
            "citation": block.get("policy_clause"), "type": "warning", "time": action.get("evaluated_at"),
            "action": f'{action["title"]}. {block["reason"]}' if block.get("tool") else
                      f'{action["title"]}. {action["recommendation"]} {action["impact"]}',
        })
    # Surface one evidence chain per model tool so a single verbose page cannot crowd out the other.
    proof = []
    for tool in ("llm_vision", "llm_text"):
        chains = [events for events in pages.values() if any(event["tool"] == tool for event in events)]
        if chains:
            chain = max(chains, key=lambda events: (any(event["status"] == "accepted" for event in events),
                                                     events[-1]["time"]))
            read_tools = {"ocr_crop"} if tool == "llm_vision" else {"ocr", "pdf_text"}
            read = next((event for event in chain if event["tool"] in read_tools), None)
            call = next(event for event in chain if event["tool"] == tool)
            validations = [event for event in chain if event["tool"] == "quote_validation"]
            outcome = next((event for event in validations if event["status"] == "accepted"),
                           validations[0] if validations else None)
            proof.extend(event for event in (read, call, outcome) if event)
    shown = {event["id"] for event in proof}
    review_activity = [
        {"id": f'doc:{review["file"]}:review', "agent": "Document Agent", "tool": "document_review",
         "type": "warning", "status": "needs_review", "action": f'Needs review · {review["file"]} · {review["reason"]}',
         "input_ref": review["file"], "output_ref": None, "citation": {"file": review["file"]}, "time": ""}
        for review in reviews[-5:]
    ]
    recent = [*escalation, *proof, *review_activity, *general, *sorted((event for event in traced if event["id"] not in shown),
                                                  key=lambda event: event["time"], reverse=True)]
    return [dict(event, time=clock(event["time"])) for event in recent]


def network(con, site_id, short_materials):
    """Supplier and shipment positions for the map, read from the ingested master data and shipment feed."""
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"records", "suppliers", "supplier_components", "open_shipments"} <= tables:
        return {"hub": None, "suppliers": [], "shipments": []}
    hub = None
    for (payload,) in con.execute("SELECT payload FROM records WHERE kind = 'site'"):
        row = json.loads(payload)
        if row.get("site_id") == site_id and row.get("lat") is not None:
            hub = {"id": site_id, "name": row.get("city") or row.get("name"), "lat": row["lat"], "lon": row["lon"]}
    supply = {}
    for supplier, material in con.execute("SELECT supplier_id, component_id FROM supplier_components"):
        supply.setdefault(supplier, set()).add(material)
    # One point per supplier: a re-sent profile (e.g. a data drop) can leave several rows; the last one wins.
    suppliers = list({sid: {"id": sid, "name": name, "city": city, "country": country, "lat": lat, "lon": lon,
                            "atRisk": bool(supply.get(sid, set()) & short_materials)}
                      for sid, name, city, country, lat, lon in con.execute(
                          "SELECT supplier_id, name, city, country, lat, lon FROM suppliers "
                          "WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY rowid")}.values())
    shipments = []
    for sid, supplier, mode, status, lat, lon, eta, materials in con.execute(
            "SELECT shipment_id, supplier_id, mode, status, last_lat, last_lon, eta, material_ids FROM open_shipments "
            "WHERE last_lat IS NOT NULL AND last_lon IS NOT NULL"):
        mats = set(json.loads(materials) if str(materials).startswith("[") else str(materials or "").replace("|", " ").split())
        shipments.append({"id": sid, "supplier": supplier, "mode": mode, "status": status, "lat": lat, "lon": lon,
                          "eta": str(eta or ""), "atRisk": bool(mats & short_materials)})
    return {"hub": hub, "suppliers": suppliers, "shipments": shipments}


def supplier_option_block(option, constraints):
    if option.get("kind") in {"air", "alternate", "partial"}:
        return constraints.get((option.get("supplier_id"), option.get("material")))
    return None


def std_costs(con):
    """Finished-goods standard cost per product (products.csv), for the euro view of the gap."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'products'").fetchone():
        return {}
    return {pid: cost for pid, cost in con.execute("SELECT product_id, std_cost_eur FROM products") if cost is not None}


# Option kind (src/decide) -> action kind of the approval engine (src/decide/approvals.py, T93).
ENGINE_KIND = {"inbound": "dock_slot", "partial": "hold_and_quote", "quality": "quality_exception",
               "air": "air_freight", "alternate": "supplier_info_request", "ppap_release": "supplier_release",
               "priority": "internal_message"}


def approval_mode(option):
    """Ask the approval engine how this option may be approved (AUTO / ONE_CLICK / ESCALATE / NEVER)."""
    kind = ENGINE_KIND.get(option.get("kind"))
    if not kind:
        return None
    try:
        from src.decide import approvals
        verdict = approvals.evaluate({
            "id": option.get("id"), "kind": kind, "value_eur": option.get("price") if option.get("price") is not None
            else (0 if kind in ("dock_slot", "quality_exception", "supplier_info_request", "internal_message", "supplier_release") else None),
            "part": option.get("material"), "site": "DC-HAM" if kind == "dock_slot" else None,
            "binding": kind not in ("supplier_info_request", "internal_message"), "reversible": kind != "purchase_order",
            "evidence": [cite_text(source) if isinstance(source, dict) else str(source) for source in option.get("evidence") or []]})
    except Exception:  # engine missing or changed: the UI falls back to one-click
        return None
    name = lambda person: person.get("name") if isinstance(person, dict) else person
    chain = [name(step) for step in verdict.get("escalation_chain") or [] if name(step)]
    return {"mode": verdict.get("mode"), "approver": name(verdict.get("approver")), "reason": verdict.get("reason"),
            "slaMinutes": verdict.get("sla_minutes"), "escalateTo": chain[0] if chain else None,
            "blockedBy": verdict.get("blocked_by") or []}


def auto_approve(con, demo=False):
    """Approve open options that cost no more than the team's auto-approve limit (slider in the UI).

    Never auto-approves what the approval engine marks NEVER (quality release, unpriced) or ESCALATE, anything
    with an approval block, or anything a live supplier reply has made obsolete. Every approval is logged."""
    setting = get_state(con, "autoApprove", {}) or {}
    limit = setting.get("limitEur") or 0
    if limit <= 0:
        return []
    done = decisions(con)
    try:
        constraints = chaser.live_reply_constraints(con) if not demo else []
    except Exception:
        constraints = []
    approved = []
    for option in get_state(con, "options", []) or []:
        if option["id"] in done or option.get("approval_block"):
            continue
        mode = (approval_mode(option) or {}).get("mode")
        if mode not in ("AUTO", "ONE_CLICK") or (option.get("price") or 0) > limit:
            continue
        if constraints and supplier_option_block(option, constraints):
            continue
        try:
            authorize(con, option, "approve")
        except PermissionError:
            continue
        approved.append(option["id"])
        with con:
            chaser.activity(con, "Auto-approve", f'{option["title"]}: approved automatically (cost up to €{limit:,.0f}, rule set by {setting.get("setBy") or "the team"}).')
    if approved:
        with con:
            save_state(con, "autoApproved", sorted(set(get_state(con, "autoApproved", []) or []) | set(approved)))
    return approved


def customer_inputs():
    """Numbers the customer told us in interviews (config/customer_inputs.json), e.g. cost of a missed copy."""
    path = ROOT / "config" / "customer_inputs.json"
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def inbound_timeline(truth):
    """Inbound lots of the part that stops packing first, with the modelled handling delay, for the arrival timeline."""
    binding = {row.get("first_stop") for row in truth["editions"].values()} - {None}
    deadline = datetime.fromisoformat(truth["deadline"])
    lags = truth.get("model", {}).get("lag_hours", {})
    lots = []
    for lot in truth.get("inbound", []):
        if lot.get("material") not in binding or not lot.get("quantity") or not lot.get("earliest"):
            continue
        earliest = datetime.fromisoformat(lot["earliest"])
        if earliest > deadline + timedelta(days=2):
            continue
        lots.append({"id": lot["id"], "reference": lot.get("reference"), "material": lot["material"],
                     "label": truth["parts"].get(lot["material"], {}).get("label"), "quantity": lot["quantity"],
                     "mode": lot.get("mode"), "earliest": lot["earliest"], "held": bool(lot.get("held")),
                     "lagHours": lags.get(lot.get("mode"))})
    return {"deadline": truth["deadline"], "lots": sorted(lots, key=lambda lot: lot["earliest"])}


def dashboard(con, *, include_action_history=False):
    # Keep the risks, options and banner on the same published replay snapshot.
    snapshot = {row["key"]: json.loads(row["value"]) for row in con.execute(
        "SELECT key, value FROM state WHERE key IN ('truth', 'options', 'drop', 'sync', 'actionProposals')"
    )}
    truth = snapshot.get("truth")
    if not truth:
        return None
    chosen = snapshot.get("options", [])
    states = decisions(con)
    live = (snapshot.get("sync") or {}).get("mailMode") == "live"
    constraints = chaser.live_reply_constraints(con) if live else {}
    supplier_actions = supplier_loop.view(con, "demo" if (snapshot.get("sync") or {}).get("mode") == "replay" else "live")
    if live:
        supplier_actions = [*recovery.view(con), *supplier_actions]
    obsolete_dock = {item["optionId"]: item["detail"] for item in supplier_actions
                     if item["kind"] == "review_recovery" and item.get("optionId")}
    for option in chosen:
        if constraint := supplier_option_block(option, constraints):
            obsolete_dock[option["id"]] = constraint["nextAction"]
    actions = [dict(option, status="blocked", review_requested=states.get(option["id"]) == "review")
               if option.get("approval_block") else dict(option, status=states.get(option["id"], "pending"))
               for option in chosen]
    for option in actions:
        option["approvalMode"] = approval_mode(option)
    for option in actions:
        if option["id"] in obsolete_dock:
            option.update(status="blocked", approval_block={"reason": obsolete_dock[option["id"]],
                           "tool": "supplier_reply", "owner": option.get("owner")})
    blocked = [option for option in actions if option["status"] == "blocked"]
    approval = next((option for option in actions if option["id"] not in obsolete_dock), actions[0] if actions else None)
    risks = []
    for part in truth["parts"].values():
        flagged = [issue for issue in truth["issues"] if issue["material"] == part["material"] and issue["kind"] in
                   {"quality_hold", "handwriting", "dock_hold", "short_ship", "tracker", "artwork", "revision_hold", "shipment_change"}]
        first = sum(edition.get("first_stop") == part["material"] for edition in truth["editions"].values())
        if not part["shortfall"] and not first and not flagged:
            continue
        sources = [source for item in flagged for source in item["evidence"]] + part["evidence"]
        suppliers = [rate["supplier"].get("name") for rate in part["suppliers"] if rate.get("supplier")]
        correspondence = [f'{rate["supplier"]["name"]}: {constraint["afterState"]}' for rate in part["suppliers"]
                          if rate.get("supplier") and (constraint := constraints.get((rate["supplier_id"], part["material"])))]
        risks.append({"rank": 0, "id": part["material"], "component": part["label"],
                      "supplier": " / ".join(filter(None, suppliers)) or "Unresolved source",
                      "shortfall": f'{part["shortfall"]:,}' if part["shortfall"] else "—", "gap": part["shortfall"],
                      "firstStop": first, "required": part["required"], "onHand": part["on_hand"], "inbound": part["inbound"],
                      "severity": "Critical" if first or part["shortfall"] else "High",
                      "detail": [item["title"] for item in flagged] + correspondence, "evidence": list(dict.fromkeys(map(cite_text, sources))),
                      "sources": sources})
    risks.sort(key=lambda risk: (-risk["firstStop"], -risk["gap"], risk["component"]))
    for rank, risk in enumerate(risks, 1):
        risk["rank"] = rank

    def clock(value):
        return datetime.fromisoformat(value).astimezone(LOCAL).strftime("%H:%M CET") if value else ""

    docs = list(documents(con))
    reviews = [{"file": doc["source"], "reason": doc["error"] or ", ".join(doc["review_reasons"])}
               for doc in docs if doc.get("error") or doc.get("review_reasons")]
    sync = snapshot.get("sync") or {}
    parsed = {doc["source"] for doc in docs if doc.get("methods") and not doc.get("error")}
    parsed.update(row[0] for row in con.execute("SELECT DISTINCT source FROM records"))
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingest_files'").fetchone():
        parsed.update(row[0] for row in con.execute("SELECT source FROM ingest_files WHERE row_count > 0"))
    errors = {doc["source"] for doc in docs if doc.get("error")} | {item["source"] for item in sync.get("events", [])}
    last_sync = datetime.fromisoformat(sync["time"]) if sync.get("time") else None
    health = {"filesSeen": sync.get("filesSeen", 0), "filesParsed": len(parsed),
              "needsReview": len({review["file"] for review in [*reviews, *sync.get("warnings", [])]}),
              "errors": len(errors) + int(sync.get("failed", False)),
              "lastSyncAgeSeconds": max(0, int((datetime.now(timezone.utc) - last_sync).total_seconds())) if last_sync else None}
    costs = std_costs(con)
    missed = customer_inputs().get("missed_copy_cost_eur", {})
    queue_reviews = recovery_reviews(con, truth, actions, supplier_actions, include_pending=True)
    return {
        "launch": {"name": truth["name"].strip(" -–•"), "deadline": truth["deadline"], "location": truth["site"]},
        "readiness": [{"edition": "CE" if pid.endswith("-CE") else "STD", "percent": round(row["packed"] / row["target"] * 100, 1),
                       "packed": row["packed"], "target": row["target"], "probability": row["probability"], "p50": row["p50"],
                       "p10": row["p10"], "p90": row["p90"], "firstStop": truth["parts"].get(row["first_stop"], {}).get("label"),
                       "status": "At risk" if row["probability"] < .8 else "On track", "tone": "red" if row["probability"] < .3 else "amber",
                       "productId": pid, "stdCostEur": costs.get(pid),
                       "missCostEur": (missed.get(pid) or {}).get("value"), "missCostConfirmed": (missed.get(pid) or {}).get("confirmed")}
                      for pid, row in truth["editions"].items()],
        "inboundTimeline": inbound_timeline(truth),
        "autoApprove": get_state(con, "autoApprove", {}) or {"limitEur": 0},
        "autoApproved": get_state(con, "autoApproved", []) or [],
        "risks": risks, "activity": dashboard_activity(con, blocked, clock, docs=docs, reviews=reviews), "documentReviews": reviews,
        "threads": [{**thread, "initials": "".join(word[0] for word in thread["supplier"].split()[:2]),
                     "messages": [dict(msg, timestamp=msg["time"], time=clock(msg["time"])) for msg in thread["messages"]]}
                    for thread in chaser.list_threads(con, states)],
        "mailHistory": mail_history.view(clock),
        "supplierActions": supplier_actions,
        "recoveryApprovals": recovery_reviews(con, truth, actions, supplier_actions) if live else [],
        "actions": action_approvals.project(
            con, action_queue(con, truth, actions, queue_reviews, snapshot.get("actionProposals", []),
                              missed, include_history=include_action_history),
            include_history=include_action_history,
        ),
        "approval": approval, "options": actions, "blockedApprovals": blocked,
        "drop": snapshot.get("drop"),
        "sync": snapshot.get("sync"), "dataHealth": health,
        "model": truth["model"], "dataQuality": truth["data_quality"],
        "network": network(con, truth["site"], {risk["id"] for risk in risks if risk["gap"]}),
    }


def supplier_report(con, *, save, kind="all"):
    """T77 mail-agent: best supplier per material plus overdue suppliers. Drafts only."""
    from src.chaser.followup import due_reminders
    from src.chaser.negotiate import compare

    truth = get_state(con, "truth", {}) or {}
    row = con.execute("SELECT deadline FROM chases LIMIT 1").fetchone()
    deadline = truth.get("deadline") or (row[0] if row else None)
    if not deadline:
        return {"materials": [], "reminders": [], "deadline": None}
    report = compare(con, deadline, save=save and kind in ("all", "negotiate"))
    report["reminders"] = due_reminders(con, save=save and kind in ("all", "remind"))
    report["deadline"] = deadline
    return report


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
        self.health = {
            "lastCycleTime": None,
            "durationMs": 0,
            "lockWaitMs": 0,
            "errors": [],
        }
        if args.demo:
            saved_replay = getattr(args, "replay_dir", None)
            session = saved_replay or ROOT / "runtime" / "replay" / str(time.time_ns())
            self.root = session / "data"
            self.database = session / "soony.db"
            baseline = args.data
            pending = {source.relative_to(baseline).as_posix() for source in baseline.rglob("*")
                       if source.is_file() and ("shipping_advice" in source.name.casefold() or "oferta_" in source.name.casefold())}
            for source in baseline.rglob("*"):
                if source.is_file():
                    key = source.relative_to(baseline).as_posix()
                    dest = self.root / key
                    if key in pending and not dest.exists():
                        self.drop_files.append((source, dest))
                    else:
                        self.copy(source, dest)
            cache = ROOT / "store" / "docs_cache.sqlite3"
            if cache.is_file():
                replay_store = self.root.parent / "store"
                replay_store.mkdir(exist_ok=True)
                replay_cache = replay_store / cache.name
                if not replay_cache.exists():
                    with closing(sqlite3.connect(cache)) as source, closing(sqlite3.connect(replay_cache)) as dest:
                        source.backup(dest)
            language_data = ROOT / "runtime" / "tessdata"
            if language_data.is_dir():
                replay_runtime = self.root.parent / "runtime"
                replay_runtime.mkdir(exist_ok=True)
                languages = replay_runtime / "tessdata"
                if not languages.is_symlink():
                    languages.symlink_to(language_data, target_is_directory=True)
        else:
            self.root = args.data
            self.database = args.db
        self.portal = None
        self.portal_state = {}
        self.next_portal_check = 0
        self.rejected_portal = None
        if not args.demo and not args.online:
            workspace = self.database.parent / "portal-sync"
            if (workspace / ".soony_token").is_file() or (workspace / "current").is_file():
                self.portal = PortalMirror(workspace, self.root)
                try:
                    self.root = self.portal.current() or self.root
                except PortalError as error:
                    self.portal_state = {"status": "unavailable", "error": str(error)}
        self.agents = AutonomyLoop(self.database) if os.getenv("SOONY_AGENTS") == "1" else None

    @staticmethod
    def copy(source, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name("." + dest.name + ".partial")
        shutil.copyfile(source, temp)
        temp.replace(dest)

    def portal_candidate(self, check):
        if not check or self.portal is None or time.monotonic() < self.next_portal_check:
            return self.root
        self.next_portal_check = time.monotonic() + 120
        checked = now()
        try:
            candidate = self.portal.refresh()
            if candidate == self.rejected_portal:
                raise PortalError("The new portal drop needs source review. Using the previous snapshot.")
        except (PortalError, OSError) as error:
            reason = str(error) if isinstance(error, PortalError) else "The private portal cache is unavailable."
            self.portal_state.update(status="unavailable", checkedAt=checked, error=reason)
            return self.root
        self.portal_state.update(status="verified", checkedAt=checked, error=None)
        return candidate

    def validate_portal(self, con, root):
        """Try a new drop in a copy of the operational store before using it."""
        if json.loads(self.portal.manifest(root).read_text()) == dict(con.execute("SELECT source,sha FROM files")):
            return
        with TemporaryDirectory(dir=self.portal.workspace, prefix=".validate-") as temp:
            with closing(connect(Path(temp) / "candidate.db")) as trial:
                con.backup(trial)
                ingest(trial, root, self.portal.manifest(root))
                if get_state(trial, "sourceChecks")["rejections"]:
                    raise PortalError("The new portal drop contains a source the engine cannot read.")
                extract(trial, root, output=self.portal.workspace / "store" / "docs.jsonl")
                readiness(trial, root)

    def cycle(self, sync=False):
        started = time.monotonic()
        sync_error = None
        if sync and self.args.online:
            try:
                subprocess.run([sys.executable, str(ROOT / "bridge" / "sync.py")], cwd=ROOT,
                               capture_output=True, text=True, timeout=180, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                sync_error = f"Portal sync failed ({exc.__class__.__name__}). Last local snapshot remains available."
        root = self.portal_candidate(sync)

        lock_started = time.monotonic()
        with self.lock, closing(connect(self.database)) as con:
            self.health["lockWaitMs"] = round((time.monotonic() - lock_started) * 1000)
            chaser.schema(con)
            before = get_state(con, "truth")
            new_portal = self.portal is not None and root != self.root
            if new_portal:
                try:
                    self.validate_portal(con, root)
                except (OSError, ValueError, KeyError, IndexError, sqlite3.Error) as error:
                    reason = str(error) if isinstance(error, PortalError) else "The new portal drop could not be evaluated."
                    self.portal_state.update(status="unavailable", error=reason)
                    self.rejected_portal = root
                    new_portal, root = False, self.root
            manifest = ROOT / "bridge" / "state.json" if self.args.online else None
            if self.portal and self.portal.manifest(root).is_file() and root.is_relative_to(self.portal.snapshots):
                manifest = self.portal.manifest(root)
            events = ingest(con, root, manifest)
            successful = [event for event in events if event["action"] != "error"]
            checks = get_state(con, "sourceChecks")
            with con:
                if successful:
                    save_state(con, "pendingEvents", [*get_state(con, "pendingEvents", []), *successful])
            if self.portal and manifest:
                extracted = extract(con, root, output=self.portal.workspace / "store" / "docs.jsonl")
            else:
                extracted = extract(con, root)
            handwriting = reconcile_handwriting(con, root)
            mail_ready = True
            mail_changed = False
            if not self.args.demo:
                try:
                    chaser.poll(con)
                except (OSError, chaser.imaplib.IMAP4.error) as exc:
                    sync_error = (sync_error + " " if sync_error else "") + f"Inbox polling failed ({exc.__class__.__name__})."
                    mail_ready = False
                supplier_loop.import_verified(con, os.getenv("SOONY_MAIL_HISTORY_DB"))
                chaser.reconcile_reply_constraints(con)
                mail_watermark = recovery.watermark(con)
                last_mail = get_state(con, "forecastMailWatermark", 0)
                mail_changed = recovery.pending_revision(con, last_mail, mail_watermark)
            successful = get_state(con, "pendingEvents", [])
            if (not self.initialized or before is None or new_portal or successful or extracted or handwriting
                    or mail_changed or get_state(con, "pendingRecompute", False)):
                previous_options = get_state(con, "options", [])
                with con:
                    save_state(con, "pendingRecompute", True)
                if self.args.demo:
                    truth = readiness(con, root)
                else:
                    truth = readiness(con, root, reconcile_shipments=lambda lots, deadline:
                                      recovery.reconcile(con, lots, deadline, before or {}))
                    if self.portal:
                        truth["portalShortfalls"] = recovery.portal_shortfalls(
                            before or {}, truth, successful if new_portal else ())
                options = choose(con, truth, root)
                for option in options:
                    if option.get("approval_block"):
                        option["evaluated_at"] = now()
                draft_count = chaser.draft(con, truth, options)
                proposals = source_proposals(con, truth, root)
                with con:
                    save_state(con, "truth", truth)
                    save_state(con, "options", options)
                    save_state(con, "actionProposals", proposals)
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
                        if self.portal and manifest:
                            drop["source"] = "portal"
                        save_state(con, "drop", drop)
                        chaser.activity(con, "Data Bridge", detail)
            if new_portal:
                self.portal.accept(root)
                self.root = root
                self.rejected_portal = None
                self.portal_state["appliedAt"] = now()
            if not self.args.demo:
                if mail_watermark != last_mail:
                    with con:
                        save_state(con, "forecastMailWatermark", mail_watermark)
                recovery.advance(con, get_state(con, "truth", {}))
                action_delivery.refresh(con)
            auto_approve(con, demo=self.args.demo)
            supplier_loop.advance(con, get_state(con, "truth", {}), get_state(con, "options", []),
                                  scope="demo" if self.args.demo else "live",
                                  dispatch=mail_ready and not getattr(self.args, "once", True))
            if mail_ready and not self.args.demo and not getattr(self.args, "once", True):
                from src.chaser import autosend  # T78 mail-agent: automatic sending (live mode only)
                if autosend.enabled(self.args.demo):
                    try:
                        autosend.run(con)
                    except Exception as exc:
                        sync_error = (sync_error + " " if sync_error else "") + f"Automatic email sending failed ({exc.__class__.__name__})."
            chaser.expire(con)
            failed = sync_error is not None
            rejected = checks["rejections"]
            if rejected:
                summary = "Source rejected: " + ", ".join(f'{event["source"]} ({event["detail"]["error"]})' for event in rejected)
                sync_error = f"{sync_error} {summary}" if sync_error else summary
            warnings = [{"file": source, "reason": reasons[0] + (f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else "")}
                        for source, reasons in checks["warnings"].items()]
            with con:
                previous = get_state(con, "sync", {})
                save_state(con, "sync", {"time": previous.get("time") if failed or rejected else now(), "error": sync_error,
                                        "failed": failed, "filesSeen": checks["filesSeen"],
                                        "mode": "replay" if self.args.demo else "portal" if self.args.online or self.portal else "local",
                                        "pendingDrop": len(self.drop_files), "mailMode": "dry-run" if self.args.demo or os.getenv("CHASER_REAL_SMTP") != "1" else "live",
                                        "events": rejected, "warnings": warnings,
                                        **({"portal": {**previous.get("portal", {}), **self.portal_state,
                                                       "snapshot": root.parent.name[:12] if self.portal and manifest else None}}
                                           if self.portal else {})})
            if not getattr(self.args, "once", True) and not sync_error and not rejected:
                queue = dashboard(con, include_action_history=True)["actions"]
                action_approvals.register(con, queue, automatic=not self.args.demo and
                                          mail_ready and os.getenv("CHASER_REAL_SMTP") == "1")
            self.initialized = True
            self.health["lastCycleTime"] = now()
            self.health["durationMs"] = round((time.monotonic() - started) * 1000)
            self.health["errors"] = [sync_error] if sync_error else []
            cycle_result = len(successful)
        if self.agents:
            if cycle_result:
                with closing(connect(self.database)) as agent_con:
                    drop = get_state(agent_con, "drop", {}) or {}
                self.agents.submit({
                    "kind": "drop",
                    "changed_files": [event["source"] for event in successful],
                    "summary": drop.get("detail", "Data drop processed"),
                })
            self.agents.tick()
        return cycle_result

    def promote_drop(self):
        with self.lock:
            for source, dest in self.drop_files:
                self.copy(source, dest)
            self.drop_files.clear()

    def background(self):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                self.cycle(sync=True)
            except Exception as exc:
                print(f"Pipeline: {exc}", file=sys.stderr, flush=True)
                self.health["lastCycleTime"] = now()
                self.health["durationMs"] = round((time.monotonic() - started) * 1000)
                self.health["errors"] = [str(exc)]
                with closing(connect(self.database)) as con, con:
                    previous = get_state(con, "sync", {})
                    save_state(con, "sync", {**previous, "error": str(exc), "failed": True, "pendingDrop": len(self.drop_files)})
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
                    if path == "/api/health":
                        snapshot = dashboard(con)
                        data_health = snapshot["dataHealth"] if snapshot else None
                        health = dict(loop.health)
                        health.update({
                            "last_cycle_time": health["lastCycleTime"],
                            "duration_ms": health["durationMs"],
                            "duration_seconds": round(health["durationMs"] / 1000, 3),
                            "lock_wait_ms": health["lockWaitMs"],
                            "lock_wait_seconds": round(health["lockWaitMs"] / 1000, 3),
                            "dataHealth": data_health,
                            "backendCommit": os.getenv("SOONY_RELEASE_SHA"),
                        })
                        return self.out(health)
                    if path == "/api/actions":
                        value = dashboard(con, include_action_history=True)
                        return self.out({"actions": value["actions"] if value else []})
                    if path == "/api/dashboard":
                        value = dashboard(con, include_action_history=True)
                        if value is not None:
                            from src.chaser import autosend
                            value["autoSend"] = autosend.enabled(loop.args.demo)
                        if value is not None and loop.agents:
                            value["agents"] = {
                                "enabled": loop.agents.enabled,
                                "mode": os.getenv("SOONY_AGENT_MODE", "live"),
                                "status": "offline (deterministic mode)" if not loop.agents.enabled else "running",
                                "runs": loop.agents.runs(5),
                            }
                        return self.out(value) if value else self.out({"error": "Building launch snapshot", "sync": get_state(con, "sync")}, 503)
                    if path == "/api/agents/runs":
                        return self.out(loop.agents.runs() if loop.agents else [])
                    if path.startswith("/api/agents/trace"):
                        run_id = urlsplit(self.path).query.removeprefix("run=")
                        if not loop.agents or not run_id:
                            return self.out({"error": "run is required"}, 400)
                        try:
                            return self.out(loop.agents.trace(run_id))
                        except KeyError:
                            return self.out({"error": "Unknown agent run"}, 404)
                    if path == "/api/truth":
                        return self.out(get_state(con, "truth"))
                    if path == "/api/release-gate":
                        return self.out(release_gate(con, loop.root))
                    if path == "/api/deals":  # T90 mail-agent: offers table with best offer per part
                        from src.chaser import deals as supplier_deals
                        deadline = (get_state(con, "truth", {}) or {}).get("deadline")
                        if deadline:
                            supplier_deals.sync(con, deadline)
                        return self.out(supplier_deals.list_deals(con))
                    if path == "/api/mail/held":  # IMPORTANT 6 mail-agent: binding emails waiting for one click
                        from src.chaser import autosend as mail_auto
                        return self.out({"held": mail_auto.held(con)})
                    if path == "/api/suppliers/best":  # T77 mail-agent: read-only ranking
                        return self.out(supplier_report(con, save=False))
                    if path == "/api/documents":
                        return self.out(list(documents(con)))
                    if path.startswith("/api/source/"):
                        return self.file(loop.root, unquote(path[len("/api/source/"):]), source=True)
                return self.out({"error": "Unknown API endpoint"}, 404)
            if path == "/live" or (path == "/" and not (DIST / "index.html").is_file()):
                return self.file(CONTROL_ROOM, "control-room.html")
            if path in {"/", "/react"}:
                return self.file(DIST, "index.html")
            return self.file(DIST, unquote(path).lstrip("/"))

        def file(self, base, relative, *, source=False):
            target = (base / relative).resolve()
            if relative.startswith(".") or not target.is_relative_to(base.resolve()) or not target.is_file():
                return self.out({"error": "File unavailable. Build the dashboard in web/ if needed."}, 404)
            body = target.read_bytes()
            content = mimetypes.guess_type(target)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if source:
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
                if path == "/api/agents/stop":
                    if loop.agents:
                        return self.out(loop.agents.stop())
                    return self.out({"ok": True, "status": "stopped"})
                if path == "/api/agents/run":
                    if not loop.agents:
                        return self.out({"ok": False, "status": "offline"}, 409)
                    return self.out(loop.agents.submit(body), 202)
                with closing(connect(loop.database)) as con:
                    chaser.schema(con)
                    action_match = re.fullmatch(r"/api/actions/([a-f0-9]{24})/(approve|dismiss|done)", path)
                    if action_match:
                        with loop.lock:
                            return self.update_action(con, *action_match.groups(), body)
                    deal = re.fullmatch(r"/api/deals/([a-f0-9]{12})/(approve|decline)", path)
                    if deal:  # T90 mail-agent: record the decision and draft the supplier email
                        from src.chaser import deals as supplier_deals
                        supplier_deals.schema(con)
                        if deal[2] == "approve" and not loop.args.demo and (
                            recovery.superseded_offer(con, deal[1])
                            or recovery.pending_revision(con, get_state(con, "forecastMailWatermark", 0))
                        ):
                            return self.out({"error": "Supplier evidence changed. Review the current recovery action.",
                                             "status": "blocked"}, 409)
                        try:
                            row = supplier_deals.decide(con, deal[1], deal[2], str(body.get("by") or "team member")[:80],
                                                        (str(body["note"])[:500] if body.get("note") else None))
                        except KeyError:
                            return self.out({"error": "Unknown offer. Refresh the page."}, 404)
                        return self.out({"ok": True, "deal": row})
                    held = re.fullmatch(r"/api/mail/([A-Za-z0-9_-]{1,64})/approve", path)
                    if held:  # IMPORTANT 6 mail-agent: one click on a binding email; the next mail cycle sends it
                        from src.chaser import autosend as mail_auto
                        try:
                            return self.out({"ok": True, **mail_auto.approve(con, held[1], str(body.get("by") or "")[:80])})
                        except KeyError:
                            return self.out({"error": "Unknown email."}, 404)
                        except ValueError as exc:
                            return self.out({"error": str(exc)}, 400)
                    if path == "/api/suppliers/drafts":  # T77 mail-agent: create drafts only, never sends
                        return self.out(supplier_report(con, save=True, kind=body.get("kind", "all")))
                    if path == "/api/auto-approve":
                        try:
                            limit = max(0.0, min(float(body.get("limitEur") or 0), 2_000_000.0))
                        except (TypeError, ValueError):
                            return self.out({"error": "limitEur must be a number"}, 400)
                        with con:
                            save_state(con, "autoApprove", {"limitEur": limit, "setAt": now(), "setBy": str(body.get("setBy") or "")[:80] or None})
                            chaser.activity(con, "Auto-approve", f"Auto-approve limit set to €{limit:,.0f}." if limit else "Auto-approve switched off.")
                        return self.out({"ok": True, "limitEur": limit, "approved": auto_approve(con, demo=loop.args.demo)})
                    match = re.fullmatch(r"/api/decisions/([a-f0-9]+)/(approve|review)", path)
                    if match:
                        if (match[2] == "approve" and not loop.args.demo and
                                recovery.pending_revision(con, get_state(con, "forecastMailWatermark", 0))):
                            return self.out({"error": "A new supplier reply is being reconciled. Refresh before approving.",
                                             "status": "blocked"}, 409)
                        decision = next((item for item in get_state(con, "options", []) if item["id"] == match[1]), None)
                        if not decision:
                            return self.out({"error": "Decision changed. Refresh before approving."}, 409)
                        active = supplier_loop.view(con, "demo" if loop.args.demo else "live")
                        if match[2] == "approve" and not loop.args.demo and (
                            constraint := supplier_option_block(decision, chaser.live_reply_constraints(con))
                        ):
                            return self.out({"error": constraint["nextAction"], "status": "blocked"}, 409)
                        if match[2] == "approve" and any(a["kind"] == "review_recovery" and a.get("optionId") == match[1] for a in active):
                            return self.out({"error": "The matched shipment reply changed the dock plan. Review launch recovery.", "status": "blocked"}, 409)
                        try:
                            status = authorize(con, decision, match[2])
                        except PermissionError as exc:
                            return self.out({"error": str(exc), "status": "blocked"}, 409)
                        with con:
                            message = ("Review requested. Release remains blocked." if status == "blocked"
                                       else f"{status}. Purchasing remains subject to its approval chain.")
                            chaser.activity(con, "Procurement", f'{decision["title"]}: {message}')
                        return self.out({"ok": True, "approvalId": match[1], "status": status})
                    reply_action = re.fullmatch(r"/api/reply-decisions/([0-9]{1,12})/approve", path)
                    if reply_action:
                        decision = chaser.reply_decision(con, int(reply_action[1]))
                        if not decision:
                            return self.out({"error": "No actionable reply decision"}, 404)
                        status = authorize(con, decision, "approve")
                        return self.out({"ok": True, "status": status})
                    match = re.fullmatch(r"/api/threads/([A-F0-9]+)/(send|demo-reply)", path)
                    if match and match[2] == "send":
                        if body.get("confirm") is not True:
                            return self.out({"error": "Review and confirm this supplier message before sending"}, 409)
                        draft = con.execute("SELECT supplier_id,material,qty,status FROM chases WHERE id=?", (match[1],)).fetchone()
                        truth = get_state(con, "truth", {})
                        if draft and draft["status"] == "draft":
                            current = truth.get("parts", {}).get(draft["material"], {})
                            if current.get("shortfall", 0) != draft["qty"]:
                                return self.out({"error": "The quantity has changed. Refresh the launch snapshot before sending."}, 409)
                        managed = bool(draft and supplier_loop.managed(draft["supplier_id"], draft["material"]))
                        chaser.send(con, match[1], demo=loop.args.demo or (not managed and os.getenv("CHASER_REAL_SMTP") != "1"),
                                    managed=managed)
                        return self.out({"ok": True})
                    if match and loop.args.demo:
                        message = con.execute("SELECT * FROM chases WHERE id=?", (match[1],)).fetchone()
                        reply_text = body.get("text")
                        managed = bool(message and supplier_loop.managed(message["supplier_id"], message["material"]))
                        if not message or (message["status"] != "awaiting reply" and
                                           not (managed and message["status"] == "reply to verify")):
                            raise ValueError("A sent demo thread is required")
                        truth = get_state(con, "truth", {})
                        options = get_state(con, "options", [])
                        scenario = body.get("scenario") if message["material"] == supplier_loop.CARD[1] and managed else None
                        if reply_text is None:
                            reply_text = supplier_loop.sample_card_reply(truth, scenario) if managed and scenario else demo_reply(truth, message, options)
                        if not isinstance(reply_text, str) or not reply_text.strip():
                            raise ValueError("Reply text must be nonempty")
                        reply = EmailMessage()
                        reply["From"], reply["Subject"], reply["In-Reply-To"] = message["address"], message["subject"], message["message_id"]
                        reply["Message-ID"] = make_msgid(domain="simulation.soony.invalid")
                        reply.set_content(reply_text)
                        if scenario == "complete":
                            for kind in ("Commercial invoice", "Packing list", "Air waybill"):
                                reply.add_attachment(f"Simulation only. {kind} for {supplier_loop.SHIPMENT}.",
                                                     filename=f"{kind}.txt")
                        parsed = chaser.receive(con, reply, simulated=True)
                        if parsed and managed:
                            supplier_loop.advance(con, truth, options, scope="demo")
                        if loop.agents and parsed:
                            loop.agents.submit({
                                "kind": "reply",
                                "changed_files": [],
                                "summary": "Supplier reply received and parsed",
                            })
                        return self.out({"ok": parsed})
                return self.out({"error": "Unknown API endpoint"}, 404)
            except (ValueError, sqlite3.Error) as exc:
                return self.out({"error": str(exc)}, 400)
            except PermissionError as exc:
                return self.out({"error": str(exc)}, 403)

        def update_action(self, con, action_id, verb, body):
            by = body.get("by")
            if not isinstance(by, str) or not by.strip() or len(by) > 80:
                return self.out({"error": "A team member name in by is required."}, 400)
            note = body.get("note")
            if note is not None and (not isinstance(note, str) or len(note) > 500):
                return self.out({"error": "Note must be text of 500 characters or fewer."}, 400)
            value = dashboard(con, include_action_history=True)
            action = next((item for item in (value or {}).get("actions", []) if item["id"] == action_id), None)
            if action is None:
                return self.out({"error": "Action changed or is unknown. Refresh the action queue."}, 409)
            status = action["status"]
            if verb == "approve":
                if status in {"dismissed", "done"}:
                    return self.out({"error": "This action is closed."}, 409)
                if status != "pending":
                    return self.out({"ok": True, "action": action})
                sync = value.get("sync") or {}
                supplier = action["kind"] == "supplier"
                if (not loop.args.demo and (sync.get("pendingDrop") or get_state(con, "pendingRecompute", False)
                        or recovery.pending_revision(con, get_state(con, "forecastMailWatermark", 0)))):
                    return self.out({"error": "New evidence is being processed. Refresh before approving."}, 409)
                if supplier and body.get("confirm") is not True:
                    return self.out({"error": "Review and confirm the supplier draft before sending."}, 409)
                delivery = action_approvals.approve(
                    con, action, by.strip(), note, demo=loop.args.demo or sync.get("mailMode") != "live")
                status = delivery["status"]
                if delivery.get("waitingFor"):
                    return self.out({"ok": True, "action": action, "waitingFor": delivery["waitingFor"]}, 202)
            else:
                updated = "dismissed" if verb == "dismiss" else "done"
                if status in {"dismissed", "done"} and status != updated:
                    return self.out({"error": "This action is closed."}, 409)
                if status != updated:
                    if action.get("delivery"):
                        action_delivery.mark(con, action_id, updated, note)
                    mark_action(con, action_id, updated, by.strip(), note)
                    action_approvals.close(con, action_id, updated)
                status = updated
            updated = dashboard(con, include_action_history=True)
            action = next((item for item in updated["actions"] if item["id"] == action_id), dict(action, status=status))
            return self.out({"ok": True, "action": action})

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
    # Windows consoles default to a legacy code page; supplier names and notices need UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--replay-dir", type=Path, help="reuse a private local replay workspace")
    parser.add_argument("--mail-history-config", type=Path, help="private team mailbox configuration for the read-only history reader")
    parser.add_argument("--interval", type=float, default=45)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--online", action="store_true", help="poll the private portal")
    modes.add_argument("--demo", action="store_true", help="isolate and replay previously downloaded documents")
    modes.add_argument("--numbers", action="store_true", help="print the evaluated store snapshot as the deck's Markdown tables")
    parser.add_argument("--once", action="store_true", help="evaluate once and print the result")
    args = parser.parse_args()
    if args.replay_dir and not args.demo:
        parser.error("--replay-dir requires --demo")
    if args.replay_dir:
        args.replay_dir = args.replay_dir.resolve()
        if args.replay_dir.is_relative_to(args.data.resolve()) or args.data.resolve().is_relative_to(args.replay_dir):
            parser.error("the replay workspace and original inputs must be separate")
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.online and args.data.resolve() != (ROOT / "data").resolve():
        parser.error("online bridge sync requires the default data directory")
    if args.numbers:
        if args.once:
            parser.error("refresh with --once, then run --numbers")
        try:
            with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as con:
                con.row_factory = sqlite3.Row
                con.execute("BEGIN")
                print(numbers_report(con))
        except (ValueError, sqlite3.Error) as exc:
            parser.exit(1, f"Cannot read launch numbers: {exc}\n")
        return
    loop = Loop(args)
    if args.once:
        loop.cycle(sync=True)
        with closing(connect(loop.database)) as con:
            print(json.dumps(dashboard(con), ensure_ascii=False, indent=2))
        return
    # Initialize SQLite and WAL before the worker and the first request can open it.
    with closing(connect(loop.database)) as con:
        chaser.schema(con)
    history_config = args.mail_history_config or (args.replay_dir.parent / "mail-history.json" if args.replay_dir else None)
    history_db = settings = None
    if history_config and history_config.is_file():
        settings = json.loads(history_config.read_text())
        history_db = history_config.with_name("mail-history.db")
        os.environ["SOONY_MAIL_HISTORY_DB"] = str(history_db)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler(loop)) as server:
        thread = threading.Thread(target=loop.background, daemon=True)
        thread.start()
        if settings and history_db:
            threading.Thread(target=mail_history.run,
                             args=(loop.stop, loop.database, history_db, settings), daemon=True).start()
        print(f"Launch Control Room at http://127.0.0.1:{args.port} (Ctrl-C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            loop.stop.set()
            loop.trigger.set()


if __name__ == "__main__":
    main()
