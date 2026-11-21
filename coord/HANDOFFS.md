# HANDOFFS — when a task ends: what you built, how to run it, known gaps, next step.

## T72 — Release Gate (copilot-gate)

- Added `src/decide/release_gate.py`: pure cited GO/HOLD/HUMAN evaluation from readiness, extracted documents and supplier rows; includes quality, artwork, embedded magnet, conditional Pune authority, Incoterm and usable-stock rules plus per-edition packable units.
- Added `GET /api/release-gate`, read-only `release_gate_status(part_id?)`, CLI `python3 -m src.decide.release_gate`, focused tests and `docs/RELEASE_GATE.md`.
- Validation: `python3 -m unittest -v tests.test_release_gate tests.test_agents_tools` — 5 passed. Real-store CLI smoke was blocked by the non-interactive permission boundary because `store/soony.db` access required approval.

## T47d — Planner option IDs, summary and chaser handoff (copilot-planner)

- Added `list_options` and made `breakeven` report valid IDs when given an invalid one; Planner prompts now require copying real IDs.
- Agent runs produce a deterministic summary from tool results, run numeric grounding, force a Planner-to-Chaser handoff, persist one pending draft approval, and attribute model cost to tool rows.
- Validation: `python3 -m unittest tests.test_agents_team tests.test_agents_tools tests.test_agents_runtime tests.test_agents_loop` — 15 passed. Live validation was attempted but denied by the non-interactive permission boundary; no live cost/result is claimed.

## T41b — Agent trace projection and German notice guard (copilot-loop2)
- `/api/agents/trace` now exposes UI-ready `steps` plus `approvals_pending`, while retaining the raw trace for compatibility. Each step includes agent, tool, args/result summaries, reason, cost, latency, citations and status. `/api/agents/runs` exposes event summary text, step count, harness result and total run cost.
- The worker snapshots only rows created for each run, then normalizes trace and pending approval state. The German-notice fixture under `tests/fixtures/unseen_german_notice.txt` gives the scenario a real reviewable file; empty claims are ignored rather than turned into false citation violations.
- Validation: `tests.test_agents_loop` and `tests.test_agents_harness` pass (13 tests), and `scripts/demo_check.sh` passes. The live port 8794 smoke was attempted but loopback server startup was denied by the non-interactive tool sandbox, so no live result or live cost is claimed.

## T69 — Supplier claims and money on the table (copilot-claims)

- Added `src/decide/claims.py` for deterministic late-delivery damages, commenced-week caps, Hwaseong claim deadlines, price drift, Boise freight/DDP exposure, pins/cancellation leakage and the Hwaseong LTA renewal deadline.
- Added `docs/CLAIMS.md` with supplier totals and per-line source evidence. CLI: `python3 -m src.decide.claims`.
- Added `tests/test_claims.py`; `python3 -m unittest tests.test_claims -v` passes 4 tests.
- Key totals: Hwaseong USD 274,912; Dongguan CNY 7,894.95; PackRight CNY 6,684.58. PackRight fixed-price potential drift is CNY 347,627.10; Boise revision-allowed drift exposure is USD 531,091; freight/duties are unquantified; leakage is 78,000 pins plus 32,500 cancelled units.
- Known gaps: invoices and 12-month claim notices are absent, and no FX conversion or legal force-majeure/set-off analysis is asserted.

## T67 — Event taxonomy + materiality triage (copilot-triage)

- Added `src/agents/triage_policy.py`: deterministic category/materiality pass, 35-65 ambiguous LLM second pass with quote validation, and `event_decisions` SQLite persistence. Dashboard read helper: `dashboard_decisions(db_path)`.
- Added 12 clearly synthetic labelled events under `tests/agent_eval/events/` and `tests/test_triage_policy.py`.
- Nick integration: import `classify_event`, pass the event and truth summary before starting the expensive team, then use `dashboard_decisions()` for the dashboard. Synthetic and live modes remain separate; no synthetic data is written under `data/`.
- Validation: `python3 -m unittest tests.test_triage_policy -v` — 4 tests pass. `python3 -m src.agents.triage_policy --eval` — 12/12 decision/category eval, cost `$0.0000` for deterministic synthetic run.

## T47c — Replay harness calibration (copilot-fix3)

- Calibrated `stop_check` to count only tool-call rows, allow 45 tool calls, retain repeated-signature and Pending Plan B oscillation checks, and identify rule evidence. Evaluator live/replay runs now delete prior `agent_trace` rows from the isolated database.
- Normalized repository-relative/basename citations and compact `5.9k`/`5900.0` numeric grounding. Replay evidence now includes the wanted file, wanted quote and available evidence.
- Validation: `python3 -m unittest tests.test_agents_harness` (10 tests pass); `SOONY_AGENT_MODE=replay python3 tests/agent_eval/run_eval.py --live --runs 1` passes 6/6 replay scenarios at $0.00. No live API run was made.

## T47b — Live eval failure fixes (copilot-fix2)

- Added per-run tool-call deduplication with cached results excluded from repeat traces, bounded triage rounds to two, and quote-backed claims from tool results.
- Briefer validation now runs numeric grounding and PP-07 policy checks and derives price/signer only from `propose_option`/`escalate_to_human` payloads.
- Validation: `python3 -m unittest tests.test_agents_runtime tests.test_agents_team tests.test_agents_harness tests.test_agents_roles2` (23 passed). Direct fake team traces pass stop/citation checks. The cached pre-fix live report remains the only live evidence; no new live pass rate is claimed.

## T41 — Autonomy loop and agent APIs (copilot-loop)

- `src/agents/loop.py` persists bounded background runs in `agent_runs`, deduplicates event hashes, captures per-run traces and harness results, supports timer events, replay adapters, and the stop switch.
- The orchestrator submits drop/reply events only when `SOONY_AGENTS=1`; `GET /api/agents/runs`, `GET /api/agents/trace?run=...`, `POST /api/agents/run`, and `POST /api/agents/stop` are available. Dashboard activity includes the agent trace projection.
- Validation: `python3 -m unittest -q tests.test_agents_loop tests.test_agents_team tests.test_agents_runtime` (10 passed) and `PATH=$PWD/.venv/bin:$PATH bash scripts/demo_check.sh` (passed).

## T47 — Live agent wiring (copilot-wire)

- Role prompts load `knowledge.load_pack(role)` and require the pack's strict JSON schemas; verifier searches distinctive identifiers and opens matching documents.
- Harness evaluation is attached to every team event. Violations mark proposals and pending approvals `blocked by harness`; specialist delegation and supplier drafts stop after one idempotent action.
- Tool descriptions now document purpose, guardrails, and argument examples. Evaluator traces are isolated per live run.
- Focused validation: 23 agent tests pass. Existing art-book live evidence passes twice at $0.057892; quality-hold and German-notice live runs were not completed after the cumulative live attempt reached $1.694971. Do not claim those pass rates.

## T44 — Agent trace panel (copilot-trace)

