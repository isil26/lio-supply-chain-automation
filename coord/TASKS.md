# TASKS board (specs in CODEX_TASKS.md). Status: open | in_progress | review | done | blocked
| ID | Task | Owner | Dir | Status | Depends on |
|---|---|---|---|---|---|
| T1 | Ingestion layer -> store/soony.db | Codex | src/ingest | review | - |
| T2 | Doc extraction (OC pdf, delivery-note images, notices, contracts) with provenance | Codex #2 | src/docs | done | FINDINGS formats |
| T3 | Readiness engine (BOM/MRP netting, Monte Carlo, criticality, usable-stock adjustments) | nick | src/truth | in_progress | T1 (can start on CSVs) |
| T4 | Supplier Chaser (multilingual drafts, approval gate, reply parsing, escalation) | Copilot #2 | src/chaser | done | T2 |
| T5 | Plan B / decision copilot (option enumeration, cost vs P(on time), approval policy PP-07) | Codex | src/decide | done | T3 |
| T6 | UI Control Room | Copilot | web | review | contract in DECISIONS.md |
| T7 | Orchestrator + drop handling (sync -> reingest -> re-evaluate) | Codex | src/orchestrator | done | T1,T3 |
| T8 | Submission: README, deck outline, demo script, business case | Codex | docs/ | done | - |
| T8 | Pitch deck, speaker notes, PDF export guide | copilot-deck | docs/deck | done | Built 6-slide HTML deck, 3-minute notes, and PDF export README in docs/deck. |

| T9 | Visible LLM step, escalation case (Pune/Category Lead), numbers script | codex-truth | src/truth, src/docs, src/decide, src/orchestrator | done | docs/WIN_PLAN.md |
| T10 | Static replay + live-API React UI hero screen | copilot-ui | web | done | Live HTTP client, Vercel static snapshots, local replay state, reset, dry-run send/reply and static evidence mode complete |
| T7 | Show blocked releases in the standalone demo | murat-agent | src/orchestrator/control-room.html | done | T9 approval API |
| T11 | Supplier lag calibration, readiness sensitivity and counterfactual CLI | codex-sens | src/truth/sensitivity.py, src/truth/test_sensitivity.py | in_progress | T1, T3 |
| T11 | Supplier lag calibration, readiness sensitivity and counterfactual CLI | codex-sens | src/truth/sensitivity.py, src/truth/test_sensitivity.py | in_progress | T1, T3 |
| T11 | Supplier lag calibration, readiness sensitivity and counterfactual CLI | codex-sens | src/truth/sensitivity.py, src/truth/test_sensitivity.py | done | T1, T3 |
| T12 | Offline demo smoke check, end-to-end tests, and demo runbook | codex-e2e | scripts/demo_check.sh, tests/test_e2e.py, docs/RUNBOOK.md | done | T7, T9, T10 |
| T7 | Serialize demo database initialization | murat-agent | src/orchestrator/__main__.py | done | T12 startup report |
| T13 | Hidden findings hunt (artwork rev, Incoterm, pins, cancellations, stale counts, magnets, contracts) -> docs/HIDDEN_FINDINGS.md | codex-hunter | docs/HIDDEN_FINDINGS.md | in_progress | FINDINGS.md |
| T14 | Surprise-drop robustness tests (new formats, encodings, languages, corrupt files) -> docs/DROP_ROBUSTNESS.md | codex-drops | tests/drops, docs/DROP_ROBUSTNESS.md | done | T7 |
| T15 | Supplier reliability prior (discounted ETA, p_on_time, update hook) | codex-decide | src/decide/reliability.py | done | docs/GAME_THEORY.md |
| T16 | Chaser: reply commitment scoring, R1 templates, validate_draft guardrail, R0-R4 ladder | copilot-chaser | src/chaser | done | docs/GAME_THEORY.md |
| T17 | Expedite option chooser with break-even L* (no default for L) | codex-decide | src/decide/expedite.py, tests/test_decide_extra.py | done | T15 |
| T18 | Pitch + deck rewrite: true hook (SAP hides art book + statue gaps), cuts per docs/REDTEAM.md | nick | docs/PITCH_3MIN.md, docs/deck | in_progress | docs/REDTEAM.md |
| T19-Vercel | Team-authenticated Vercel dashboard and supplier-drop replay | codex-hosted | deploy/vercel, narrow hosted-mode changes in web | done | T7, T9, T10 |

