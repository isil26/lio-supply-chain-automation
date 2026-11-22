# Team live backend

The live backend runs on Murat’s Mac. It stays up while the Mac is signed in, awake and online. The health endpoint reports the running commit as `backendCommit`. The Vercel replay remains a separate fallback.

## Interact and request changes

Use the protected live link in [the repo inbox](../../coord/INBOX.md) and sign in with your provisioned username and password. Agents can use the same sign-in to obtain a session cookie, then read `/api/dashboard` and `/api/health`. Browser actions and API calls share the same state. Get credentials through the existing private team workflow.

By default the Mac service runs the case in dry-run mode. **Process drop** applies the staged files. Under **Agents**, select a game-card supplier thread to simulate a reply and see its effect on the next action.

The operator can set `"SOONY_MAC_MAIL_MODE": "live"` in the private `config.json` and restart the LaunchAgent to use the registered team mailbox. Live mode stores operational mail in `live-mail/soony.db`, separately from the saved replay. It uses the existing private `mail-history.json` credentials and restricts recipients to the hackathon supplier domain. Supplier replies are polled read-only. The **Live supplier threads** view shows dispatch, matched replies and decisions. Set `"CHASER_AUTO_SEND": "0"` and restart to pause automatic dispatch, or remove `SOONY_MAC_MAIL_MODE` and restart to restore replay. Dock release, purchasing and other commitments still need PP-07 approval.

## Automatic portal updates

Put the existing team API token in `live-mail/portal-sync/.soony_token` in the private Mac workspace with owner-only permissions. The live worker checks the official inventory every two minutes when available. It verifies the downloaded bytes against the portal hashes and tests a new file set in a copy of the planning store. It publishes the verified snapshot, recalculates the forecast and uses the existing supplier recovery rules for newly exposed shortfalls. The existing approval gates apply.

Live Manti shows the last portal check and any applied drop. The private `portal-sync/current` pointer and snapshots survive code releases. If a drop fails verification or the portal is unavailable, the worker serves the last accepted snapshot, or the bundled case data until the first successful check. Portal inputs and the token stay on the Mac. The team replay uses its packaged snapshot.

For a request, post `murat-agent: live backend request` in [INBOX](../../coord/INBOX.md), with the behavior, affected page or API route, and code commit when available.

## Releases

`watch.py` runs under a macOS LaunchAgent from a dedicated private checkout. It fetches `origin/main` every 30 seconds and builds the latest observed SHA in a separate directory. The existing process serves while the build runs. The watcher restarts the Python service only after the build succeeds, checks the dashboard’s readiness, and restores the last ready release if startup fails. The replay files, SQLite database and recorded supplier interactions live outside each release. Keep the state directory private.

The team login gateway stays on loopback. The tunnel exposes only that gateway. A Quick Tunnel address remains stable across app releases and can change when the tunnel process restarts. The launch operator publishes the new address in the inbox if that occurs. Configure a named tunnel for stable DNS when the team has one available.

Before rolling out the named-login release to a live-mail host, set `SOONY_USERS_JSON` and `SOONY_REPLAY_KEY` in its private configuration and restart the watcher with the updated `watch.py`. The managed candidate build checks the gateway credentials before the watcher replaces the running service. An older watcher keeps serving the previous release until the live configuration is ready. The updated watcher generates a private service credential at startup and uses it for the readiness probe and gateway-to-Python traffic. Only the gateway port is for browsers. The dry-run watcher uses the five [demo accounts](../vercel/README.md#sign-in-and-audit-activity). A dedicated Vercel preview can package `deploy/vercel/package-live.sh` and set `SOONY_LIVE_UPSTREAM` to the live tunnel URL. Set `SOONY_LIVE_UPSTREAM_TOKEN` to the server-only credential that matches `SOONY_LIVE_GATEWAY_TOKEN` on the Mac. Deploy the preview separately from the replay alias.

Verify releases using `node --test deploy/backend/test-gateway.cjs`, the reply-history unit tests and the private dashboard HTTP rehearsal. Store deployment keys and logs in the private workspace.

## Verified mailbox history

Open **Verified team mailbox** in the supplier threads area or use the live site with `?mail=1`. The dedicated reader searches the team mailbox's Sent and Inbox folders in read-only mode. It imports only messages tied to a known Chaser thread and matching draft or Chaser marker, and links inbound mail to the recorded sent Message-ID. The independent history database preserves evidence and deduplicates messages across deploys. This view has no send or approve action.

The Mac enables the reader only when the operator supplies a private `mail-history.json` with the authorized Gmail user and app password next to the replay workspace. The history reader itself only reads IMAP. In live mode the operational worker also uses the mailbox for supplier SMTP and reply intake. This file and `mail-history.db` remain outside the release artifact and Git.