- Added `web/src/agents/AgentTrace.tsx`, scoped `agents.css`, typed trace contracts, and a recorded fixture under `web/public/snapshot/agent_run.json`.
- The panel shows the five-role handoff graph, tool timeline, citation chips opening the existing evidence modal, per-step cost/latency, harness status, pending approvals, and live/replay/offline status.
- Added DashboardApi methods for `/api/agents/runs`, `/api/agents/trace`, `/api/agents/run`, and `/api/agents/stop`; static and mock adapters remain safe until the backend is available.
- Export latest redacted run with `python3 scripts/export_agent_run.py`.
- Validation: `npm --prefix web run build` and `VITE_STATIC=1 npm --prefix web run build` pass.

## T39 — Agent tool layer (copilot-tools)

- Added `src/agents/tools.py`: a closed registry of thin adapters over readiness, sensitivity, supplier reliability, cited document search, source comparison, expedite analysis, chaser draft/send/parse, pending options, PP-07 escalation, and review requests.
- Every handler returns `value` plus normalized `citations`; side-effecting tools are marked `needs_approval`, and `send_email` is hard-restricted to dry-run.
- `python3 -m src.agents.tools --list` prints JSON names/schemas. `python3 -m unittest tests.test_agents_tools` passes (3 tests).

## T63 - Document Reader (copilot-reader)

- Added `src/agents/reader.py`: `read_document(path, supplier_id=None)` returns the coverage/language/kind/facts/review contract, parses text/PDFs deterministically, and uses quote-validated text or vision JSON as a provisional fallback.
- Image prompts use OpenAI-compatible `image_url` base64 input; handwritten claims must retain a verbatim transcription quote and are never forecast-safe before approval.
- Review state persists in SQLite `doc_review`; call `DocumentReader(...).approve(file)` after human review. `reader_tool()` is compatible with the runtime tool registry.
- CLI: `python3 -m src.agents.reader PATH`; focused validation: `python3 -m unittest tests.test_agents_reader -v` (4 passed).
- No live model call was made; live cost `$0`. Register the tool in `src/agents/team.py`/role whitelists before enabling it in the runtime.

## T63 reader follow-up — copilot-reader

- `DocumentReader` now constructs the shared `LLMClient` when no client is injected, so the CLI honors configured model settings; configured images always take the vision path.
- Vision instructions explicitly inspect strike-through/handwriting and preserve `printed_quantity`, `handwritten_quantity`, `handwriting_present`, and the evidence quote; handwritten quantities retain `read as X, uncertain` wording and remain review-required.
- Offline validation: `python3 -m unittest tests.test_agents_reader -v` — 7 passed. The optional live smoke test reached `gpt-4.1-mini` and returned art-book printed 80,000 / handwritten 8,000 / review required; logged cost was unavailable (0.0 in the client log).
- Requested Karton notice and second plain-scan live invocations were attempted but the non-interactive environment denied network approval; no result is claimed for either.

## T38b — Live multi-agent path (copilot-live)

- Fixed live auth fallback across `SOONY_LLM_KEY`, `SOONY_LLM_API_KEY`, and `OPENAI_API_KEY`; OpenAI/Anthropic tool-call history now preserves parallel call IDs and tool-result protocol, with 30-second timeouts and one retry for 429/5xx.
- Added gpt-4.1-mini usage-price accounting, trace/cassette secret redaction, and hard `NO LIVE MODEL RAN` CLI failure when the live path errors. The only scripted path is `--fake`.
- Recorded/replayed the `art_book` live trace with real tool calls. Export: `docs/agent_runs/art_book_live.json` and `docs/agent_runs/README.md`.
- Art-book live cost: `$0.057892`; 130,117 input and 3,653 output tokens across the final run. Two live passes were used; stopped after the final pass exceeded the ~100k preferred input threshold.
- Offline validation passes the supplier-language draft and approval state. Observed hallucinated numeric values: 0.
- Validation: `python3 -m unittest tests.test_agents_runtime tests.test_agents_team tests.test_agents_tools` (11 tests pass); `python3 -m src.agents.team --scenario art_book --fake` passes.

## T46 — Guard harness and golden evals (copilot-harness)

- Added `src/agents/harness.py` with pure-Python numeric grounding, citation, PP-07 policy, stop/oscillation and supplier-language guards; `evaluate()` returns an aggregate report.
- Added six golden scenarios under `tests/agent_eval/scenarios/` and `python3 tests/agent_eval/run_eval.py --fake` for the markdown report at `docs/AGENT_EVAL.md`. Live mode is available with `SOONY_AGENT_MODE=live` or `--live`, capped at five runs.
- Added `tests/test_agents_harness.py`; all 7 focused tests pass. Fake golden eval passes all 6 scenarios, including proving that unapproved send and hallucinated-number cases are caught.

## T40 — Multi-agent team (copilot-agents)

- Added `src/agents/team.py` and `src/agents/prompts.py`: Triage delegates at most 3 rounds to Analyst, Verifier, Planner and Chaser; each specialist has a closed role whitelist and the existing runtime/schema gates remain enforced.
- The Verifier rejects claims without matching source quotes. Planner options persist as pending approval; Chaser can draft and escalate but `send_email` remains approval-gated and dry-run-only.
- Run fake scenarios with `python3 -m src.agents.team --scenario art_book --fake`, or replace `--fake` with live HTTP/Anthropic configuration.
- Verified 13 focused agent/runtime/tool/supplier tests; all three fake CLI scenarios run. Live key validation was not available.

## T33 — Shared LLM client (copilot-llm)

- Added `src/llm/client.py` for Ollama and OpenAI-compatible chat-completions endpoints, legacy `SOONY_LOCAL_*` compatibility, JSON-schema validation, source-quote validation, SHA-256 disk cache, strict timeout, per-cycle budget and `store/llm_log.jsonl` cost/latency events.
- Wired `src/docs/providers.py` and `src/chaser/llm.py` to the shared client. Model failures and missing configuration fall back to deterministic behavior instead of crashing a cycle.
- Added `python3 -m src.llm.check` for a real PDF extraction ping. It reports no live model unless `SOONY_LLM_MODEL` or `SOONY_LOCAL_MODEL` is configured.
- Verified 36 focused LLM, chaser and document-provider tests. Live check was run and correctly returned `FAIL - SOONY_LLM_MODEL/SOONY_LOCAL_MODEL is not configured`.

## T34 — State hardening (copilot-state)

- SQLite ingest and chaser connections use a 30-second busy timeout; chaser connections enable WAL and foreign keys.
- Portal sync runs before `Loop.cycle()` acquires the cycle lock, so long sync/OCR work does not block dashboard reads or short HTTP handlers.
- `GET /api/health` reports last cycle time, cycle duration, lock wait, errors and the existing `dataHealth` badge payload.
- Verified 7/7 drop regressions, 13/13 chaser tests and 4/4 orchestrator drop/health tests. The broader source suite passed 54 tests and has one unrelated Ollama mock error in `docs.test_docs.PipelineTests.test_loopback_adapter_decodes_the_ollama_chat_response`.

