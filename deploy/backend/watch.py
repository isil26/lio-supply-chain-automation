"""Serve and update the protected Soony backend from a dedicated Git clone."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import secrets
import signal
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOTS = ("src", "web", "bridge", "case-data", "config", "docs/delegations.json", "deploy/backend", "deploy/vercel")
CHECK_INTERVAL = 30
START_TIMEOUT = 240


class Host:
    def __init__(self, workspace):
        self.home = Path(workspace).resolve()
        self.checkout = self.home / "checkout"
        self.releases = self.home / "releases"
        self.releases.mkdir(parents=True, exist_ok=True)
        self.marker = self.home / "release"
        self.env = {**os.environ, **json.loads((self.home / "config.json").read_text())}
        self.live_mail = self.env.get("SOONY_MAC_MAIL_MODE") == "live"
        self.env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "CHASER_REAL_SMTP": "0",
            "SOONY_AGENTS": "1",
            "SOONY_AGENT_MODE": "simulated",
            "SOONY_LLM_PROVIDER": "none",
            "OMP_THREAD_LIMIT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.port = int(self.env.get("SOONY_BACKEND_PORT", "8787"))
        self.env["SOONY_LIVE_UPSTREAM"] = f"http://127.0.0.1:{self.port}"
        if self.live_mail and not self.env.get("SOONY_USERS_JSON"):
            raise RuntimeError("Configure private named accounts before starting the live-mail watcher.")
        self.env["SOONY_BACKEND_TOKEN"] = secrets.token_hex(32)
        self.env["SOONY_LIVE_UPSTREAM_TOKEN"] = self.env["SOONY_BACKEND_TOKEN"]
        self.env["SOONY_DEMO_ACCOUNTS"] = "0" if self.live_mail else "1"
        self.process = self.gateway = self.current = None

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.checkout, env=self.env, timeout=45)

    def stage(self, sha):
        destination = self.releases / sha
        if destination.is_dir():
            return destination
        with TemporaryDirectory(dir=self.releases) as temp:
            staging = Path(temp) / "release"
            staging.mkdir()
            archive = self.git("archive", sha, *ROOTS)
            with tarfile.open(fileobj=io.BytesIO(archive)) as files:
                files.extractall(staging, filter="data")
            # Copy only build inputs. The React public directory is excluded
            # because the live site gets its case state through the gateway.
            public = staging / "web" / "public"
            if public.is_dir():
                shutil.rmtree(public)
            web = staging / "web"
            dependency_key = hashlib.sha256((web / "package-lock.json").read_bytes()).hexdigest()
            dependencies = self.home / "web-deps" / dependency_key / "node_modules"
            if not dependencies.is_dir():
                subprocess.run(["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"], cwd=web,
                               env=self.env, check=True, timeout=180)
                dependencies.parent.mkdir(parents=True, exist_ok=True)
                (web / "node_modules").rename(dependencies)
            (web / "node_modules").symlink_to(dependencies, target_is_directory=True)
            subprocess.run(["npm", "run", "build"], cwd=web, env=self.env, check=True, timeout=150)
            staging.rename(destination)
        return destination

    @staticmethod
    def stop(process):
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def start(self, sha, release, halted):
        env = {**self.env, "SOONY_RELEASE_SHA": sha}
        config = self.home / "mail-history.json"
        args = [sys.executable, "-m", "src.orchestrator", "--data", str(release / "case-data"),
                "--port", str(self.port)]
        if self.live_mail:
            settings = json.loads(config.read_text())
            user, password = settings.get("user"), settings.get("password")
            if not user or not password:
                raise RuntimeError("The private team mail configuration is incomplete")
            env.update({
                "CHASER_REAL_SMTP": "1", "CHASER_SENDER": user, "CHASER_SMTP_USERNAME": user,
                "CHASER_SMTP_PASSWORD": password, "CHASER_SMTP_HOST": "smtp.gmail.com", "CHASER_SMTP_PORT": "587",
                "CHASER_ALLOWED_DOMAINS": "suppliers.juliansibbing.de", "CHASER_ALLOWED_RECIPIENTS": "",
                "SOONY_IMAP_USER": user, "SOONY_IMAP_PASSWORD": password, "SOONY_IMAP_HOST": "imap.gmail.com",
                "SOONY_IMAP_PORT": "993", "SOONY_MAIL_HISTORY_DB": str(self.home / "mail-history.db"),
            })
            args.extend(["--db", str(self.home / "live-mail" / "soony.db"), "--mail-history-config", str(config)])
        else:
            args.extend(["--demo", "--replay-dir", str(self.home / "replay")])
        self.process = subprocess.Popen(args, cwd=release, env=env)
        expected_mode = "live" if self.live_mail else "dry-run"
        for _ in range(START_TIMEOUT):
            if self.process.poll() is not None or halted.is_set():
                break
            try:
                probe = Request(f"http://127.0.0.1:{self.port}/api/dashboard",
                                headers={"Authorization": "Bearer " + env["SOONY_BACKEND_TOKEN"]})
                with urlopen(probe, timeout=2) as rows:
                    dashboard = json.load(rows)
                    if dashboard.get("readiness") and (dashboard.get("sync") or {}).get("mailMode") == expected_mode:
                        return
            except (URLError, TimeoutError, ValueError):
                pass
            halted.wait(1)
        self.stop(self.process)
        raise RuntimeError("candidate did not serve a ready dashboard")

    def switch(self, sha, halted):
        release = self.stage(sha)
        previous = self.current
        self.stop(self.process)
        try:
            self.start(sha, release, halted)
        except RuntimeError:
            if previous and not halted.is_set():
                self.start(previous, self.releases / previous, halted)
            raise
        self.current = sha
        self.marker.write_text(sha + "\n")
        print(f"Serving commit {sha} with {'live' if self.live_mail else 'dry-run'} supplier mail", flush=True)
        self.stop(self.gateway)
        self.gateway = subprocess.Popen(["node", "deploy/backend/gateway.cjs"], cwd=release, env=self.env)

    def watch(self, halted):
        if self.marker.is_file():
            try:
                self.switch(self.marker.read_text().strip(), halted)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                print(f"Cannot restore the previous release ({type(error).__name__}).", flush=True)
        try:
            while not halted.is_set():
                try:
                    self.git("fetch", "--no-tags", "origin", "main")
                    sha = self.git("rev-parse", "FETCH_HEAD").decode().strip()
                    running = self.process and self.process.poll() is None and self.gateway and self.gateway.poll() is None
                    if sha != self.current or not running:
                        self.switch(sha, halted)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    print(f"Release check failed ({type(error).__name__}). Retrying.", flush=True)
                halted.wait(CHECK_INTERVAL)
        finally:
            self.stop(self.gateway)
            self.stop(self.process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    args = parser.parse_args()
    halted = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: halted.set())
    Host(args.workspace).watch(halted)


if __name__ == "__main__":
    main()
