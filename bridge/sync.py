#!/usr/bin/env python3
"""Soony portal bridge: syncs all files via the API into ./data, tracks sha256 changes.
Token: env SOONY_TOKEN or file ./.soony_token. Usage: python3 bridge/sync.py [--list]"""
import os, sys, json, hashlib, urllib.request, urllib.parse, pathlib, datetime
BASE = "https://start-hack-portal-cxh3crbdaef2f8gt.westeurope-01.azurewebsites.net"
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"; STATE = ROOT / "bridge" / "state.json"; LOG = ROOT / "bridge" / "changes.log"
def token():
    t = os.environ.get("SOONY_TOKEN") or (ROOT/".soony_token").read_text().strip() if (os.environ.get("SOONY_TOKEN") or (ROOT/".soony_token").exists()) else None
    if not t: sys.exit("No token: set SOONY_TOKEN or write it to .soony_token")
    return t
def get(path, tok):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=60) as r: return r.read()
def main():
    tok = token()
    files = json.loads(get("/api/v1/files", tok))["files"]
    if "--list" in sys.argv:
        for f in files: print(f["bytes"], f["path"])
        return
    old = json.loads(STATE.read_text()) if STATE.exists() else {}
    new, changes = {}, []
    for f in files:
        p = f["path"]; new[p] = f["sha256"]; dest = DATA / p
        if old.get(p) == f["sha256"] and dest.exists(): continue
        body = get("/api/v1/files/" + urllib.parse.quote(p), tok)
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(body)
        changes.append(("NEW" if p not in old else "CHANGED", p))
    for p in set(old) - set(new): changes.append(("REMOVED", p))
    STATE.write_text(json.dumps(new, indent=1))
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with LOG.open("a") as lg:
        for k, p in changes: lg.write(f"{ts} {k} {p}\n"); print(k, p)
    print(f"{len(files)} files, {len(changes)} changes")
main()
