# DECISIONS (append only; date + who)
- 21 Nov: Direction = Launch Control Room + Supplier Chaser + Plan B. (team)
- 21 Nov: Deterministic tools produce numbers; LLM does extraction/drafting/explaining. (Claude, from research)
- 21 Nov: Shared store = `store/soony.db` (SQLite/DuckDB, built by src/ingest). Canonical IDs: SUP-####, CMP-XXX-###, FG-*, DC-HAM. Supplier/part code mappings: see private/ (team-shared, not in git).
- 21 Nov: Extracted facts carry provenance {value, source_file, page, quote, confidence}.
- 21 Nov: Launch deadline constant: 2026-11-22T20:00:00+01:00 (Europe/Berlin).
- 21 Nov: "Usable stock" != ERP stock (art book 80k booking error, statue lot failed AQL); engine must adjust and show why.
- 21 Nov 14:14, Codex: Local Python API on 127.0.0.1:8787 serves the React build and JSON. GET /api/dashboard, GET /api/truth, GET /api/documents, POST /api/sync, POST /api/decisions/{id}/{approve|review}, POST /api/threads/{id}/send. Approve records permission to prepare a quote/review. Actual supplier outreach has its own draft-specific confirmation and defaults to dry-run.
