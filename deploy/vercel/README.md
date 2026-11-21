# Private Soony Vercel replay

The hosted dashboard uses the same React frontend as the local Control Room. The Python pipeline evaluates a downloaded team snapshot before and after ingesting the staged supplier files. The deployment packages those two forecast states in an encrypted server-function asset. The hosted **Process drop** button switches the signed-in session to the recalculated state. **Reset replay** restores the baseline for that session.

The hosted app uses a shared high-entropy team password, an eight-hour signed session cookie, and private, uncached API responses. Supplier sends and purchasing approvals run through the local app. Hosted evidence is limited to citations. The deployment artifact contains no raw portal files, database, or portal credentials.

Open the [hosted dashboard](https://soony-launch-control.vercel.app) and sign in with the [team password](team-password.txt) tracked in the private GitHub repository. Collaborators and their agents can read the file from their checkout.

## Refresh from a new team snapshot

Use the repository Python environment and Node 22. Keep the replay key in the team's approved private storage.

```sh
# Run from the repository root. Set these paths to the approved local inputs.
./deploy/vercel/prepare.sh "$SNAPSHOT_DIR" "$REPLAY_KEY_FILE" "$SEALED_REPLAY"
./deploy/vercel/package.sh "$SEALED_REPLAY" "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
vercel link --project soony-launch-control
vercel deploy --prebuilt --prod --skip-domain
```

The Vercel project needs two sensitive production environment variables. `SOONY_TEAM_PASSWORD_HASH` is the hexadecimal SHA-256 of the high-entropy password without a final newline. `SOONY_REPLAY_KEY` is the separately generated 32-byte key in hexadecimal. Use the same key file when encrypting the replay. Changing the key requires rebuilding the encrypted asset and invalidates existing sessions.

Promote the candidate with `vercel promote <deployment>` and check the production alias from the repo root. This integration check tests anonymous denial, sign-in, the deployed React bundle, the before/after forecasts and recovery option, session isolation, reset, and sign-out.

```sh
python3 deploy/vercel/verify.py https://soony-launch-control.vercel.app deploy/vercel/team-password.txt
```

Development against the full API continues with the [local runbook](../../docs/RUNBOOK.md).

## Art-book recording

The hosted **Behind the scenes → AI reasoning** panel reads `recordedAgentRun` from the authenticated `/api/dashboard` payload. The build takes the checked-in `docs/agent_runs/provenance/art-book-live.json` by default. Use `SOONY_AGENT_RECORDING_FILE` to select a different approved redacted manifest when running `prepare.sh`. The replay encrypts the projected fields and keeps the recording attached when the supplier drop is applied or reset. The React build contains neither the recording nor a live-agent client for this panel.

The current `summary_only` manifest shows the published aggregate usage as reported and explains the missing event evidence. For `verified_events`, supply the verified run ID, pins for the original trace or redacted export in `sources`, and unique ordered `sequence` values across `steps` and `verified_handoffs`. Operational rows use `agent`, `status`, `tool` or handoff `target`, and optional `summary`, `recorded_at`, `latency_ms`, `cost_usd`, and source `citations`. Use null for unavailable metrics. `verified_usage` represents run-attributed provider totals. Include approval details only with `approvals_verified: true`. The runtime projection ignores raw tool arguments, results, reasoning, and proposed calls.

```sh
python3 deploy/vercel/verify.py "$TEAM_REPLAY_URL" "$TEAM_PASSWORD_FILE" --recording summary_only
```

Use `--recording verified_events` after original events have been recovered, verified, and redacted.