## T38 — Multi-agent runtime (copilot-runtime)

- Added `src/agents/` standard-library runtime: `Agent` ReAct loop, schema-validated closed tools, max-step/cost/wall-clock budgets, malformed-response retry, and human approval rows for gated tools.
- Added Anthropic and OpenAI-compatible HTTP adapters, `FakeLLM`, SHA-256 cassette record/replay, SQLite `agent_trace` plus dashboard-compatible activity events, and `Team` blackboard/delegation mailbox.
- Run `python3 -m unittest tests.test_agents_runtime`; 3 tests pass. Tool-layer integration remains with the owner of `src/agents/tools.py`.

## T16 — Chaser scoring and escalation (copilot-chaser)

- Reply parsing now returns commitment strength and score: `none` (0), `date_only` (1), `date_and_quantity` (2), and `document_or_booking_reference` (3), plus `what_to_ask_next`.
- Added `r1_document` drafts in English, Korean, Chinese and Polish that request per-lot quantity and packing-list or booking evidence.
- `validate_draft()` blocks binding commitments and disclosure of deadline slack, walkaway alternatives, maximum premium or cost per missing copy; `send()` rechecks the persisted draft.
- R0-R4 next-step decisions persist in SQLite with timestamps and action log entries.
- Run `python3 -m unittest src.chaser.test_chaser`; all 12 chaser tests pass.

## T10 — Vercel static replay (copilot-ui)

- The React API client now uses static replay when `VITE_STATIC=1`, `?static=1`, or `?mock=1`, and automatically falls back to static snapshots when `/api/dashboard` is unreachable.
- Static replay loads `/snapshot/before.json`, `/snapshot/after.json` and `/snapshot/meta.json`, with `web/src/mock/dashboard.json` fallback until exported snapshots exist. State persists in localStorage across approvals, reviews, sends and replies.
- **Release data drop** swaps to the after snapshot. The thread workflow supports approve-and-dry-run send and demo reply. The evidence modal shows file/page/quote only in static mode. **Reset demo** restores the baseline.
- Live HTTP mode remains the default with no `VITE_STATIC` flag or static query parameter.
- Verified: `cd web && VITE_STATIC=1 npm run build` passes.

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

- On the combined integration commit, a fresh local replay with Tesseract English and no prebuilt OCR cache still showed both shipment alerts. The offer parsed, but a missing `handwritten_quantity` on the art-book receipt kept its stock at the recorded balance. The decision engine therefore omitted the recovery option. T9 has the repro in the inbox.

- On main at `7c7a7f1`, the T9 OCR fallback and the T10 React client pass together. A fresh replay and a replay seeded with a pre-fix OCR cache both produce the art-book option. Build React, start `python3 -m src.orchestrator --demo` with the team snapshot, open the default route, then click **Process drop**. The **Secure art book stock** card appears with the server price.

## T5/T7/T8 — Decisions, integrated demo and submission (Codex)

- `python3 -m src.orchestrator --demo` serves the live control room at `http://127.0.0.1:8787/live`. Use **Replay supplier drop**. `--online` polls the authenticated portal. `--once` prints the current snapshot. The API uses the T1 canonical store plus T2 document evidence.
- The browser test covered the before/after drop, evidence, a Polish draft, human-confirmed dry-run send, simulated reply and logged procurement approval. The live mail transport and optional local LLM need team configuration.
- The React build is still available at `/react`. It is a separate mock-data UI until its owner switches its API client.
- `README.md` contains local setup and architecture. The deck, walkthrough, business case and three-minute recording are under ignored `private/submission/`. Keep the recording and source-backed pitch inside the team workspace.

## T10 — Live React control room (Copilot #3)

- Replaced `web/src/api.ts` mock-only client with same-origin live HTTP calls for dashboard, source evidence, sync, decisions, and supplier threads. `?mock=1` is the only mock fallback.
- Built a responsive hero screen in `web/src/main.tsx`: countdown, P(on-time) readiness cards with p10/p50/p90 range bars, ranked SAP-vs-reality risks, source evidence modal, live activity, supplier draft/send states, PP-07 approval card, and data-drop sync.
- Vite proxies `/api` to `127.0.0.1:8787`; `npm --prefix web run build` passes.
- T7 handoff: React is still served at `/react` and HTML at `/live`. Request is in `coord/INBOX.md` to make React `/` and retain `/live`.

## T8 pitch deck (copilot-deck)

- Created `docs/deck/index.html`: six self-contained 16:9 slides, dark design system, keyboard arrows, hash navigation, inline SVG architecture diagram, print-to-PDF CSS, and no external assets or fonts.
- Created `docs/deck/SPEAKER_NOTES.md` for a timed 3-minute pitch: 0:30 problem, 1:45 live demo, 0:30 architecture, 0:15 business.
- Created `docs/deck/README.md` with browser presentation and PDF export steps.
- Source constraints: pitch figures come from `docs/NUMBERS.md`; cost-per-missing-copy and pricing are visibly marked as placeholders.
- Presenter should open `docs/deck/index.html` in Chromium and export to a 16in x 9in PDF before submission.

## T9 technical depth (codex-truth)

- Optional Ollama extraction uses `SOONY_LLM_MODEL` for notice text and `SOONY_LLM_VISION_MODEL` for receiving crops. `SOONY_LLM_URL` overrides the default loopback endpoint. `SOONY_LLM_PROVIDER=none` selects deterministic extraction. The text quote must match independent OCR or the PDF text layer. Vision must match both the part and the independent handwriting-cell OCR. Model-supplied transcription never provides validation evidence.
- `GET /api/dashboard` returns OCR, model and validation records in `activity`, including accepted and rejected candidates. Event citations open the original page in the standalone view. Cached traces keep their original execution times. Both model adapters were exercised with test responses on real source documents. A live Ollama model was unavailable in this workspace.
- The Pune PPAP option and `blockedApprovals` show the exact PP-07 §5 clause and §6 exception route. Dr. Maren Vogt can approve a documented exception. Daniel Okafor still provides written Supplier Quality release once PPAP succeeds. Approval returns HTTP 409 while the release is blocked. Requesting review preserves the block. The component gap exposes up to 3,400 CE copies, or €117,300 at finished-goods standard cost. The missed-copy financial cost is pending confirmation.
- The 282-document replay had zero extraction errors and zero generic receipt-scan issues. Multi-line receipt matching, the narrow quantity OCR crop, and the art-book correction resolve the three false reports. The art-book adjustment remains a critical handwriting issue. The correction also works with English-only Tesseract and the pipeline invalidates older receiving caches.
- Refresh locally with `python3 -m src.orchestrator --once`. Then run `python3 -m src.orchestrator --numbers` to print the Markdown report from the evaluated SQLite store. `--db` selects a different evaluated store. The replay preserved the frozen forecast and €12,390 art-book materials estimate. The report counts eight Incoterm conflict lines across six POs.
- Verified with `python3 -m unittest discover -s src` (34 tests) and the private snapshot.

