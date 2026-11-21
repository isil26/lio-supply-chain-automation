# Private Soony Vercel replay

The hosted dashboard uses the same React frontend as the local Control Room. The Python pipeline evaluates a downloaded team snapshot before and after ingesting the staged supplier files. The deployment packages those two forecast states in an encrypted server-function asset. The hosted **Process drop** button switches the signed-in session to the recalculated state. **Reset replay** restores the baseline for that session.

The hosted app uses a shared high-entropy team password, an eight-hour signed session cookie, and private, uncached API responses. Supplier sends and purchasing approvals run through the local app. Hosted evidence is limited to citations. The deployment artifact contains no raw portal files, database, or portal credentials.

## Refresh from a new team snapshot

Use the repository Python environment and Node 22. Keep the team password file and replay key in the team's approved private storage. Never put either value in a commit, a build log, or a public channel.

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
python3 deploy/vercel/verify.py https://soony-launch-control.vercel.app "$TEAM_PASSWORD_FILE"
```

Development against the full API continues with the [local runbook](../../docs/RUNBOOK.md).
