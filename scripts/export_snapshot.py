#!/usr/bin/env python3
"""Export a local, private copy of the dashboard replay.

Runs the real orchestrator in replay mode on a free port, captures /api/dashboard before and after the
staged data drop, and writes private/static-replay/snapshot/{before,after}.json plus meta.json.
Run with the project venv: .venv/bin/python scripts/export_snapshot.py
"""
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "private" / "static-replay" / "snapshot"


def call(port, token, path, data=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                                          "X-Soony-User": base64.urlsafe_b64encode(b"snapshot-export").decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait_dashboard(port, token, accept, timeout=400):
    end = time.time() + timeout
    while time.time() < end:
        try:
            value = call(port, token, "/api/dashboard")
            if accept(value):
                return value
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("timed out waiting for the dashboard")


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = secrets.token_hex(32)
    proc = subprocess.Popen([sys.executable, "-m", "src.orchestrator", "--demo", "--port", str(port)], cwd=ROOT, env={**os.environ, "SOONY_BACKEND_TOKEN": token},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        before = wait_dashboard(port, token, lambda d: bool(d.get("readiness")) and "pendingDrop" in d.get("sync", {}))
        before_text = json.dumps(before, sort_keys=True)
        call(port, token, "/api/sync", b"{}")
        after = wait_dashboard(port, token, lambda d: json.dumps(d, sort_keys=True) != before_text and bool(d.get("readiness")), 120)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "before.json").write_text(json.dumps(before, indent=1))
        (OUT / "after.json").write_text(json.dumps(after, indent=1))
        (OUT / "meta.json").write_text(json.dumps({"exported": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                                   "mode": "static replay snapshot"}, indent=1))
        print("wrote", OUT)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
