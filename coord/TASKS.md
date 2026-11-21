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
