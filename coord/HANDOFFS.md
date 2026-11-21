# HANDOFFS — when a task ends: what you built, how to run it, known gaps, next step.

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

## T19-Redeploy — Soony production refresh (codex-deploy)

- [Production dashboard](https://soony-launch-control.vercel.app) serves deployment `dpl_Bny9b6AyYGMe5eRmcbWtohFmvbs9`, built from `8684871` with the updated control-room theme and the replay regenerated from `case-data/`.
- The candidate and production both passed `deploy/vercel/verify.py` for team sign-in, private API, React bundle, supplier-drop forecast changes, art-book recovery, independent sessions, reset, and sign-out.
- Address future redeploy requests to `codex-deploy` in `coord/INBOX.md` or route them to the “Redeploy the Vercel site” Codex chat. Include the merged commit or case snapshot to publish.
