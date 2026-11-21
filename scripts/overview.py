#!/usr/bin/env python3
"""overview-agent (T78): who is doing what right now, from coord/*.md and git log.

Standard library only; does not import or start the main app.

  python scripts/overview.py            # write coord/agents_overview.json + coord/AGENTS_OVERVIEW.md
  python scripts/overview.py --print    # also print the markdown
  python scripts/overview.py --serve 8765 [--every 60] [--push 600]
        # live dashboard at http://127.0.0.1:8765 (git pull + regenerate every N s);
        # --push: also commit+push coord/agents_overview.json + AGENTS_OVERVIEW.md every 600 s when they changed

Rules (read by humans and agents):
  * STATUS.md / TASKS.md are append-only, so the LAST row for an agent (or task ID) wins.
  * Older rows for the same agent+task are reported as superseded, identical rows as duplicates.
  * Last activity = newest of: own commit, STATUS 'Updated' time, INBOX line sent.
  * Commits by `autosync` are attributed to whoever owns the touched directory when unambiguous.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COORD = ROOT / "coord"
OUT_JSON = COORD / "agents_overview.json"
OUT_MD = COORD / "AGENTS_OVERVIEW.md"
DASHBOARD = ROOT / "src" / "overview" / "dashboard.html"

CET = timezone(timedelta(hours=1))  # Munich in November; avoids needing tzdata
YEAR = 2026
STALE_MIN = 90  # in_progress with no sign of life for this long -> flagged

HUMANS = {"nick federspiel": "Nick (human)", "murat göğebakan": "Murat (human)",
          "isil özyigit": "Isil (human)", "gülsah": "Gülsah (human)", "leo": "Leo (human)"}
ALIASES = {"claude": "nick", "claude (coord)": "nick", "lead": "nick", "mail-agent (gülşah-agent)": "mail-agent", "(free)": None,
           "(new owner, claim here)": None, "(released by gülşah-agent)": None}
DONE_STATES = {"done", "released", "review"}
BLOCK_WORDS = re.compile(r"\b(blocked|waits? on|waiting (for|on)|pending|needs?|requires|cannot|can't|not yet)\b", re.I)
REQUEST_WORDS = re.compile(r"\b(please|can you|could you|need|shout if|tell me|share|claim)\b|\?", re.I)


# ---------------------------------------------------------------- parsing
def read(name: str) -> str:
    p = COORD / name
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def table_rows(text: str):
    """Yield (line_no, cells) for markdown table data rows."""
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|") or re.match(r"^\|[\s\-|:]+\|$", s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and cells[0].lower() in {"agent", "id"}:
            continue
        yield i, cells


def norm_agent(name: str) -> str | None:
    n = re.sub(r"\s+", " ", name.strip()).strip("*`")
    low = n.lower()
    if low in ALIASES:
        return ALIASES[low]
    if low in HUMANS:
        return HUMANS[low]
    m = re.match(r"^([\w\-#. ]+?)\s*\(", n)  # "mail-agent (gülşah-agent)" -> mail-agent
    if m and "-" in m.group(1):
        return m.group(1).strip()
    return n or None


NOW = datetime.now(CET)


def parse_when(text: str) -> datetime | None:
    m = re.search(r"(\d{1,2}) Nov(?:\s+(\d{1,2}):(\d{2}))?", text or "")
    if not m:
        return None
    d, hh, mm = int(m.group(1)), m.group(2), m.group(3)
    if hh is None:
        return None  # day only: too coarse to count as activity
    dt = datetime(YEAR, 11, d, int(hh), int(mm), tzinfo=CET)
    if dt > NOW + timedelta(minutes=5):  # some agents write UTC wall-clock times
        dt = datetime(YEAR, 11, d, int(hh), int(mm), tzinfo=timezone.utc)
    return dt if dt <= NOW + timedelta(minutes=5) else None


def norm_state(s: str) -> str:
    low = s.lower()
    for key in ("blocked", "released", "done", "review", "in_progress", "in progress", "assigned", "open"):
        if key in low:
            return key.replace(" ", "_")
    return low or "unknown"


def parse_status():
    rows = []
    for ln, c in table_rows(read("STATUS.md")):
        if len(c) < 4:
            continue
        c += [""] * (6 - len(c))
        rows.append({"line": ln, "agent": norm_agent(c[0]), "raw_agent": c[0], "task": c[1], "dirs": c[2],
                     "state": norm_state(c[3]), "raw_state": c[3], "notes": c[4], "updated": c[5],
                     "when": parse_when(c[5])})
    return [r for r in rows if r["agent"]]


def parse_tasks():
    rows = []
    for ln, c in table_rows(read("TASKS.md")):
        if not c or not re.match(r"^T\d+[a-z\-A-Za-z]*$|^R-", c[0]):
            continue
        tid = c[0]
        if len(c) >= 6:
            title, owner, dirs, status = c[1], c[2], c[3], c[4]
        else:  # malformed row (owner column missing): "| T35 | task | open P1 | dir | dep |"
            title, owner, dirs, status = c[1], "", c[3] if len(c) > 3 else "", c[2] if len(c) > 2 else ""
        if re.search(r"\b(done|open|in_progress)\b", owner) and not re.search(r"\b(done|open|in_progress)\b", status):
            owner, status = re.split(r"\s+(?=done|open|in_progress)", owner, 1)[0], owner  # "copilot-wire done P1"
        rows.append({"line": ln, "id": tid, "title": title, "owner_raw": owner,
                     "owner": norm_agent(owner) if owner and not owner.startswith("(") else None,
                     "dirs": dirs, "state": norm_state(status), "raw_state": status})
    return rows


INBOX_RE = re.compile(r"^\[(?P<when>[^\]]+)\]\s*(?P<frm>[^\-\[\]]+?(?:\([^)]*\))?)\s*->\s*(?P<to>[^:.]+?)\s*[:.]\s*(?P<text>.*)$")


def split_names(s: str):
    out = []
    for part in re.split(r",| and |\+", s):
        part = re.sub(r"\(T[\w\-]+\)", "", part).strip()
        if not part:
            continue
        n = norm_agent(part)
        if n:
            out.append(n)
    return out


def parse_inbox():
    msgs = []
    for i, line in enumerate(read("INBOX.md").splitlines(), 1):
        m = INBOX_RE.match(line.strip())
        if not m:
            continue
        frm = split_names(m.group("frm"))
        to = split_names(m.group("to"))
        text = m.group("text")
        broadcast = any(t.lower() in {"all agents", "all", "team", "team record"} or "team" in t.lower() for t in to)
        kind = "done" if re.search(r"\bDONE\b", line) else (
            "request" if REQUEST_WORDS.search(text) and not broadcast else "info")
        msgs.append({"line": i, "when_raw": m.group("when"), "when": parse_when(m.group("when")),
                     "from": frm[0] if frm else "?", "to": to, "broadcast": broadcast, "kind": kind,
                     "text": text})
    # a request is answered if the addressee later wrote back to the sender, or anyone wrote DONE about it
    for k, msg in enumerate(msgs):
        msg["answered"] = msg["kind"] != "request" or any(
            later["from"] in msg["to"] and (msg["from"] in later["to"] or later["broadcast"])
            for later in msgs[k + 1:])
    return msgs


def git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30).stdout
    except Exception:
        return ""


def parse_git(limit=400):
    out = git("log", f"-{limit}", "--name-only", "--format=\x1e%h\x1f%an\x1f%cI\x1f%s")
    commits = []
    for block in out.split("\x1e")[1:]:
        head, *files = block.strip("\n").split("\n")
        sha, author, iso, subj = head.split("\x1f", 3)
        tag = re.search(r"\[([^\]]+)\]\s*$", subj)
        names = [norm_agent(x) for x in re.split(r"[,;]", re.sub(r"committed by \w+", "", tag.group(1)))
                 if x.strip()] if tag else [norm_agent(author)]
        names = [n for n in names if n] or [norm_agent(author)]
        commits.append({"sha": sha, "author": author, "agent": names[0], "co_agents": names[1:], "when": datetime.fromisoformat(iso),
                        "subject": subj, "files": [f for f in files if f], "autosync": subj.startswith("autosync")})
    return commits


# ---------------------------------------------------------------- analysis
def owner_of_paths(status_rows, task_rows):
    """Map path prefix -> set(agents), from Dir columns."""
    owners = {}
    for r in status_rows + task_rows:
        agent = r.get("agent") or r.get("owner")
        if not agent:
            continue
        for p in re.split(r"[,;+()]| and ", r.get("dirs", "")):
            p = p.strip().strip("`").split(" ")[0].rstrip("/")
            if "/" in p or p in {"web", "coord", "docs"}:
                owners.setdefault(p, set()).add(agent)
    return owners


def iso(dt):
    return dt.astimezone(CET).isoformat(timespec="minutes") if dt else None


def ago(dt, now):
    if not dt:
        return "unknown"
    m = int((now - dt).total_seconds() // 60)
    return f"{m} min ago" if m < 120 else f"{m // 60} h {m % 60:02d} min ago"


def build(now: datetime | None = None):
    global NOW
    now = NOW = now or datetime.now(CET)
    status, tasks, inbox, commits = parse_status(), parse_tasks(), parse_inbox(), parse_git()
    owners = owner_of_paths(status, tasks)
    issues = []

    # latest task row per ID; duplicate/conflicting rows
    latest_task, by_id = {}, {}
    for r in tasks:
        by_id.setdefault(r["id"], []).append(r)
        latest_task[r["id"]] = r
    for tid, rows in by_id.items():
        titles = {re.sub(r"\W+", " ", r["title"].lower())[:40] for r in rows}
        if len(rows) > 1 and len(titles) > 1 and not any("taken" in t or "re-owned" in t or "assigned" in t for t in titles):
            issues.append({"kind": "id_reused", "task": tid, "lines": [r["line"] for r in rows],
                           "text": f"{tid} has {len(rows)} rows with {len(titles)} different titles in TASKS.md (re-owned or ID reused; last row wins; lines {', '.join(str(r['line']) for r in rows)})."})
        elif len(rows) > 2:
            issues.append({"kind": "task_rows", "task": tid, "lines": [r["line"] for r in rows],
                           "text": f"{tid} has {len(rows)} rows in TASKS.md; the last (line {rows[-1]['line']}, '{rows[-1]['raw_state']}') wins."})

    # per agent
    agents = {}
    def A(name):
        return agents.setdefault(name, {"name": name, "kind": "human" if "(human)" in name else "agent",
                                        "status_rows": [], "tasks": [], "commits": [], "sent": [], "received": []})
    for r in status:
        A(r["agent"])["status_rows"].append(r)
    for r in tasks:
        if r["owner"] and latest_task[r["id"]] is r:
            A(r["owner"])["tasks"].append(r)
    for c in commits:
        who = c["agent"]
        if c["autosync"]:  # attribute to the single owner of the touched dirs, if any
            cands = set()
            for f in c["files"]:
                if f.startswith("coord/"):
                    continue
                best = max((p for p in owners if f.startswith(p)), key=len, default=None)
                if best:
                    cands |= owners[best]
            if len(cands) == 1:
                who = next(iter(cands))
                c = dict(c, via_autosync=True)
            else:
                continue  # unattributable autosync: don't count as nick's own work
        if who:
            A(who)["commits"].append(c)
        for co in c.get("co_agents", []):
            A(co)["commits"].append(c)
    def resolve(n):  # "T1 owner" -> current owner of T1
        m = re.match(r"^(T\d+\w*) owner$", n)
        return (latest_task.get(m.group(1), {}).get("owner") or n) if m else n
    for m in inbox:
        m["from"], m["to"] = resolve(m["from"]), [resolve(t) for t in m["to"]]
        A(m["from"])["sent"].append(m)
        for t in m["to"]:
            if not m["broadcast"]:
                A(t)["received"].append(m)

    out_agents = []
    for name, a in agents.items():
        rows = a["status_rows"]
        cur = rows[-1] if rows else None
        # superseded / duplicate status rows
        seen, dups, superseded = {}, 0, 0
        for r in rows:
            key = (r["task"], r["state"], r["notes"])
            if key in seen:
                dups += 1
            seen[key] = r
        task_keys = {}
        for r in rows:
            task_keys.setdefault(r["task"][:20].lower(), []).append(r)
        superseded = sum(len(v) - 1 for v in task_keys.values())
        open_now = []
        for k, v in task_keys.items():
            last = v[-1]
            if last["state"] not in DONE_STATES:
                open_now.append(last)
        last_commit = max(a["commits"], key=lambda c: c["when"], default=None)
        times = [t for t in [last_commit and last_commit["when"], cur and cur["when"]] +
                 [r["when"] for r in rows] + [m["when"] for m in a["sent"]] if t]
        last_act = max(times, default=None)
        state = cur["state"] if cur else (a["tasks"][-1]["state"] if a["tasks"] else "unknown")
        # board tasks still open for this agent
        board_open = [t for t in a["tasks"] if t["state"] not in DONE_STATES]
        flags = []
        if dups:
            flags.append(f"{dups} identical duplicate STATUS row(s)")
        if superseded:
            flags.append(f"{superseded} older STATUS row(s) superseded by newer ones")
        # board says the task is finished (maybe by a re-owner) while this STATUS row is still open
        for r in list(open_now):
            tid = re.match(r"^(T\d+\w*)", r["task"])
            own = [t for t in by_id.get(tid.group(1), []) if t["owner"] == name] if tid else []
            bt = own[-1] if own else (latest_task.get(tid.group(1)) if tid else None)  # ID reuse: prefer own row
            if bt and bt["state"] in {"done", "released"}:
                open_now.remove(r)
                flags.append(f"STATUS line {r['line']} says '{r['raw_state']}' for {tid.group(1)}, but TASKS.md says "
                             f"{bt['state']} ({bt['owner'] or bt['owner_raw']}): outdated row")
                if r is cur:
                    state = "outdated"
        stale_rows = [r for r in open_now if r is not cur]
        for r in stale_rows:
            flags.append(f"STATUS line {r['line']} still says '{r['raw_state']}' for '{r['task'][:50]}' but the agent moved on")
        if state in {"in_progress", "assigned"} and last_act and (now - last_act) > timedelta(minutes=STALE_MIN):
            flags.append(f"in progress but no activity for over {STALE_MIN} min (last {last_act.astimezone(CET):%a %H:%M})")
        if state in {"in_progress", "assigned"} and not last_act:
            flags.append("in progress, but no commit, INBOX line or timed STATUS update found: likely stale")
        for t in a["tasks"]:
            if "not yet acknowledged" in t["raw_state"]:
                flags.append(f"{t['id']} assigned by nick, not acknowledged on the board")
        blockers = []
        if cur and state not in DONE_STATES and BLOCK_WORDS.search(cur["notes"]):
            sent = re.split(r"(?<=[.;])\s+", cur["notes"])
            blockers = [s for s in sent if BLOCK_WORDS.search(s)][:3]
        open_to = [m for m in a["received"] if not m["answered"]]
        open_from = [m for m in a["sent"] if not m["answered"]]
        out_agents.append({
            "name": name, "kind": a["kind"],
            "current_task": cur["task"] if cur else (a["tasks"][-1]["id"] + " " + a["tasks"][-1]["title"] if a["tasks"] else None),
            "state": state,
            "dirs": cur["dirs"] if cur else (a["tasks"][-1]["dirs"] if a["tasks"] else ""),
            "notes": cur["notes"] if cur else "",
            "status_line": cur["line"] if cur else None,
            "last_activity": iso(last_act), "last_activity_ago": ago(last_act, now),
            "last_commit": {"sha": last_commit["sha"], "when": iso(last_commit["when"]), "subject": last_commit["subject"],
                            "via_autosync": bool(last_commit.get("via_autosync"))} if last_commit else None,
            "commits_total": len(a["commits"]),
            "board_tasks": [{"id": t["id"], "title": t["title"][:90], "state": t["state"]} for t in a["tasks"]],
            "board_open": [t["id"] for t in board_open],
            "open_status_rows": [{"line": r["line"], "task": r["task"], "state": r["state"]} for r in open_now],
            "blockers": blockers,
            "inbox_open_to": [{"line": m["line"], "from": m["from"], "when": m["when_raw"], "text": m["text"][:240]} for m in open_to][-6:],
            "inbox_open_from": [{"line": m["line"], "to": m["to"], "when": m["when_raw"], "text": m["text"][:240]} for m in open_from][-6:],
            "flags": flags,
        })

    order = {"blocked": 0, "in_progress": 1, "assigned": 2, "review": 3, "open": 4, "outdated": 5, "unknown": 5, "done": 6, "released": 7}
    out_agents.sort(key=lambda x: (x["kind"] == "human", order.get(x["state"], 5),
                                   -(datetime.fromisoformat(x["last_activity"]).timestamp() if x["last_activity"] else 0)))

    dup_status = sum(1 for _ in status) - len({(r["agent"], r["task"], r["state"], r["notes"]) for r in status})
    open_tasks = [t for t in latest_task.values() if t["state"] == "open"]
    unclaimed = [{"id": t["id"], "title": t["title"][:100]} for t in open_tasks if not t["owner"]]
    if dup_status:
        issues.insert(0, {"kind": "status_duplicates", "text": f"STATUS.md has {dup_status} exact duplicate rows (same agent, task, state, notes)."})
    autosync_n = sum(1 for c in commits if c["autosync"])
    if autosync_n:
        issues.append({"kind": "autosync", "text": f"{autosync_n} of the last {len(commits)} commits are nick's autosync; "
                       "agents that never commit themselves (most copilot-*) only show up through STATUS rows or dir ownership."})

    counts = {}
    for a in out_agents:
        if a["kind"] == "agent":
            counts[a["state"]] = counts.get(a["state"], 0) + 1
    head = commits[0] if commits else None
    return {
        "generated_at": iso(now), "generator": "overview-agent (scripts/overview.py)",
        "head": {"sha": head["sha"], "subject": head["subject"], "when": iso(head["when"])} if head else None,
        "summary": {"agents": sum(1 for a in out_agents if a["kind"] == "agent"), "by_state": counts,
                    "status_rows": len(status), "inbox_requests_open": sum(1 for m in inbox if not m["answered"]),
                    "unclaimed_open_tasks": unclaimed},
        "agents": out_agents, "issues": issues,
        "recent_commits": [{"sha": c["sha"], "agent": c["agent"], "when": iso(c["when"]), "subject": c["subject"]} for c in commits[:15]],
        "rules": "STATUS/TASKS: last row wins. 'answered' = addressee later wrote back to sender. Stale = in_progress, no activity for "
                 f"{STALE_MIN} min.",
    }


# ---------------------------------------------------------------- output
def md(data) -> str:
    s = data["summary"]
    states = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(s["by_state"].items(), key=lambda kv: -kv[1]))
    L = [f"# AGENTS OVERVIEW — generated {data['generated_at']} by overview-agent. Do not edit; run `python scripts/overview.py`.",
         f"Machine-readable: `coord/agents_overview.json`. Head: `{data['head']['sha']}` {data['head']['subject']}" if data["head"] else "",
         "", f"**{s['agents']} agents**: {states}. {s['inbox_requests_open']} INBOX requests look unanswered. "
         f"Hand-written project picture: `coord/OVERVIEW.md` (nick).", "",
         "| Agent | State | Current task | Last activity | Last commit | Attention |", "|---|---|---|---|---|---|"]
    for a in data["agents"]:
        lc = a["last_commit"]
        att = []
        if a["blockers"]:
            att.append("blocker")
        if a["inbox_open_to"]:
            att.append(f"{len(a['inbox_open_to'])} open request(s) to it")
        if any("no activity" in f for f in a["flags"]):
            att.append("stale?")
        task = (a["current_task"] or "-").replace("|", "/")[:70]
        L.append(f"| {a['name']} | {a['state']} | {task} | {a['last_activity_ago']} | "
                 f"{('`' + lc['sha'] + '` ' + lc['subject'][:50].replace('|', '/')) if lc else '-'} | {', '.join(att) or ''} |")
    L += ["", "## Needs attention"]
    for a in data["agents"]:
        bits = []
        if a["blockers"]:
            bits.append("Blocker: " + " ".join(a["blockers"])[:300])
        for m in a["inbox_open_to"][-3:]:
            bits.append(f"Open request from {m['from']} (INBOX line {m['line']}): {m['text'][:160]}")
        bits += [f for f in a["flags"] if "superseded" not in f and "duplicate" not in f]
        if bits:
            L.append(f"- **{a['name']}** ({a['state']})")
            L += [f"  - {b}" for b in bits]
    L += ["", "## Board hygiene"] + [f"- {i['text']}" for i in data["issues"]]
    if s["unclaimed_open_tasks"]:
        L += ["", "## Unclaimed open tasks"] + [f"- {t['id']}: {t['title']}" for t in s["unclaimed_open_tasks"]]
    L += ["", f"_Rules: {data['rules']}_", ""]
    return "\n".join(x for x in L if x is not None)


def write(data):
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(md(data), encoding="utf-8")


# ---------------------------------------------------------------- live server
class State:
    data = None
    lock = threading.Lock()


def refresh(pull: bool):
    if pull:
        git("pull", "--rebase", "--autostash", "-q", "origin", "main")
    d = build()
    with State.lock:
        State.data = d
    return d


VOLATILE = {"generated_at", "last_activity_ago", "head", "recent_commits"}


def fingerprint(data) -> str:
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return json.dumps(strip(data), sort_keys=True, ensure_ascii=False)


def publish(data, last_fp: str | None) -> str | None:
    """Commit + push only the two overview files as overview-agent, if the content really changed."""
    fp = fingerprint(data)
    if fp == last_fp:
        return last_fp
    git("pull", "--rebase", "--autostash", "-q", "origin", "main")
    data = build()
    write(data)
    paths = [str(OUT_JSON.relative_to(ROOT)), str(OUT_MD.relative_to(ROOT))]
    git("add", "--", *paths)
    if not git("diff", "--cached", "--name-only", "--", *paths).strip():
        return fingerprint(data)
    s = data["summary"]
    msg = (f"T78: refresh agents overview ({s['agents']} agents, {s['by_state'].get('in_progress', 0)} in progress) "
           "[overview-agent]\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    git("-c", "user.name=overview-agent", "-c", "user.email=overview-agent@users.noreply.github.com",
        "commit", "-q", "-m", msg, "--", *paths)
    for _ in range(3):  # nick's autosync pushes often; retry after a rebase
        git("pull", "--rebase", "--autostash", "-q", "origin", "main")
        r = subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "HEAD:main"], capture_output=True, text=True)
        if r.returncode == 0:
            print(time.strftime("%H:%M:%S"), "pushed overview", git("rev-parse", "--short", "HEAD").strip(), flush=True)
            return fingerprint(data)
        time.sleep(5)
    print("push failed:", r.stderr.strip()[:300], file=sys.stderr)
    return last_fp


def serve(port: int, every: int, pull: bool, write_files: bool, push_every: int = 0):
    def loop():
        last_push, last_fp = 0.0, None
        while True:
            try:
                d = refresh(pull)
                if push_every and time.time() - last_push >= push_every:
                    last_fp, last_push = publish(d, last_fp), time.time()
                elif write_files:
                    write(d)
            except Exception as e:  # keep serving the last good snapshot
                print("refresh failed:", e, file=sys.stderr, flush=True)
            time.sleep(every)
    refresh(False)
    threading.Thread(target=loop, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/overview.json"):
                with State.lock:
                    body = json.dumps(State.data, ensure_ascii=False).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body, ctype = DASHBOARD.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    print(f"overview dashboard on http://127.0.0.1:{port} (refresh every {every}s, git pull={'on' if pull else 'off'}, "
          f"push={'every %ss' % push_every if push_every else 'off'})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", action="store_true", help="print the markdown")
    ap.add_argument("--serve", type=int, metavar="PORT", help="serve the live dashboard")
    ap.add_argument("--every", type=int, default=60, help="refresh interval in seconds for --serve")
    ap.add_argument("--no-pull", action="store_true", help="--serve: do not git pull before each refresh")
    ap.add_argument("--write", action="store_true", help="--serve: also rewrite the coord files on each refresh")
    ap.add_argument("--push", type=int, metavar="SECONDS", default=0,
                    help="--serve: every SECONDS commit+push the two overview files as overview-agent if they changed")
    args = ap.parse_args()
    if args.serve:
        serve(args.serve, args.every, not args.no_pull, args.write, args.push)
        return
    d = build()
    write(d)
    if args.print:
        sys.stdout.reconfigure(encoding="utf-8")
        print(md(d))
    else:
        print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}: "
              f"{d['summary']['agents']} agents, {len(d['issues'])} board issues")


if __name__ == "__main__":
    main()