## T11 — Readiness sensitivity (codex-sens)

Run `python3 -m src.truth.sensitivity` in the project virtual environment. Use `--add COMPONENT=UNITS` for custom stock cases. The CLI reads the existing store and prints calibrated lag, baseline, first-stop criticality and paired one-day and Plan B deltas. The 500-trial run on the live snapshot took under a second.

Pass `shipment_days`, `supplier_days`, `add_units`, `release_shipments` or `shipment_earliest` in the counterfactual changes dict. With matching supplier profiles the empty changes dict reproduces the report baseline. PO lateness is an end-to-end proxy for residual handling lag, and stock scenarios assume usable units at first shift. The dock rescue includes a conditional early arrival for comparison with the scheduled ETA. Six T11 tests and 40 repository tests passed.

## T12 — Demo hardening (codex-e2e)

- `scripts/demo_check.sh` starts offline replay on a free loopback port in a disposable workspace and runs `tests/test_e2e.py` with unittest. It times dashboard readiness, the staged drop, the NUMBERS.md assertions, approval and dry-run send. No application wiring is needed.
- `docs/RUNBOOK.md` covers setup, the stage sequence, the cached dashboard, offline replay and the local recording.
- Real data passed all assertions through the in-process HTTP handler, with SQLite initialized before polling. Baseline took 95.71 seconds and the drop 0.94 seconds. The sandbox denied loopback bind, so run the shell preflight from the demo laptop terminal. The startup SQLite race and bind restriction are both recorded in the inbox for nick.

## T7 standalone blocked approval controls (murat-agent)

- On `/live`, select the blocked PPAP decision. The release stays blocked, and Request review records the escalation without releasing stock.
- Verified persistent review and the separate art-book quote action in a disposable demo replay. The integrated controls retain the T9 implementation and add explicit feedback after the blocked review request.

## T7 replay startup and dashboard consistency (murat-agent)

- SQLite and WAL initialize before the HTTP listener and replay worker start. A single dashboard query reads truth, options, the drop banner and sync status from one SQLite snapshot.
- T12's full loopback smoke test passed against a disposable replay in 32 seconds. It checked the data drop, decision persistence and simulated supplier transport. A separate regression test covers a drop committing mid-response.

## T19-Vercel — Private Vercel supplier-drop replay (codex-hosted)

- Production https://soony-launch-control.vercel.app serves protected deployment `dpl_G89s2TVbcpAKcqFxPXcTYJvs7eCL`. Automated HTTPS checks passed for anonymous API denial, authenticated forecast and shortfall changes, the art-book recovery option, independent sessions, reset, and sign-out.
- The hosted control switches between two states calculated by the local pipeline from the private team snapshot. The download was cross-checked against the portal inventory before release. Get the password through the private team channel or the ignored access file on the shared workspace. Never copy credentials into coordination files.
- [Deployment and refresh instructions](../deploy/vercel/README.md). Use the local full API for portal sync, outbound mail, approval workflows, and any source files.
- The sample replay uses the synthetic fixture. The separate local exporter writes under ignored `private/static-replay/`, outside `web/public`. The hosted artifact only contains a sealed, server-side payload.
- Password location update. Collaborators and their agents can now use the [tracked Vercel team password](../deploy/vercel/team-password.txt) from the private GitHub repository in their clones and worktrees.

## T14 — Surprise-drop robustness (codex-drops)

- [Report and proposed diff](../docs/DROP_ROBUSTNESS.md). Run `python -m unittest discover -s tests/drops -v` for seven fast regressions. Run `PYTHONPATH=. python tests/drops/audit_drops.py` for the 20 diagnostic probes.
- Highest-impact failures were cancelled inbound surviving a stale tracker, same-date stock copies double-counting a lot, and document extraction losing new facts without a visible warning. The source owner received an exact proposal in INBOX.

## T21 — Default forecast consistency (codex-consistency)

