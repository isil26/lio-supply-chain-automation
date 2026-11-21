# HANDOFFS — when a task ends: what you built, how to run it, known gaps, next step.

## T4 — Supplier Chaser (Copilot #2)

- Built in `src/chaser/`: structured issue model, profile-derived supplier language and contact, multilingual draft templates, guardrails, SQLite thread/message/reply/action state, approval gate, dry-run/mock/SMTP outboxes, mock inbox, deterministic reply LLM, and CLI.
- Run: `python3 -m src.chaser.run --help`; tests: `python3 -m unittest src.chaser.test_chaser` (7 passing).
- Default sending is dry-run. Mock sends are available for demo. Real SMTP requires `CHASER_REAL_SMTP=1` plus `CHASER_SENDER` and SMTP environment settings.
- Pending/approved/sent state and all action records persist in `store/chaser.sqlite`.
- Handoff: T7 can call `src/chaser.run` or import `SupplierChaser`; T6 can consume thread/list/log state, but no external API wrapper was added in T4.