| R-methods | Compare relevant products and scientific methods, reproduce decision-quality issues, and coordinate focused experiments | codex-methods | research index and inbox (own entries) | in_progress | coordinate with research, research-gt, hunter, drops and decide |
More unclaimed work: see coord/OPEN_TASKS.md (T19-T31). Claim by copying the row here.
| T32 | Apply drop-robustness patches from docs/DROP_ROBUSTNESS.md (cancelled shipment still counted when tracker stale; same stock lot at a second path double-counted; .eml/unknown docs silently ignored; header-only CSV treated as empty; React ignores sync.error; PO CSV re-read as UTF-8 throws) | codex-truth (src/*) + copilot-ui (web warnings) | src/truth, src/ingest, src/docs, web | open P1 | docs/DROP_ROBUSTNESS.md |

| T21 | Keep the default forecast consistent across the dashboard and published numbers, with a regression check | codex-consistency | docs/NUMBERS.md, tests/test_numbers.py | done | codex-truth |
| T32 | Apply drop-robustness patches from docs/DROP_ROBUSTNESS.md (cancelled shipment still counted when tracker stale; same stock lot at a second path double-counted; .eml/unknown docs silently ignored; header-only CSV treated as empty; React ignores sync.error; PO CSV re-read as UTF-8 throws) | codex-truth (src/*) + copilot-ui (web warnings) | src/truth, src/ingest, src/docs, web | open P1 | docs/DROP_ROBUSTNESS.md |
| T32 | Apply drop-robustness patches from docs/DROP_ROBUSTNESS.md (cancelled shipment still counted when tracker stale; same stock lot at a second path double-counted; .eml/unknown docs silently ignored; header-only CSV treated as empty; React ignores sync.error; PO CSV re-read as UTF-8 throws) | codex-truth (src/*) + copilot-ui (web warnings) | src/truth, src/ingest, src/docs, web | in_progress P1 (codex-fix) | docs/DROP_ROBUSTNESS.md |
| T32 | Apply drop-robustness patches from docs/DROP_ROBUSTNESS.md (cancelled shipment still counted when tracker stale; same stock lot at a second path double-counted; .eml/unknown docs silently ignored; header-only CSV treated as empty; React ignores sync.error; PO CSV re-read as UTF-8 throws) | codex-truth (src/*) + copilot-ui (web warnings) | src/truth, src/ingest, src/docs, web | in_progress P1 (codex-fix) | docs/DROP_ROBUSTNESS.md |
| T32 | Apply drop-robustness patches from docs/DROP_ROBUSTNESS.md (cancelled shipment still counted when tracker stale; same stock lot at a second path double-counted; .eml/unknown docs silently ignored; header-only CSV treated as empty; React ignores sync.error; PO CSV re-read as UTF-8 throws) | codex-fix | src/truth, src/ingest, src/docs, src/decide, src/orchestrator, web (warnings and decision/health display) | done | docs/DROP_ROBUSTNESS.md |

| T5 | Resolve explicit supplier-offer revisions and pair Plan B forecasts | murat-agent | src/decide, supplier-notice parsing, offer regressions | done | T11, T14, T32 |
| T33 | Shared LLM client: schema + quote validation, cache, budget, cost log, fallback, `python3 -m src.llm.check` live proof, env-name fix | copilot-llm | src/llm, glue in src/docs/providers.py, src/chaser/llm.py | done P1 | docs/ARCHITECTURE_REVIEW.md B |
| T34 | State hardening: WAL, sync outside cycle lock, /api/health, regression tests | copilot-state | src/orchestrator, src/chaser/store.py, src/ingest/store.py | in_progress P1 | docs/ARCHITECTURE_REVIEW.md E |
| T34 | State hardening: WAL, sync outside cycle lock, /api/health, regression tests | copilot-state | src/orchestrator, src/chaser/store.py, src/ingest/store.py | done P1 | docs/ARCHITECTURE_REVIEW.md E |
| T35 | Triage agent (orchestrator-workers, closed tool whitelist, <=3 rounds, falls back to fixed order) | open P1 | src/agent | T33 |
| T36 | Fallback extractor + coverage contract (full/partial/none) + review queue incl. .eml | open P1 | src/docs | T33 |
| T37 | LLM-drafted chaser emails with validator and template fallback | open P2 | src/chaser | T33 |
| T38 | Multi-agent runtime: tool-calling ReAct loop, Anthropic + OpenAI-compatible adapters, record/replay cassettes, Team with delegate + blackboard + mailbox, trace to activity feed, human-gate primitive | copilot-runtime | src/agents/runtime.py, llm_adapter.py, trace.py | in_progress P1 | - |
| T39 | Tool layer wrapping existing deterministic code (readiness, whatif, search_documents, compare_sources, breakeven, draft/send/parse, propose_option, escalate_to_human, request_review) | copilot-tools | src/agents/tools.py | done | - |
| T40 | The agents: Triage/Orchestrator (plans, delegates), Analyst (finds and explains gaps with citations), Verifier (checks every claim against quotes, rejects unsupported), Planner (Plan B options with cost), Chaser agent (autonomous ladder: draft, wait, parse reply, escalate). System prompts, tool whitelists, hand-offs | copilot-agents | src/agents/team.py, prompts.py | done P1 | T38, T39 |
| T41 | Autonomy loop: on a data-drop event the Triage agent runs; timers advance the chaser ladder; approval queue; kill switch; budget cap per cycle; replay from cassettes for a reliable demo; wire into src/orchestrator behind SOONY_AGENTS=1 with the old pipeline as fallback | open P1 | src/orchestrator (small), src/agents/loop.py | T40 |
| T42 | Simulated supplier agents: LLM personas per supplier (language, private capacity/ETA, reliability from history, deliberately vague or late replies) that answer drafted emails; makes the whole multi-agent loop testable without real email, also a demo fallback | open P1 | src/agents/suppliers_sim.py | T38 |
| T43 | Test runs with a real API: scripted scenarios (art-book shortfall, quality hold, game-card short-ship, unseen German notice), run each 3-5 times, record cassettes, measure success rate, tool-call correctness, hallucinated numbers (must be 0), cost and latency; report in docs/AGENT_EVAL.md | open P1 | tests/agent_eval/, docs/AGENT_EVAL.md | T40, API key |
| T44 | UI: multi-agent trace view (who called which tool and why, hand-offs between agents, approvals waiting) in React + standalone page | copilot-trace | web/src/agents | done P2 | T38 trace format |
| T42 | (taken) Simulated supplier agents | copilot-sim | src/agents/suppliers_sim.py | done P1 | T38 done; deterministic fallback and demo CLI verified |
| T38b | Make the live agent path real: auth env names, valid OpenAI/Anthropic tool-calling protocol, honest errors (no silent scripted fallback), cost accounting, first successful live run recorded to cassettes + docs/agent_runs/ | copilot-live | src/agents | done P1 | T38, T39, T40 |
| T45 | Project knowledge pack per role (domain, data map, policy, pitfalls, negotiation, style, few-shot examples) + role cards docs/AGENT_ROLES.md; loader load_pack(role); no computed numbers in the pack | copilot-know | src/agents/knowledge, docs/AGENT_ROLES.md | done P1 | - |
| T46 | Guard harness: numeric grounding, citation check, PP-07 policy check, stop/oscillation check, language check, golden eval scenarios + report docs/AGENT_EVAL.md (merges with T43) | copilot-harness | src/agents/harness.py, tests/agent_eval | done P1 | T40 |
| T47 | Wire pack + harness into prompts/runtime: agents load their pack, every run is evaluated by the harness, violations block proposals and show in UI | open P1 | src/agents | T45, T46, T38b |
| T19-Redeploy | Refresh the protected Soony production replay and coordinate future deploy requests | codex-deploy | coord | done | T19-Vercel |
| T47 | Wire pack + harness into prompts/runtime: agents load their pack, every run is evaluated by the harness, violations block proposals and show in UI | open P1 | src/agents | T45, T46, T38b |
| T19-Redeploy | Refresh the protected Soony production replay and coordinate future deploy requests | codex-deploy | coord | in_progress | T19-Vercel |
| T47 | Wire pack + harness into prompts/runtime: agents load their pack, every run is evaluated by the harness, violations block proposals and show in UI | copilot-wire done P1 | src/agents | T45, T46, T38b |
| T19-Redeploy | Refresh the protected Soony production replay and coordinate future deploy requests | codex-deploy | coord | in_progress | T19-Vercel |

Round 2 open tasks T48-T62 (humans and agents): see coord/OPEN_TASKS.md.
| T50 | (assigned by nick) | codex-overseer | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T54 | (assigned by nick) | codex-overseer | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T58 | (assigned by nick) | codex-overseer | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T60 | (assigned by nick) | murat-agent | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T55 | (assigned by nick) | murat-agent | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T48 | (assigned by nick) | leo-claude | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T57 | (assigned by nick) | leo-claude | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T29 | (assigned by nick) | leo-claude | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T53 | Authenticated replay of the verified art-book agent recording | codex-hosted | web/src/BehindScenes.tsx, hosted agent panels, deploy/vercel replay packaging and checks | review | Summary live on dffa6bb; detailed events await the originating recording |
| T56 | (assigned by nick) | codex-access | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T25 | (assigned by nick) | codex-access | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T31 | (assigned by nick) | codex-access | see coord/OPEN_TASKS.md | assigned, not yet acknowledged | |
| T28 | UI taste + accessibility pass | (released by gülşah-agent) | web/, docs/ui/ | open | changes reverted at owner's request |
| T63 | Document Reader agent (LLM + vision): scans, handwriting, multilingual notices, quote-validated facts, coverage rating, review queue, provisional facts need approval | copilot-reader | src/agents/reader.py | done P1 | T33 |
| T64 | Reply Interpreter agent: supplier reply -> commitment strength, next ladder step, escalate | copilot-roles | src/agents/interpreter.py, tests/test_agents_roles2.py | done P1 | T47 |
| T65 | Briefer agent: one-screen brief for Dr. Vogt from verified facts only (no new numbers), harness-checked | copilot-roles | src/agents/briefer.py, tests/test_agents_roles2.py | done P1 | T47 |
| T66 | Per-role model routing: cheap model for extraction/parsing, stronger for Planner; cost table; configurable via env | open P2 | src/agents | T47 |
| T67 | Inbound expedite option: dock slot + customs pre-clearance for landing lots (SHP-2026-04311 game-card air lot), pickup wording for lots at port | isil-agent | src/decide/inbound.py, tests/test_inbound.py (+ hook in src/decide/__init__.py, handling_hours in src/truth/sensitivity.py) | done P1 | T3, T17 |
| T41 | Autonomy loop in orchestrator behind SOONY_AGENTS=1, runs table, trace/run APIs, kill switch, replay, harness on every run | copilot-loop | src/agents/loop.py, orchestrator glue | done P1 | T47 |
| T44 | Agent team trace panel in the control room (graph, timeline, citations, harness badge, approvals, recorded-run mode for hosted) | copilot-trace | web/src/agents | done P2 | T41 contract |
| T47b | Fix live agent failures: stop_check/loops, citation_check, briefer policy errors; budget $0.60 | copilot-fix2 | src/agents | done P1 | T47 |
| T47c | Harness calibration + debug citation/numeric failures in replay; one live run per scenario under $0.30 | copilot-fix3 | src/agents | done P1 | T47b |
| T68 | Host the persistent Python backend, add a protected Vercel live path and deploy current main automatically | murat-agent | deploy/backend, Vercel live preview configuration, scoped API and UI glue | done | T19-Redeploy, T41 |
| T69-Reply | Turn a matched supplier reply into a cited forecast scenario and reviewable next step | murat-agent | src/chaser reply extraction, src/orchestrator, web supplier threads | done | T26, T67 |
| T67 | Event taxonomy + materiality triage (ignore/watch/act/escalate with reasons, 12 labelled synthetic events, eval) | copilot-triage | src/agents/triage_policy.py, tests/agent_eval/events/, tests/test_triage_policy.py | done P1 | Added deterministic + ambiguous LLM triage, SQLite log, 12 synthetic fixtures and eval; 4 tests pass and eval is 12/12 |
| T69 | Money on the table: cited damages, price drift, freight terms, leakage | copilot-claims | src/decide/claims.py, docs/CLAIMS.md, tests/test_claims.py | done P1 | HIDDEN_FINDINGS |
| T41b | Fix empty agent trace endpoint, German-notice scenario citation, runs list fields | copilot-loop2 | src/agents, /api/agents routes | in_progress P1 | T41 |
| T71 | Live agent visualization: animated agent graph, event-to-decision lane, tool-call stream, harness panel, human gate, counters, Present mode, recorded-run replay for hosted | copilot-viz | web/src/agents | done P1 | T44, T41b |
| T71 | Agent visualization: RELEASED by nick; a first version exists in web/src/agents (graph, event lane, stream, harness, gate, Present mode, replay) but the user finds it poor; the new owner may rebuild it freely | (new owner, claim here) | web/src/agents | open P1 | |
| T47d | Planner uses real option ids, run summary, Chaser draft with pending approval, step cost attribution | copilot-planner | src/agents | done P1 | T41b |
| T72 | Release Gate: GO/HOLD/HUMAN per BOM part with cited rules (AQL, artwork rev, magnet conflict, vacant Category Lead, Incoterms, usable stock), API + agent tool; UI left to the viz owner | copilot-gate | src/decide/release_gate.py, src/agents/tools.py, src/orchestrator | done P1 | HIDDEN_FINDINGS |
| T73 | Pack-out schedule optimizer (what to pack when, Pareto CE vs STD, unknown L) + numbered CE allocation rules + what-if | copilot-pack | src/decide/packplan.py | in_progress P1 | T11, T17 |
| T72b | Extract artwork revision from OC footers so the Release Gate flags the sleeve rev B/C conflict (HUMAN) | copilot-gate2 | src/docs/parsers.py, release_gate.py | in_progress P1 | T72 |
| T73 | (re-owned) pack-out optimizer consistency fix: use truth engine independent recipes, honest gain vs baseline | sonnet-pack | src/decide/packplan.py | done P1 | copilot quota out |
| T72b | (re-owned) artwork revision extraction for the Release Gate | sonnet-gate | src/docs/parsers.py, release_gate.py | done | copilot quota out |
| T71 | Agent visualization rebuilt as live agent map: main-page card "Agents at work", agents light up and hand-offs animate as trace steps arrive (polls /api/agents every 2 s); hosted/static replay the recorded art-book run step by step | gülşah-agent | web/src/agents/AgentGraph.tsx, agentGraph.css (+1 line in web/src/main.tsx) | done P1 | T41b |
| T74 | mail-agent: compare supplier replies, rank best supplier, draft price-negotiation emails (approval-gated) | mail-agent (gülşah-agent) | src/chaser/negotiate.py, src/chaser/mail_agent.py | done | T26 |
| T75 | mail-agent: adaptive best-supplier model (weights shift with time pressure and price spread), split orders, multi-lever negotiation (price/date/partial/express) | mail-agent (gülşah-agent) | src/chaser/negotiate.py | done | T74 |
| T76 | mail-agent: reminder drafts for silent suppliers + read reply attachments (packing list, AWB, invoice) as evidence | mail-agent (gülşah-agent) | src/chaser/followup.py, src/chaser/__init__.py (receive: attachments only) | done | T26 |
| T77 | Best-supplier card in the control room: GET /api/suppliers/best, POST /api/suppliers/drafts, React card | mail-agent (gülşah-agent) | src/orchestrator/__main__.py (2 routes), web/src/suppliers/ | done | T75 |
| T53-Trace | Verify original art-book trace provenance and publish a safe handoff | murat-agent | docs/agent_runs/provenance, own coordination notes | awaiting original source | T38b |
| T78 | Overview agent: auto-generated per-agent digest (task, state, last activity, last commit, open INBOX, stale/duplicate rows) -> coord/AGENTS_OVERVIEW.md + coord/agents_overview.json, live dashboard | overview-agent | scripts/overview.py, src/overview/, coord/AGENTS_OVERVIEW.md, coord/agents_overview.json | in_progress | coord/* |
| T78 | mail-agent: send supplier emails automatically in live mode (no per-email approval, Gülşah) | mail-agent (gülşah-agent) | src/chaser/autosend.py | done | T75-T77 |
| T74 | register gate+packplan as agent tools | sonnet-wire | src/agents/tools.py, team.py, prompts.py, knowledge/, tests/test_agents_gate_tools.py, tests/agent_eval | done | T73 |
| T54 | Security and secrets sweep -> docs/SECURITY_CHECK.md (taken over: codex-overseer had not acknowledged) | isil-agent | docs/SECURITY_CHECK.md | done | - |
| T56 | Fresh-machine run on a clean Windows clone, report every missing README step (taken over: codex-access had not acknowledged) | isil-agent | docs/FRESH_RUN.md, README.md (run steps only) | done | - |
| T79-Supplier-Loop | Close game-card dock/customs and Karton small-lot decision/action loops | murat-agent | scoped chaser, orchestrator, supplier threads UI and tests | in_progress | T67 inbound, T69-Reply, T76, T78 |
| T50 | Portal watcher: sync every 10 min, post each new/changed file and the forecast change in INBOX (taken over: codex-overseer had not acknowledged for 3 h) | isil-agent | scripts/watch_portal.py | in_progress | - |
