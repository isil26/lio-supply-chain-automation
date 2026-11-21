# STATUS — live board (update your line at every milestone; newest info wins)
Last human sync: Sat 21 Nov 2026

| Agent | Task | Dir owned | State | Notes / blockers | Updated |
|---|---|---|---|---|---|
| nick | T3 readiness engine (MRP netting + Monte Carlo), integration, FINDINGS | src/truth, coord, FINDINGS.md | in_progress | waits on store/soony.db from T1 | 21 Nov |
| Codex | T1 ingestion -> store/soony.db | src/ingest | review (claimed done, lead verifying) | writes src/ingest/NOTES.md | 21 Nov |
| Copilot | T6 UI prototype (mock data) | web/ | review (builds, mock data) | API contract in web/src/api.ts | 21 Nov |
| Codex #2 | T2 doc extraction (OC pdf, delivery-note images, notices, contracts) | src/docs | done | Published 282 docs. Verified SQLite load, byte-identical cached rerun and the art-book handwriting correction. Eight receiving scans flagged for review. | 21 Nov |
| Copilot #2 | T4 supplier chaser (dry-run, mock inbox) | src/chaser | in_progress | uses mock data until T2/T1 land | 21 Nov |
| Copilot #2 | T4 supplier chaser implementation | src/chaser | done | SQLite state/approval gate, KO/ZH/PL/EN drafts, mock inbox/CLI, deterministic reply parser, dry-run and gated SMTP; 7 unit tests pass | 21 Nov 14:16 |
| (free) | T5 decide, T7 orchestrator, T8 submission | | open | humans: claim in TASKS.md | |
| Codex | T2 extraction, T4 chaser, T5 decision, T7 integration, T8 submission | src/docs, src/chaser, src/decide, src/orchestrator, docs | in_progress | OCR and decision modules underway. Portal synced five new documents. Will provide live API contract to Copilot and truth handoff to Claude. | 21 Nov 14:14 |
| murat-agent | T7 offline integration verification | src/orchestrator | done | Clean replay and replay with a pre-fix OCR cache passed on 7c7a7f1. The receipt correction restores the art-book gap and the supplier drop produces the recovery option. | 21 Nov 15:03 |
| murat-agent | T7 drop banner | src/orchestrator | done | Fix is on main at 0f53e76. Latest replay shows both shipment alerts and the shortfall change. React validation is with T10. | 21 Nov 14:47 |
| copilot-deck | T8 pitch deck | docs/deck | done | Built docs/deck/index.html (6 slides, keyboard nav, 16:9, print CSS, inline SVG, dark design system), SPEAKER_NOTES.md, and README.md. Uses only frozen NUMBERS.md figures. | 21 Nov 14:50 |
| Codex | T2 extraction, T4 chaser, T5 decision, T7 integration, T8 submission | src/docs, src/chaser, src/decide, src/orchestrator, docs | in_progress | OCR and decision modules underway. Portal synced five new documents. Will provide live API contract to Copilot and truth handoff to Claude. | 21 Nov 14:14 |
| Codex | T5 decisions, T7 live integration and replay, T8 submission | src/decide, src/orchestrator, private/submission | done | Live UI, real file drop, dry-run send, simulated reply and approval verified in browser. Deck and narrated MP4 delivered privately. | 21 Nov 14:35 |
| copilot-ui | T10 live React control-room hero | web | done | Completed live `/api/dashboard` client, Vite `/api` proxy, readiness probability/range bars, SAP-vs-reality risk cards, evidence modal, activity feed, thread send states, approval actions, and data-drop sync. `npm --prefix web run build` passes. No commit/push. | 21 Nov 14:46 |
| Codex #3 | T9 technical depth | src/truth, src/docs, src/decide, src/orchestrator | in_progress | Verified the three receipt scans and PP-07 release and exception clauses. Implementing the cited feed, receipt fixes, approval gate and numbers export. | 21 Nov |
| murat-agent | T7 React demo route | src/orchestrator | done | Root route fix is on main at d181fe3. Built live React from 7c7a7f1 and verified the recovery card and price after Process drop in the browser. | 21 Nov 15:03 |
| Codex #3 | T9 technical depth | src/truth, src/docs, src/decide, src/orchestrator | in_progress | Verified the three receipt scans and PP-07 release and exception clauses. Implementing the cited feed, receipt fixes, approval gate and numbers export. | 21 Nov |
| codex-truth | T9 technical depth | src/truth, src/docs, src/decide, src/orchestrator | in_progress | Private replay reports zero receipt-scan issues, preserves art-book stock correction, and exposes the blocked Pune release. Testing quote validation and the approval endpoint. | 21 Nov |
| murat-agent | T7 standalone approval controls | src/orchestrator/control-room.html | done | Real replay verified persisted review and a separate art-book quote action. Kept the concurrent T9 UI implementation and added explicit blocked review feedback. | 21 Nov 15:10 |
| codex-truth | T9 technical depth | src/truth, src/docs, src/decide, src/orchestrator | in_progress | Private replay reports zero receipt-scan issues, preserves art-book stock correction, and exposes the blocked Pune release. Testing quote validation and the approval endpoint. | 21 Nov |
| codex-truth | T9 technical depth | src/truth, src/docs, src/decide, src/orchestrator | done | All 34 tests pass. Verified zero receipt-scan issues, cited Pune block, live numbers and model quote checks with test responses. Live Ollama verification is pending on a machine with models. | 21 Nov |
| codex-sens | T11 readiness sensitivity | src/truth/sensitivity.py, src/truth/test_sensitivity.py | done | Calibration, paired sensitivity, Plan B and CLI complete. Six focused tests and 40 repo tests pass. Live 500-trial CLI takes under a second. | 21 Nov |
| codex-e2e | T12 demo hardening | scripts/demo_check.sh, tests/test_e2e.py, docs/RUNBOOK.md | done | Real in-process replay passed all API assertions. Full subprocess check requires a terminal that permits loopback bind. | 21 Nov |
| murat-agent | T7 demo database initialization | src/orchestrator/__main__.py | done | Initializes SQLite before startup and reads replay state consistently. Full loopback smoke test passed in 32 seconds including dry-run supplier send. | 21 Nov 15:15 |
| copilot-ui | T10 static replay | web | done | Added Vercel static replay fallback, localStorage state, drop/review/approve/send/reply/reset controls, snapshot badge and static evidence; live API remains intact. | 21 Nov 15:16 |
| codex-hunter | T13 hidden findings hunt | docs/HIDDEN_FINDINGS.md | in_progress | verifies artwork rev B/C, Incoterms, pins w/o PO, cancellations, stale counts, magnets, contract clauses | 21 Nov |
| codex-drops | T14 surprise-drop robustness | tests/drops, docs/DROP_ROBUSTNESS.md | in_progress | tries unseen formats/languages/encodings/corrupt files on a disposable db; proposes fixes to codex-truth via INBOX | 21 Nov |

