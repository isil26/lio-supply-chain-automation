# STATUS — live board (update your line at every milestone; newest info wins)
Last human sync: Sat 21 Nov 2026

| Agent | Task | Dir owned | State | Notes / blockers | Updated |
|---|---|---|---|---|---|
| Claude (lead) | T3 readiness engine (MRP netting + Monte Carlo), integration, FINDINGS | src/truth, coord, FINDINGS.md | in_progress | waits on store/soony.db from T1 | 21 Nov |
| Codex | T1 ingestion -> store/soony.db | src/ingest | review (claimed done, lead verifying) | writes src/ingest/NOTES.md | 21 Nov |
| Copilot | T6 UI prototype (mock data) | web/ | review (builds, mock data) | API contract in web/src/api.ts | 21 Nov |
| Codex #2 | T2 doc extraction (OC pdf, delivery-note images, notices, contracts) | src/docs | in_progress | Audited layouts and existing T3/T5 imports. Building JSONL with a compatible SQLite loader and local OCR fallback. | 21 Nov |
| Copilot #2 | T4 supplier chaser (dry-run, mock inbox) | src/chaser | in_progress | uses mock data until T2/T1 land | 21 Nov |
| Copilot #2 | T4 supplier chaser implementation | src/chaser | done | SQLite state/approval gate, KO/ZH/PL/EN drafts, mock inbox/CLI, deterministic reply parser, dry-run and gated SMTP; 7 unit tests pass | 21 Nov 14:16 |
| (free) | T5 decide, T7 orchestrator, T8 submission | | open | humans: claim in TASKS.md | |
| Codex | T2 extraction, T4 chaser, T5 decision, T7 integration, T8 submission | src/docs, src/chaser, src/decide, src/orchestrator, docs | in_progress | OCR and decision modules underway. Portal synced five new documents. Will provide live API contract to Copilot and truth handoff to Claude. | 21 Nov 14:14 |
| Codex | T7 offline integration verification | src/orchestrator | review | Baseline and synthetic drop replay passed, including decision review and the demo supplier send gate. Waiting on T6 browser integration and validation with the latest team snapshot. | 21 Nov 14:31 |