- Tested `489d0cc` on the complete private snapshot `2026-11-21_1436`. The offline dashboard matches the published post-drop edition targets, P10/P50/P90, target probabilities, trial count and 20:00 CET cutoff. The default CE median is 62,550 and P90 is 64,350. The 66,100 CE median belongs to the historical supplier-delay sensitivity scenario.
- Run the drift check using the snapshot and command in [NUMBERS.md](../docs/NUMBERS.md#forecast-drift-check). It passed with a fresh database and rejected both a one-copy CE median drift and the kickoff input fingerprint. All six sensitivity tests passed.
- Any future change to the default forecast should refresh the dashboard, published figures and presentation from the same snapshot and model. The sensitivity ranges can differ under their own assumptions.
## T15/T17 — Supplier reliability and expedite (codex-decide)

- Create `SupplierReliability(con, before=forecast_start)` per readiness snapshot. Use `profile(supplier)` for cited PO evidence and low-data status, `discounted_eta(supplier, promised_eta, deadline=deadline)` for p50/p90 and the deadline probability, and `update(supplier, observed_on_time)` once per verified outcome. Updates live in the model instance. Replay deduplicated outcomes newer than the calibrated history from persistent chaser state when rebuilding.
- Call `choose(options, loss_per_copy, q_missing, truth=truth, edition=edition_id, lag_profiles=profiles)` with wait first and the same affected copies and readiness event for every option. Provide `changes` for paired readiness replay or an explicit `p_on_time` assumption. Omitting `edition` selects joint readiness. `loss_per_copy=None` returns thresholds and the illustrative grid with status `needs Dr. Vogt`. The art-book CLI reads the materials estimate and quantity from NUMBERS.md. Freight and dock costs are still pending.
- Seven decision tests, 46 source tests and seven drop tests passed. Live SQLite calibration and `python3 -m src.decide.expedite` passed with the repo venv. The socket demo test hit the sandbox loopback restriction.

## T32 — Surprise drops and decision analysis (codex-fix)

- ERP cancellations exclude inbound and retain the feed conflict. Matching batch, material and quantity copies count once. Zero-row CSVs retain the last good snapshot. The dashboard surfaces rejected files, ambiguous dates and document review, including MIME email with extracted headers and body.
- Supplier timing uses cited completed PO lines. The art-book card compares paired wait and express-release scenarios and shows the materials-only break-even grid. Loss per missing copy remains pending Dr. Vogt. No chaser reply is treated as a verified delivery outcome.
- React and standalone show sync errors, file reviews and data-health counts. Older static replay snapshots still render. Regenerate hosted snapshots to include the new API fields.
- 60 drop, decision and source tests pass. The 20-probe audit ran. The published forecast regression matched the snapshot fingerprint and all edition quantiles and probabilities. The Vite build and standalone script syntax check pass. The real HTTP handler replay passed in-process, including approval and dry-run send. The socket smoke test could not bind 127.0.0.1 in the sandbox. Browser rendering still needs a live check.

## T42 — Simulated supplier agents (copilot-sim)

- Added `src/agents/suppliers_sim.py` with `SupplierSim`, six supplier personas, private hidden ground truth, language/register markers and attachment names.
- Replies use the existing LLM adapter for live mode and deterministic templates for `FakeLLM` tests; first replies stay bounded and dates require a specific document or per-lot quantity.
- Run `python3 -m src.agents.suppliers_sim --demo` for a two-turn exchange per supplier.
- Verified `python3 -m unittest tests.test_suppliers_sim`: 4 tests pass.

## T45 — Agent knowledge pack (copilot-know)

- Added versioned role knowledge under `src/agents/knowledge/` and `load_pack(role)` for triage, analyst, verifier, planner, chaser and supplier_sim.
- Added `docs/AGENT_ROLES.md` with role cards and the handoff diagram.
- The pack keeps stable domain facts and routing guidance separate from tool-derived quantities, probabilities and costs.
- Nick can wire `load_pack(role)` into specialist prompt assembly. This task leaves `src/agents/prompts.py` and `team.py` unchanged.
- Run `python3 -m unittest tests.test_agent_knowledge`.

## T71 — Live agent visualization (copilot-viz)

- Expanded `web/src/agents/AgentTrace.tsx` into a projector-ready live visualization: Triage through Briefer graph, external-world and human-gate nodes, incoming-drop/triage/agent chain lane, live counters, five-guard harness panel, terminal-style tool stream and citation chips.
- Added recorded-run playback with 1x/2x/4x speed and a fixed-screen Present mode. Existing replay, mock and HTTP adapters remain intact; no shared component restyling or secrets were added.
- `npm --prefix web run build` and `VITE_STATIC=1 npm --prefix web run build` pass.

## T19-Redeploy — Soony production refresh (codex-deploy)

- [Production dashboard](https://soony-launch-control.vercel.app) serves deployment `dpl_Bny9b6AyYGMe5eRmcbWtohFmvbs9`, built from `8684871` with the updated control-room theme and the replay regenerated from `case-data/`.
- The candidate and production both passed `deploy/vercel/verify.py` for team sign-in, private API, React bundle, supplier-drop forecast changes, art-book recovery, independent sessions, reset, and sign-out.
- Address future redeploy requests to `codex-deploy` in `coord/INBOX.md` or route them to the “Redeploy the Vercel site” Codex chat. Include the merged commit or case snapshot to publish.

## T5 — Supplier offer revisions and paired forecasts (murat-agent)

- Fix commit `8937cdb` resolves explicitly superseded quotes by supplier and offer ID. Byte-identical resends keep the first observed citation. Conflicting revisions require buyer review. The extraction audit retains the original notices, and offer quantities stay outside confirmed inventory.
- The Plan B card and expedite calculation use the same held shipment, actual quoted loading and driving time, and equal trial counts with shipment-specific draws. A synthetic late offer adds zero median units and zero on-time probability. The usable control adds 10 median units and raises modeled on-time probability from 27% to 40%.
- The matched 308-file replay still ranks the post-drop art-book hold and written delivered quote first. It is request-only, with the same evidence, materials estimate, gates and modeled benefit. The full offline HTTP rehearsal and 52 focused tests passed.
- The refreshed protected deployment `dpl_Bny9b6AyYGMe5eRmcbWtohFmvbs9` uses the verified 308-file snapshot `2026-11-21_1436`. Signed-in parity at 16:04 CET covered both replay phases, primary action and evidence, timing, option order, readiness, gaps and blocked approval states. No additional refresh is needed for these buyer-visible results.

## T64/T65 — Reply Interpreter and Briefer (copilot-roles)
- Added `interpreter_agent(llm, db)` with a closed five-tool whitelist and JSON contract for language, commitment, quotes, contradictions, ladder and escalation.
- Added conservative `interpret_reply()` plus `--evaluate`; 12 simulated supplier replies agree with attachment ground truth 11/12 (91.7%), deterministic cost $0.00.
- Added `briefer_agent(llm, db)`, `validate_brief()` using `harness.numeric_grounding`, and a deterministic fallback.
- Fake CLI: `python3 -m src.agents.briefer --scenario art_book --fake`; sample headline: “Collector's Edition readiness is blocked by verified evidence.”
- Focused validation: `python3 -m unittest tests/test_agents_roles2.py -q` — 6 passed.
- Related runtime/team validation: `python3 -m unittest tests/test_agents_runtime.py tests/test_agents_team.py -q` — 8 passed.

## Vercel deployment and access (codex-deploy)

- Production serves the authorized 19:25 encrypted snapshot `4de57a7`, built from `5565430bdeadfe3975dab334c6ea77cb329bf4fb` and promoted as `dpl_Ah1BvoKhagMqCLQDFdoXAqUfLJnb`. The package changed only the encrypted asset and reused the verified app with header styling `4319983`. Candidate and production checks verified the updated packed counts (554,000 Standard, 53,100 Collector’s), arrival timeline, €120 Collector’s and €32 unconfirmed Standard cost, supplier-drop/reset, recorded T53 summary and anonymous denial. In a separate browser, the after-drop replay and provenance survived a full reload, with the detailed trace marked unavailable. The browser observed no live agent or supplier requests. The previous verified deployment was `dpl_6MWshXTv9HdMwmE1JZnvBfG1pPBT`. [Soony production](https://soony-launch-control.vercel.app)
- Merge the dashboard change to private `main`. The deploy watch checks every five minutes, verifies a protected candidate, promotes eligible changes, and posts the live commit in [INBOX](INBOX.md). To coordinate a specific merged commit, post `codex-deploy: Vercel release request <commit>` there with a short description and any verification details.
- The project currently belongs to a Vercel Hobby team. On a Pro or Enterprise team, the owner can grant each designated releaser project access through their own Vercel account. Use the lowest role that can create and promote production deployments. Get access to the approved encryption key through the team's private storage. [Protected replay runbook](../deploy/vercel/README.md)
- From a fresh checkout of the merged commit, run the case replay and build the prebuilt package per the runbook. Link the package to the existing `soony-launch-control` project and deploy with `--prod --skip-domain --meta soonySourceCommit=<full-sha>`. Sign in to the generated candidate URL with your Vercel account and the dashboard team password, then test **Process drop**, the updated forecast and **Reset replay**. Promote the verified candidate, run `deploy/vercel/verify.py` against the production URL as documented, and post the commit, deployment, and checks in INBOX. Keep account tokens and the replay key out of Git, logs and agent messages.

## T68 and T69-Reply — Live backend and supplier decisions (murat-agent)

- [Protected live Control Room](https://soony-manti-live.vercel.app) uses the Python backend running on Murat’s Mac. Automatic releases track GitHub main from a dedicated checkout and keep SQLite state across restarts. Signed-in agents can use the app or read `/api/dashboard` and `/api/health`. The prior Vercel replay remains the fallback.
- [Verified mailbox view](https://soony-manti-live.vercel.app/?mail=1) reads supplier-scoped Gmail Sent and Inbox records without changing flags. It matches known Chaser drafts or markers, persists separately from the replay and deduplicates across checks. The initial check was empty. A later check verified one Gmail Sent message and its matched reply, visibly linked to the proposed decision after hard reload. Controlled SMTP and IMAP tests covered success, failures, mismatched mail and deduplication. No test email was sent.
- The simulated game-card reply lowered the upper forecast from 626,650 to 614,650 Standard and 64,350 to 62,550 Collector’s. The art-book reply confirmed a proposed 5,900-unit hold and left delivered pricing and the PO pending. Both retained message and decision IDs after hard reload and a new release.
- Request changes in [INBOX](INBOX.md) with `murat-agent: live backend request`. See [host setup](../deploy/backend/README.md) for the laptop and tunnel requirements.

## sonnet-gate (T72b)
Revision facts were already extracted from OC footers (B at PackRight, C at Karton); parsers.py regex only loosened (revB/rev_C). Gate now resolves PR-SL-0604 alias via same-PO same-qty ERP line, aggregates per supplier (delivered = GRs, open = non-delivered POs). CMP-GAM-004 = HUMAN; evaluate() gained po_rows/gr_rows args. Regression test added in tests/test_release_gate.py. Not committed.

## sonnet-pack T73 (21 Nov)
- src/decide/packplan.py rebuilt on truth.readiness outputs (independent recipes without embedded magnets, usable stock, non-held inbound earliest + median lag, shifts). Exact method in docs/PACKPLAN.md. Tests: tests/test_packplan.py (12, incl. consistency with truth.simulate).
- Baselines reproduce NUMBERS.md: CE first STD 614,650 / CE 62,550; STD first 615,100 / 62,100. Optimizer total gain vs better baseline is 0 (game card CMP-GAM-001 binds); it moves up to 3,550 units STD -> CE (CE 66,100). Air lot 28,000 12 h earlier = +28,000 STD.
- `TOOLS` has a plain dict `packplan(changes?)` for nick to register. Magnet assumption printed on every run. Allocation rules need pre-order data we do not have (owner Head of Procurement / Sales).

## T53-Trace — Art-book run provenance (murat-agent)

- [Machine-readable handoff](../docs/agent_runs/provenance/art-book-live.json) pins four source files by Git commit and SHA-256. Its summary-only coverage lists the reported roles and aggregate usage and leaves event-level timing, costs, approvals, and verified calls unavailable.
- The tracked display snapshot creates five generic rows from the summary. It does not verify tool execution or the order of handoffs. The historical accounting query summed the trace table, so an exact pass-level allocation cannot be recovered from the published totals.
- The [source checks and panel contract](../docs/agent_runs/provenance/README.md) explain the gap. The original event records were requested through the private inbox. The hosted UI, deployment, existing exporter, and approval paths remain with their owners.
- The [read-only SQLite exporter](../docs/agent_runs/provenance/export_bounded_trace.py) needs exact row bounds from the original recording. The inbox request is addressed to copilot-live. Recording access is pending.

## T53 — Authenticated art-book evidence replay (codex-hosted)

- Integration `2e4a112` and release commit `dffa6bb` carries the pinned provenance manifest (`f68cf1d`) into the encrypted dashboard response. The reported summary, cost, tokens, and pending-approval flag are attributed. The original event sequence and timing remain unavailable, so the panel does not generate substitute steps. See the Vercel runbook for the verified-events contract.
- Local packaged replay passed in a separate browser session. Signed-in AI reasoning showed reported usage and provenance, and persisted after the supplier drop and reload. Hosted traces use neither live agent endpoints nor action controls. codex-deploy promoted the verified protected preview `dpl_Ek7PGWEKHPgND2V9WDBCW4XghKVr`. Independent production verification passed team sign-in, summary-only coverage, supplier-drop forecast, reset and sign-out.
- Integration `5cf4fbe` carries the pinned provenance manifest (`f68cf1d`) into the encrypted dashboard response. The reported summary, cost, tokens, and pending-approval flag are attributed. The original event sequence and timing remain unavailable, so the panel does not generate substitute steps. See the Vercel runbook for the verified-events contract.
- Local packaged replay passed in a separate browser session. Signed-in AI reasoning showed reported usage and provenance, and persisted after the supplier drop and reload. Hosted traces use neither live agent endpoints nor action controls. codex-deploy owns the protected preview and production promotion.

## T78 — Team overview digest (overview-agent)

- `scripts/overview.py` (stdlib only, does not import the app) reads `coord/STATUS.md`, `TASKS.md`, `INBOX.md` and `git log`, and writes `coord/agents_overview.json` (for agents) and `coord/AGENTS_OVERVIEW.md` (for humans). Do not edit those two files by hand.
- Rules: the last STATUS/TASKS row wins. A STATUS row still `in_progress` for a task that TASKS marks done is flagged as outdated. An INBOX request counts as unanswered until the addressee writes back to the sender. `in_progress` with no commit, INBOX line or timed STATUS update for 90 min counts as stale. Autosync commits are credited to the owner of the touched directory when that owner is unambiguous.
- Live page: `python3 scripts/overview.py --serve 8765 [--push 600]` serves `src/overview/dashboard.html`, runs `git pull` and regenerates every 60 s; with `--push`, it commits and pushes only the two overview files as overview-agent when their content changed.
- Known limits: the classification is heuristic (keywords), and STATUS rows that give only a date and no time do not count as activity.

## T74 — Gate + packplan as agent tools (sonnet-wire)

- `packplan` (read-only, `changes` what-if: `part_arrives_earlier`, `release_quarantined`, `restore_stock`) added to `src/agents/tools.py`; `release_gate_status` description rewritten. Roles: Analyst = release_gate_status; Verifier = release_gate_status; Planner = packplan + release_gate_status (`src/agents/prompts.py` ROLE_TOOLS). Knowledge: guidance appended to `knowledge/pitfalls.md` (sleeve conflict = HUMAN, quarantined statue lot = HOLD, game card is the binding part, never state units not in the packplan result).
- Harness needed no change: numeric_grounding/citation_check read tool results from the trace (tests/test_agents_gate_tools.py proves accepted and ungrounded numbers).
- New golden scenarios `sleeve_revision_conflict`, `air_lot_priority` (fake mode via `_ScenarioLLM`). Fix in `tests/agent_eval/run_eval.py`: live copies now also clear agent_mailbox/approvals/state; stale delegations made every live scenario skip its specialists and pass trivially.
- Note: stop_check counts identical tool signatures across agents, so prompts tell Verifier to call release_gate_status with the part_id and Planner with no arguments.

## T79-Supplier-Loop — game-card and Karton follow-ups (murat-agent)

- `abf0997` added the persisted decisions. `e4376cf` added one-shot follow-up dispatch through the existing worker, verified mailbox input, and no-dispatch replay packaging.
- Two isolated browser runs used the same Soony inputs. Each started with one game-card dry-run request. The 13:00 CET reply with missing documents and slot created one follow-up, for two game-card attempts total. The same ETA with all three mock documents and a confirmed slot left the total at one. Counts held through browser reloads, two process starts per case, and 25 and 20 successful dashboard polls respectively. The SMTP test double recorded one same-thread Karton status request across two live worker cycles. An ambiguous SMTP disconnect under concurrent claims produced one attempt and a reconciliation item.
- A 23:00 CET revision replaced the dock review with launch recovery and blocked stale dock approval. At 13:00 the faster dock scenario modeled medians of 632,650 Standard and 65,250 Collector’s versus 614,650 and 62,550 without it. At 23:00 modeled faster handling added zero. Both branches held the shared forecasts and purchasing gates.
- Authenticated Mac-backed service on `e4376cf` returned zero worker health errors, dry-run mode, and the verified Karton thread with two Gmail Sent messages and two received replies. The 50–100-unit ask is awaiting a one-off exception to the stated 5,000-unit minimum. The 5,900-unit offer is a separate pending purchase review. The observed mailbox is read-only and no real QA email was transmitted. [Protected Karton thread](https://soony-manti-live.vercel.app/?mail=1&thread=6F967080CF)
- Worker regression passed for identical reply text with new attachment evidence. All three documents arriving together or across partial replies canceled the queued request. A duplicate retransmit kept the controlling reply and produced zero follow-ups.
- Validation passed for 55 chaser tests, 12 inbound tests, the full supplier-drop replay, the web build, and construction and decryption of a replay package that preserved T53 and the art-book recommendation with zero dispatch. No release promotion was performed.

## T78-Mail-Queue — multiple component requests (murat-agent)

- The automatic worker can send several distinct component requests to the same supplier in one cycle. An unanswered request pauses only the same recipient and component. A matched reply lifts that wait. Set `CHASER_AUTO_COOLDOWN_MIN=0` to disable the time window.
- The normal transport claim rechecks duplicate content, cooldown, the allowlist, and the information-only guardrail before SMTP. Mocked SMTP recorded two sends with the default cooldown and three with the cooldown disabled. Duplicate content and repeated polls added zero. The Mac demo remains dry-run. No supplier email was sent for testing.

## T80-Mac-Mail — live supplier email on the Mac (murat-agent)

- Activated 21 Nov at 18:30 CET. The protected Mac now runs live SMTP and read-only Inbox polling for the case-supplier domain. The operational SQLite store reuses the earlier Karton records and is separate from the replay. `2627f65` added the operator switch, and `f21cb40` applies launch-cover and release constraints from matched replies.
- Verified four requests in the initial worker cycle and one same-thread Hwaseong follow-up. All five were accepted by SMTP and reconciled against Gmail Sent. Every initial request received a Message-ID-matched supplier reply.
- Boise stock changed from pending to blocked under its stated EXW or forwarder condition. The Dongguan and Pune replies ruled out covering the statue gap before launch, and the Dongguan air-split option changed from pending to blocked. Hwaseong confirmed the 28,000-unit lot while awaiting the airline's ETA, so dock and customs release remains pending.
- Verified the signed-in hosted API, evidence and decisions after browser reload, and 72 focused tests. Real messages change planning options. Purchase and dock release still require PP-07. [Protected live supplier view](https://soony-manti-live.vercel.app/?thread=C86B928B4D)

## sonnet-gate (T89 Release Gate v2)
- `src/decide/release_gate.py`: new `load_drop(data_root)` reads bom_delta, components_update, supplier profile.json, org_chart_v2 (via gs) and the CPO memo directly from data/; `evaluate(..., drop=None, as_of=None)` stays backward compatible. `release_gate(con)` passes the drop automatically.
- Verdicts: CMP-GAM-004 HOLD (hold 64,000 rev B; do not accept 675,000 rev B; usable rev C = stock - 64,000 = 122,000; decision Sofia Marchetti). CMP-GAM-009 GO + use-up note. CMP-GAM-010 HOLD, critical, `required_authority` = Clara Weiss (HOLD to GO), Pune qualification expired -> Head of Procurement Dr. Maren Vogt + Daniel Okafor co-sign. CMP-MAG-005 HUMAN (double count only) + rare-earth note. Others unchanged.
- New part fields: ecn, do_not_accept_quantity, usable_new_revision_quantity, old_revision_lot_quantity, required_authority, required_human_action.decisions; editions now carry remaining and limited_by. For CMP-GAM-004 status is HOLD but go_quantity is the usable rev C quantity (not 0): consumers should not read HOLD as zero GO.
- Edition counts use the store's current numbers (Standard remaining 128,000, stock): sonnet-engine's new packed counts / consumption flow through truth.readiness; Standard now limited by CMP-GAM-003 (96,000) rather than the sleeve. Tests: `.venv/bin/python -m unittest tests.test_release_gate` (7 pass).

## T81-Recovery — launch recovery operations (murat-agent)

- Two operator-authorized, information-only requests were sent at 19:25 CET and verified in Gmail Sent. Hwaseong `219993CB24` and Boise `66F6864D51` both replied. Boise has no released EU stock and ruled out the Sunday 08:00 CET handoff. Hwaseong still lacks a confirmed ETA, paperwork and carrier contact for the airborne lot. It expects the 20,000-card balance in Hamburg on Tuesday 24 Nov.
- Submitted review for the provisional dock slot, Paul Winter's Karton PO and Daniel Okafor's 100% sort of the 5,600-unit quarantined lot. The €12,390 DAP quote covers 5,900 art books. Reconcile net need and delivery against the 19:25 drop before ordering. Quality & Compliance has final release authority. The dock still needs a verified forwarder contact and receiving confirmation.
- The signed-in dashboard and a separate browser verified the three cards on the Mac, with both actual replies linked and Boise still blocked. `063a6f9` surfaces the approvals and `c646b34` retains pending reviews when an underlying option changes and preserves Boise's EXW hold. [Recovery approvals](https://soony-manti-live.vercel.app/#recovery-approvals)

## T92 — Profit plan (sonnet-profit)

- Added `scripts/profit_model.py` (pure Python, deterministic, parameterised: `--scenario low|base|high`, `--set NAME=value`) and `docs/PROFIT_PLAN.md`. Enumerates 2^7 action subsets with interactions, Pareto frontier, sensitivity, value-based price.
- Base result: best set A B C D F (Collector's first, dock+customs, cases, art books, statues), net about EUR 840k expected, cost EUR 31k; art books and statues pay only together with Collector's first.
- Known gaps: L_STD (EUR 32 unconfirmed; default EUR 3 assumed), success probabilities and A fee are assumptions; counts are kickoff totals, rerun after sonnet-engine refreshes NUMBERS.md. Web figures are snippet-only [S].

## T88 — 19:25 drop in ingest and engine (sonnet-engine)

- Ingest (src/ingest/drop.py, readers.py, models.py, run.py): new typed tables `launch_status` (edition lines + notes, German thousands "554.000" understood, as_of from workbook time + "Saturday 13:00"), `bom_changes`, `component_changes`, `supplier_component_changes`, `news_items`; `products` gets day_one_qty and valid_from; `suppliers` gets qualification_valid_until/released_on/extended_by (vendor master v2 profile.json is a second source row per supplier, sorts after profile.csv so it wins). bom/components readers now exclude `*delta*`/`*update*` (they broke the build: "missing columns qty_per"). Additive ALTER TABLE migration, sha-based, idempotent. `python -m src.ingest.run` rebuilt store/soony.db (second run: no changes). Test: src/ingest/test_drop.py.
- Docs (src/docs): .docx supported (CPO memo gives `priority_rule` and `memo_line` facts), org chart v2 role carries `valid_from` (Arjun Krishnan 2026-11-23), export-licence notice gives an `export_licence` fact (deliveries after 2026-12-01 move 6 weeks, launch boxes held). Notice parser rev 4, context rev 2 (cache refresh).
- Engine (src/truth/__init__.py): packed/rate from launch_status when later than the pack-out log (issue `packed_conflict` shows both); usable stock minus parts of copies packed since the log (issue `stock_consumption`; `parts[].consumed_since_snapshot`); ECN revision hold (`parts[].revision_hold`, issue `revision_hold`, old-rev inbound ignored); `parts[].critical/drawing_rev/ecn`; Pune qualification expiry and PackRight flags as issues; shifts clipped to start at the status time (23 h left, was 30). release_gate.py: no longer subtracts the rev B lot twice (reads `revision_hold`). Orchestrator risks list now also shows `revision_hold` parts.
- Numbers: STD 554,000 / CE 53,100 packed; forecast p50 STD 614,650 / CE 62,550, P=0%, first stop game card (unchanged). Gaps: game card 34,800 before inbound / 6,800 after, art book 5,900, statue 3,400, case 32,000 before inbound / 0, STD sleeve 6,000 before inbound / 0 with Karton's 20,000 (SHP-2026-04313). NUMBERS.md: section "After the 19:25 drop", old sections marked STALE; test_numbers has the new fingerprint 808d217e... and invariants. Known unrelated failure: src/docs test_loopback_adapter_decodes_the_ollama_chat_response (provider mock, not touched).

## T81-Drop-1925 — live launch recovery (murat-agent)

- Signed-in portal export verified byte for byte. The private Git snapshot `4de57a7` has 318 files (10 new, 1 replaced, 0 removed). `tests.test_numbers` matches the committed snapshot and forecast: 554,000 Standard and 53,100 Collector’s packed as of Sat 13:00 CET, p50 614,650 / 62,550 and 0 of 500 complete launches. `case-data/soony/context/launch_status.xlsx` and `case-data/soony/master/bom_delta_2026-11-21.csv` row 2 are the controlling inputs.
- Live outreach and matched supplier replies are in Manti. Karton schedule for the existing 20,000 rev-C sleeves is Sat evening for PO 7K21M (thread `06E83D9DBA`). Signed proof of delivery, lot and Quality release are outstanding. Additional rev-C sleeves are unavailable by the cutoff from both Karton and PackRight (threads `80FC81672C`, `F98D6EF7DF`). The 64,000 rev-B sleeves remain held. State shows a 6,000 sleeve gap until receipt. The 350,000-case CTA Hamburg pickup is also a dependency (32,000 short before receipt, `soony/erp/open_shipments.csv` row 2).
- Hwaseong’s 28,000-card air lot is the first recovery action (thread `219993CB24`). Carrier time, paperwork, forwarder contact and Hamburg handover still need verification. Its 20,000-card balance and the 240,000-card sea lot are scheduled after launch (sea enquiry `22C4C62CBF`). Boise has no released EU stock and says FRA is approximately two days from release (`66F6864D51`). The lower-bound card shortage is 34,800 before the air lot and 6,800 after it.
- The Manti review section preserves the dock, Karton art-book PO and statue sort, and adds checks for the rev-C receipt and terminal pickup. The last priced art-book quote was EUR 12,390 delivered for 5,900, subject to reconfirming the hold and delivery window. The 5,600-statue sort must yield at least 3,400 released units. Quality & Compliance has final release authority. No binding action was taken.
- Paired 500-trial estimate with the terminal cases in the model gives 700,100 p50 if handling is capped at four hours and sleeve receipt is excluded, or 704,750 if sleeve receipt is included. Without terminal cases the otherwise comparable p50 falls to 674,100. A deterministic CE-first packing schedule can reach 712,000 if cases and sleeves are available in time, 5,900 approved books are usable by Sun 09:00, 3,400 statues released by noon, and 7,200 extra cards are usable by 14:00 with the 28,000 air lot usable by 16:00 (all CET). With those other dependencies fulfilled and no extra cards, the same schedule reaches 72,000 Collector’s and 632,800 Standard. This is based on the Sat 13:00 counts and modeled rates. The 7,200-card source and these release times remain unconfirmed.

## T93-Mail-Archive — supplier correspondence (codex-mail-archive)

- The [supplier email archive](../docs/supplier-email-archive/README.md) contains 8 chains, 56 verified Gmail messages as of 21 Nov 2026 at 20:02:11 CET. Use the archived Message-IDs to cite specific offers, constraints and replies. Each message keeps its original body and known dashboard record ID.

## T81-Supplier-Changes — recover from supplier or shipment changes

- The normal Mac worker applies explicit, exactly matched shipment cancellations, reduced quantities and time-zoned Hamburg handoff changes before recomputing the forecast. It also compares newly ingested authoritative shipment records, including cancellation, severe delay or a new hold. A verified withdrawal on the original quote thread invalidates the offer without changing on-hand inventory. Ambiguous, unmatched and superseded replies do not amend committed supply.
- The worker asks the original supplier and any other qualified, allowlisted source with a plausible window about released stock, partial delivery, dated Hamburg handoff, delivered quote and shipping evidence. It skips a known refusal, keeps the original correspondence threaded when possible, and uses the existing duplicate, cooldown and SMTP claim. A potentially usable quote queues a PP-07 review and does not count as stock. Stale dock/offer approvals are blocked and undispatched reservation notices tied to stale offers are retired. The live Manti Supplier recovery card shows actual dispatch or queue state and links to the reply. Protected replay does not dispatch.
- In a controlled run on the 318 case files, changing the 28,000-card Hwaseong AWB 020-48113256 to cancelled increased the material gap from 6,800 to 34,800. The stale dock review disappeared and a single enquiry used the mocked SMTP transport. Boise's verified no-EU-stock response excluded it. A second isolated worker test with a viable alternate produced two enquiries and a new approval review after a timely quote; restarts and an out-of-order cancellation retransmit produced no additional sends. Both tests used controlled transport. The test cancellation is not live supplier evidence.
