# HANDOFFS — when a task ends: what you built, how to run it, known gaps, next step.

## T4 — Supplier Chaser (Copilot #2)

- Built in `src/chaser/`: structured issue model, profile-derived supplier language and contact, multilingual draft templates, guardrails, SQLite thread/message/reply/action state, approval gate, dry-run/mock/SMTP outboxes, mock inbox, deterministic reply LLM, and CLI.
- Run: `python3 -m src.chaser.run --help`; tests: `python3 -m unittest src.chaser.test_chaser` (7 passing).
- Default sending is dry-run. Mock sends are available for demo. Real SMTP requires `CHASER_REAL_SMTP=1` plus `CHASER_SENDER` and SMTP environment settings.
- Pending/approved/sent state and all action records persist in `store/chaser.sqlite`.
- Handoff: T7 can call `src/chaser.run` or import `SupplierChaser`; T6 can consume thread/list/log state, but no external API wrapper was added in T4.

## T7 offline API verification for T3 and T6

- Verified against the local kickoff snapshot with a temporary database. A synthetic shipping advice replay changed the shipment quantity, produced a short shipment issue with a source citation, and refreshed the dashboard. Repeating the cycle with the same files processed zero changes.
- Start from the repo root with `CHASER_SENDER=demo@example.invalid python3 -m src.orchestrator --demo --data /path/to/team-snapshot`. Replay copies the input snapshot into its own working directory and stages shipping advice and offer files with matching names until sync. This address is for the demo transport.
- `GET /api/dashboard` returns 503 during initial processing and 200 when the snapshot is ready. `POST /api/sync` with an empty JSON object returns 202. In replay mode, poll until `sync.pendingDrop` reaches zero and the dashboard reports that the replayed drop was processed. Handle an empty approval and unquoted prices in the UI.
- Use the decision ID returned by the API. A review request persists the review status. Use the returned thread ID for send. An empty send request returns 409. A confirmed request with `{"confirm":true}` uses the simulated transport in replay mode. Post a simulated reply to `/api/threads/{id}/demo-reply` with `{"text":"..."}`.
- Remaining checks are the T6 browser walkthrough and replay with the latest private portal drops. The kickoff-only snapshot needs a staged drop for replay.
