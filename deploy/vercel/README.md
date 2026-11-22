# Private Soony Vercel replay

Judges use the `test` account on [Manti Live](https://soony-manti-live.vercel.app/). The `soony-vercel.yml` publishing workflow for the separate hosted replay is disabled.

The replay uses the same React frontend as the local Control Room. The Python pipeline evaluates a downloaded team snapshot before and after ingesting the staged supplier files. The deployment packages those two forecast states in an encrypted server-function asset. The hosted **Process drop** button switches the signed-in session to the recalculated state. **Reset replay** restores the baseline for that session.

## Sign in and audit activity

The demo accounts are `isil`, `murat`, `nick`, `leo`, and `gulsah`. Each uses `12345`. Each person or agent should select their own account. The team credentials work in the local `--demo` and on the Google Cloud hackathon dashboard. Anyone with the demo password can choose any of the five names.

The gateway sets an eight-hour signed, HTTP-only session cookie. Sign out from the dashboard to clear it. Server-side actions emit JSON records tagged `control_room.activity` in the gateway stdout or Vercel function logs. Filter by `user` for an account's actions. Each record has a UTC timestamp, route and HTTP status. Practice-mode clicks that stay in the browser do not create server events.

For a private live deployment, run `python3 deploy/vercel/account.py "Account Name"` in a terminal for each operator. Combine the resulting entries into one JSON object and set it as the private `SOONY_USERS_JSON` environment variable on each gateway. Where an approval rule names a signer, provision that exact account name. Setting the variable replaces the demo list. Removing an account or replacing its verifier invalidates its sessions once the gateway loads the new configuration.

For a production front gateway that already authenticates with a shared team password, keep its existing password and session key. On the receiving VM only, set `SOONY_SHARED_EDGE_ACCOUNT` to a dedicated, non-signer account in `SOONY_USERS_JSON`. Only requests authenticated by the front gateway’s server credential and carrying no individual identity receive this account. The activity log identifies them as a shared team login. Rehearsal and individual account sign-ins keep their existing attribution.

## Package a separate replay from a new snapshot

Use the repository Python environment and Node 22. Keep the replay key in the team's approved private storage.

```sh
# Run from the repository root. Set these paths to the approved local inputs.
./deploy/vercel/prepare.sh "$SNAPSHOT_DIR" "$REPLAY_KEY_FILE" "$SEALED_REPLAY"
./deploy/vercel/package.sh "$SEALED_REPLAY" "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
vercel link --project "$REPLAY_PROJECT"
vercel deploy --prebuilt --prod --skip-domain
```

Set `SOONY_REPLAY_KEY` to the separately generated 32-byte key in hexadecimal. Use the same key file when encrypting the replay. Changing the key requires rebuilding the encrypted asset and invalidates existing sessions. For a deployment with a live upstream, configure individual accounts on the front and backend gateways. Set `SOONY_DEMO_ACCOUNTS=1` on a live relay only when its upstream runs a dry-run rehearsal.

Promote the candidate with `vercel promote <deployment>` and check the production alias from the repo root. This integration check tests anonymous denial, sign-in, the deployed React bundle, the before/after forecasts and recovery option, session isolation, reset, and sign-out.

```sh
python3 deploy/vercel/verify.py "$TEAM_REPLAY_URL" isil "$DEMO_PASSWORD_FILE"
```

Development against the full API continues with the [local runbook](../../docs/RUNBOOK.md).

## Art-book recording

The hosted **Behind the scenes → AI reasoning** panel reads `recordedAgentRun` from the authenticated `/api/dashboard` payload. The build takes the checked-in `docs/agent_runs/provenance/art-book-live.json` by default. Use `SOONY_AGENT_RECORDING_FILE` to select a different approved redacted manifest when running `prepare.sh`. The replay encrypts the projected fields and keeps the recording attached when the supplier drop is applied or reset. The React build contains neither the recording nor a live-agent client for this panel.

The current `summary_only` manifest shows the published aggregate usage as reported and explains the missing event evidence. For `verified_events`, supply the verified run ID, pins for the original trace or redacted export in `sources`, and unique ordered `sequence` values across `steps` and `verified_handoffs`. Operational rows use `agent`, `status`, `tool` or handoff `target`, and optional `summary`, `recorded_at`, `latency_ms`, `cost_usd`, and source `citations`. Use null for unavailable metrics. `verified_usage` represents run-attributed provider totals. Include approval details only with `approvals_verified: true`. The runtime projection ignores raw tool arguments, results, reasoning, and proposed calls.

```sh
python3 deploy/vercel/verify.py "$TEAM_REPLAY_URL" "$TEAM_USERNAME" "$TEAM_PASSWORD_FILE" --recording summary_only
```

Use `--recording verified_events` after original events have been recovered, verified, and redacted.

## Upload case data

The team deployment uses its existing live gateway settings for uploads. Both the planning service and the Vercel relay must run a release with the upload route. The route uses the dashboard sign-in to isolate each visitor's data.

To enable uploads on a protected replay deployment, set `SOONY_UPLOAD_UPSTREAM` to the upload gateway's HTTPS address and `SOONY_UPLOAD_UPSTREAM_TOKEN` to its gateway token.

Choose one case file or a ZIP in **Upload case data**. ZIPs can wrap the existing `soony/` and `suppliers/` folders in a parent folder. Use a recognized export name for a standalone update, such as `goods_receipts_update.csv`. Files can be up to 64 MB. The app reports how many files it imported and shows the recalculated forecast. Successful uploads build on the current upload scenario. **Return to launch dashboard** ends the scenario.

Uploads run the normal ingest, OCR, readiness, and action preparation pipeline in a private dry-run workspace. Invalid updates preserve the previous accepted result. The scenario is temporary and expires after an hour of inactivity.
