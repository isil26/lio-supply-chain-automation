# Launch Control Room demo runbook

## Fresh-clone setup

Run from the repo root. Use Python 3.10+, SQLite 3.37+, Node.js 22 with npm, and Tesseract with English, Polish, Korean and Simplified Chinese data. Install the OCR packages for your platform.

```sh
# macOS (Homebrew)
brew install tesseract tesseract-lang
# Debian or Ubuntu
# sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-pol tesseract-ocr-kor tesseract-ocr-chi-sim
tesseract --list-langs

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run build
```

For a fresh checkout, initialize the local mirror from the [supplied snapshot](../case-data/) with `cp -R case-data data`. Run this when `data/` does not yet exist. For live portal updates, provision `SOONY_TOKEN` through the team’s private channel and sync while the portal is reachable. Keep the mirror, OCR cache, snapshots and recording inside the private team workspace. The portal download does not require mailbox credentials.

```sh
python3 bridge/sync.py  # Only when refreshing inputs from the portal
```

The replay needs the full mirror, including the downloaded shipping advices and express offer. Keep `store/docs_cache.sqlite3` available on the demo laptop to reuse OCR results.

## Demo day

At least 30 minutes before the slot, prepare the offline snapshot and run the preflight. The snapshot JSON and database stay in `private/demo-cache/`.

```sh
source .venv/bin/activate
export CHASER_REAL_SMTP=0 SOONY_LLM_PROVIDER=none
unset SOONY_IMAP_HOST SOONY_LOCAL_MODEL SOONY_VISION_MODEL
mkdir -p private/demo-cache
python3 -m src.orchestrator --once --db private/demo-cache/soony.db > private/demo-cache/dashboard.json
scripts/demo_check.sh
```

The check times each step and uses a temporary workspace and loopback port. The same check can be run directly with `python3 -m unittest discover -s tests -p test_e2e.py -v`. `DEMO_DATA_DIR` selects an alternate private mirror, and `DEMO_TIMEOUT_SECONDS` sets the wait limit per dashboard stage (240 seconds by default).

Once preflight passes, launch a separate replay for the stage and leave it running at the baseline. Each `--demo` invocation starts with a fresh database.

```sh
python3 -m src.orchestrator --demo --port 8787
```

In another terminal or browser, wait for the dashboard before the session begins. On macOS, use the following commands.

```sh
curl -fsS --retry 120 --retry-connrefused --retry-delay 2 --retry-max-time 240 \
  -o /dev/null http://127.0.0.1:8787/api/dashboard
open http://127.0.0.1:8787/
```

1. Open the readiness view and point out the STD and CE targets. Open the evidence for the art book receipt correction and the statue hold.
2. Click **Process drop** once on stage. In the standalone view, use **Replay supplier drop**. Wait for **Replayed portal drop processed**, then point out the changed game-card risk and the art-book recovery option. The post-drop gaps are listed in [NUMBERS.md](NUMBERS.md).
3. Approve the art-book hold and quote request. Open a current supplier draft and confirm the dry-run send. Show **Awaiting reply** and the activity entry for demo transport. Approval queues quote preparation under the procurement policy.
4. Stop a rehearsal with Ctrl-C and start a new `--demo` process before the next walkthrough so the drop starts staged again.

## Fallback ladder

1. **Cached snapshot.** Open the prewarmed local dashboard at `http://127.0.0.1:8788/`. Start the standby before the slot with `python3 -m src.orchestrator --db private/demo-cache/soony.db --port 8788` and the same dry-run environment. The standby uses the cached `data/` mirror; keep the exported dashboard JSON as a last copy of the figures and evidence references.
2. **Offline replay.** Use a fresh `--demo` instance on the cached mirror for the staged drop and supplier workflow. If the React build is unavailable, open `http://127.0.0.1:8787/live` for the standalone control room.
3. **Recorded video.** Open `private/submission/Soony Launch Control Room Demo.mp4` in a local player. Queue it before the slot and check audio with the presentation output.

## Failure modes

| Symptom | Fix |
| --- | --- |
| Portal down or Wi-Fi unavailable | Keep the last complete mirror and switch to offline replay. If the input mirror is incomplete, use the cached standby or the recording. |
| OCR cold start, dashboard returns HTTP 503 | Keep the process running while the first pass builds the snapshot. Verify `tesseract --list-langs`, warm the cache with `--once`, then start replay before stage time. For a slower preflight use `DEMO_TIMEOUT_SECONDS=480 scripts/demo_check.sh`. |
| Temporary SQLite lock at startup | Give the replay one background refresh interval (45 seconds by default) to retry. Use the prewarmed standby if the page stays unavailable. |
| Port busy (`Address already in use`) | Start replay with another loopback port such as `--port 8789`. Update the browser and curl URLs to match. The smoke check selects an ephemeral port. |
| Token missing or rejected | Use the existing mirror for offline replay. For a portal update, provision a fresh team token through the private channel and rerun `python3 bridge/sync.py`. |
| Drop already applied or missing | Start a fresh `--demo` process. If preflight still reports zero staged files, restore the complete cached mirror with the held-back supplier documents. |
| Preflight reports `Operation not permitted` on `bind` | Run it from a regular terminal that allows loopback listeners. |
