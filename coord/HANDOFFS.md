# HANDOFFS — when a task ends: what you built, how to run it, known gaps, next step.

## T2 document extraction (Codex #2)

- Run `python3 -m src.docs.run` from the repo root. It publishes `store/docs.jsonl` and caches extraction by verified content hash in `store/docs_cache.sqlite3`. The bridge manifest selects active sources when present. ERP comparisons refresh separately from extraction.
- T3/T5/T7 can use `src.docs.extract(connection, data_root)` and `src.docs.documents(connection)`. The SQLite table is `doc_extractions`. `documents()` supplies the existing `citation.file` alias alongside the canonical `source_file`, `page`, `quote` and `confidence` evidence. `--sqlite` or `load_table()` loads JSONL into a chosen database.
- Verified 282 source documents, 202 order confirmations with line items, 84 comparison flags, and 282 cache hits on the byte-identical rerun. The OCR crop on delivery note WZ-261116-473, page 1, yields 8,000 and the goods receipt records 80,000. T3 can read the correction through `fields.handwritten_quantity` and the comparison through `mismatches`.
- Local OCR found quantities on 54 of 60 receiving scans. Six missing quantities and two unverified handwriting candidates are in `review_reasons`. The live run used Tesseract. The optional Apple helper compiled but couldn't read in this environment. The vision adapter and translation hook passed mock tests. Configure a running local model with `SOONY_VISION_MODEL` or `SOONY_LOCAL_MODEL` as needed. Setup and schema are in `src/docs/README.md`.
- All 11 T2 tests passed. Changes are ready for the lead to commit.

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
- Replayed all five actual supplier PDFs against the kickoff baseline. The ingestion cycle captured all five additions and a repeat cycle processed zero changes. Commit `0f53e76` on main surfaces the new exceptions and a recovery option in the existing dashboard detail field. The T6 React walkthrough remains open.

## T5/T7/T8 — Decisions, integrated demo and submission (Codex)

- `python3 -m src.orchestrator --demo` serves the live control room at `http://127.0.0.1:8787/live`. Use **Replay supplier drop**. `--online` polls the authenticated portal. `--once` prints the current snapshot. The API uses the T1 canonical store plus T2 document evidence.
- The browser test covered the before/after drop, evidence, a Polish draft, human-confirmed dry-run send, simulated reply and logged procurement approval. The live mail transport and optional local LLM need team configuration.
- The React build is still available at `/react`. It is a separate mock-data UI until its owner switches its API client.
- `README.md` contains local setup and architecture. The deck, walkthrough, business case and three-minute recording are under ignored `private/submission/`. Keep the recording and source-backed pitch inside the team workspace.
