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

| T5 | Pair Plan B offer forecasts and verify usable and late offers | murat-agent | src/decide forecast helper and regression | in_progress | T11, T32 |
| T33 | Shared LLM client: schema + quote validation, cache, budget, cost log, fallback, `python3 -m src.llm.check` live proof, env-name fix | copilot-llm | src/llm, glue in src/docs/providers.py, src/chaser/llm.py | in_progress P1 | docs/ARCHITECTURE_REVIEW.md B |
| T34 | State hardening: WAL, sync outside cycle lock, /api/health, regression tests | copilot-state | src/orchestrator, src/chaser/store.py, src/ingest/store.py | in_progress P1 | docs/ARCHITECTURE_REVIEW.md E |
| T35 | Triage agent (orchestrator-workers, closed tool whitelist, <=3 rounds, falls back to fixed order) | open P1 | src/agent | T33 |
| T36 | Fallback extractor + coverage contract (full/partial/none) + review queue incl. .eml | open P1 | src/docs | T33 |
| T37 | LLM-drafted chaser emails with validator and template fallback | open P2 | src/chaser | T33 |
| T38 | Multi-agent runtime: tool-calling ReAct loop, Anthropic + OpenAI-compatible adapters, record/replay cassettes, Team with delegate + blackboard + mailbox, trace to activity feed, human-gate primitive | copilot-runtime | src/agents/runtime.py, llm_adapter.py, trace.py | in_progress P1 | - |
| T39 | Tool layer wrapping existing deterministic code (readiness, whatif, search_documents, compare_sources, breakeven, draft/send/parse, propose_option, escalate_to_human, request_review) | copilot-tools | src/agents/tools.py | in_progress P1 | - |
| T40 | The agents: Triage/Orchestrator (plans, delegates), Analyst (finds and explains gaps with citations), Verifier (checks every claim against quotes, rejects unsupported), Planner (Plan B options with cost), Chaser agent (autonomous ladder: draft, wait, parse reply, escalate). System prompts, tool whitelists, hand-offs | open P1 | src/agents/*.py | T38, T39 |
| T41 | Autonomy loop: on a data-drop event the Triage agent runs; timers advance the chaser ladder; approval queue; kill switch; budget cap per cycle; replay from cassettes for a reliable demo; wire into src/orchestrator behind SOONY_AGENTS=1 with the old pipeline as fallback | open P1 | src/orchestrator (small), src/agents/loop.py | T40 |
| T42 | Simulated supplier agents: LLM personas per supplier (language, private capacity/ETA, reliability from history, deliberately vague or late replies) that answer drafted emails; makes the whole multi-agent loop testable without real email, also a demo fallback | open P1 | src/agents/suppliers_sim.py | T38 |
| T43 | Test runs with a real API: scripted scenarios (art-book shortfall, quality hold, game-card short-ship, unseen German notice), run each 3-5 times, record cassettes, measure success rate, tool-call correctness, hallucinated numbers (must be 0), cost and latency; report in docs/AGENT_EVAL.md | open P1 | tests/agent_eval/, docs/AGENT_EVAL.md | T40, API key |
| T44 | UI: multi-agent trace view (who called which tool and why, hand-offs between agents, approvals waiting) in React + standalone page | open P2 | web/ | T38 trace format |
