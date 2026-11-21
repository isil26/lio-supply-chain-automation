# TASKS board (specs in CODEX_TASKS.md). Status: open | in_progress | review | done | blocked
| ID | Task | Owner | Dir | Status | Depends on |
|---|---|---|---|---|---|
| T1 | Ingestion layer -> store/soony.db | Codex | src/ingest | review | - |
| T2 | Doc extraction (OC pdf, delivery-note images, notices, contracts) with provenance | Codex #2 | src/docs | done | FINDINGS formats |
| T3 | Readiness engine (BOM/MRP netting, Monte Carlo, criticality, usable-stock adjustments) | Claude | src/truth | in_progress | T1 (can start on CSVs) |
| T4 | Supplier Chaser (multilingual drafts, approval gate, reply parsing, escalation) | Copilot #2 | src/chaser | done | T2 |
| T5 | Plan B / decision copilot (option enumeration, cost vs P(on time), approval policy PP-07) | Codex | src/decide | done | T3 |
| T6 | UI Control Room | Copilot | web | review | contract in DECISIONS.md |
| T7 | Orchestrator + drop handling (sync -> reingest -> re-evaluate) | Codex | src/orchestrator | done | T1,T3 |
| T8 | Submission: README, deck outline, demo script, business case | Codex | docs/ | done | - |
