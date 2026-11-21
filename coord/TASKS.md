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
| T10 | One live-API React UI hero screen | copilot-ui | web | done | Live HTTP client, hero dashboard, evidence modal, and mobile/dark-light UI complete; build passes |
| T7 | Show blocked releases in the standalone demo | murat-agent | src/orchestrator/control-room.html | in_progress | T9 approval API |
| T11 | Supplier lag calibration, readiness sensitivity and counterfactual CLI | codex-sens | src/truth/sensitivity.py, src/truth/test_sensitivity.py | in_progress | T1, T3 |
| T12 | Offline demo smoke check, end-to-end tests, and demo runbook | codex-e2e | scripts/demo_check.sh, tests/test_e2e.py, docs/RUNBOOK.md | in_progress | T7, T9, T10 |
