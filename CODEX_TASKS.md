# Codex handoff — Soony "Keep the Line Running" (START Hack Munich 2026)

## Context
We play a startup selling AI agents to **Soony** (fictional games publisher). **Grand Heist 6 ships Sun 22 Nov 2026, 20:00** from DC-HAM (Hamburg). Need 640k Standard + 72k Collector's Edition (CE). At kickoff 512k STD / 46.8k CE packed. 6 suppliers (KR, CN, PL, IN, US...), data is messy and changes during the hack without notice. Judging: pitch story, business case, technical depth (real agents, tools, state, no hardcoding, copes with new data drops), taste/UX.
Submission Sun 12:00; demos from 14:00 (3 min + 2 min Q&A). Deliverables: working prototype, deck, 3-min video, code + README.

Chosen direction: **Launch Control Room + Supplier Chaser**. Agents must take real actions (decide, write, escalate), not just a dashboard.

## Layout
- `bridge/sync.py` — pulls all files via API into `data/`, tracks sha256 in `bridge/state.json`, logs to `bridge/changes.log`. Token in `.soony_token` (gitignored; never commit/print it). Re-run to detect new drops.
- `data/soony/{context,erp,logistics,master,receiving}` — Soony's own data. `data/suppliers/SUP-####_Name/` — profile, components, contracts, order_confirmations (PDF), notices.
- Read `data/soony/context/onboarding_notes.md` first.
- API: `https://start-hack-portal-cxh3crbdaef2f8gt.westeurope-01.azurewebsites.net/api/v1/` (Bearer token). Spec at `/api/v1/openapi.json`.

## Known data quirks (verify, don't trust)
- Two PO exports: `purchase_orders_2025H2-2026.csv` (comma, ISO dates) and legacy `purchase_orders_legacy_2024-2025H1.csv` (`;`, SAP field names EBELN/LIFNR/MATNR, `MM/DD/YYYY`, decimal comma, LIFNR `19` = SUP-0019, qty/status codes like `GL`).
- Supplier docs are in Korean/Chinese/Polish/English PDFs/XLSX; receiving scans are images (`receiving/DC-HAM/*.png|jpg`) booked by paper, not necessarily matching SAP goods receipts.
- `stock_snapshot.csv` shows weeks_of_cover far below safety stock for game cards; no lid magnets in stock list (open question in notes).
- `open_shipments.csv` vs `logistics/open_shipments_tracker_v37_FINAL_final2.xlsx` likely disagree.
- Supplier notices (e.g. `SUP-0028_Karton_Nowak/notices/Zawiadomienie_przestoj_techniczny_2026-11.pdf` = Polish tech downtime notice) may hide launch-critical risks.
- Hidden things exist: contradictions, single-source parts, price/contract terms, ETAs vs transit times.

## Tasks (in priority order)

### T1 — Ingestion layer (`src/ingest/`)
Normalize everything into one typed store (SQLite or DuckDB + pydantic models): POs (both formats unified), goods receipts, stock, shipments (CSV + XLSX tracker), BOM, components, suppliers, routes. Must be schema-tolerant (column renames, delimiters, encodings, date formats) and idempotent: re-run on changed files detected by `bridge/sync.py`. Emit a "what changed" diff per sync. No hardcoded column positions.

### T2 — Document extraction agent (`src/docs/`)
For PDFs/XLSX/images: OCR + LLM extraction with translation (KO/ZH/PL/EN) into structured JSON: order confirmations (PO, qty, promised date, price, conditions), notices (what, impact, dates), contracts (penalties, lead times, MOQ, force majeure, who owes whom), receiving scans (delivery note no., qty, damage). Store source file + page + quote for every field (citations). Cache by sha256.

### T3 — Truth / Readiness engine (`src/truth/`)
Compute per component and per edition (STD, CE): required qty from BOM × remaining units to pack (640k−512k, 72k−46.8k, but verify from packout_log), vs. on-hand (stock_snapshot, adjusted by receiving scans), vs. inbound (open shipments with realistic ETA = route transit + port/customs/truck lag, not the optimistic date). Output: P(ready by Sun 20:00), shortfall per component, and "what breaks first". Flag contradictions between SAP / tracker / supplier confirmations / scans, with evidence.

### T4 — Supplier Chaser agent (`src/chaser/`)
Agent with tools: draft email in supplier's language, send (SMTP/inbox — sender addresses must be registered in portal Settings; supplier contact addresses to be found in `profile.csv`/docs), parse replies, update state, escalate on timeout. Human approval gate for anything costly. Log every action. Replies come from simulated suppliers — design for async.

### T5 — Plan B / Decision Copilot (`src/decide/`)
When a gap exists: options (air freight vs sea, alt supplier, partial shipment, split CE vs STD priority) with cost, time, risk, and who signs (see `context/approval_policy_PP-07.pdf`, `org_chart_procurement.pdf`). Output a one-screen recommendation with a price for Dr. Maren Vogt. Open question: cost of a missing copy on day one (ask her in office hours).

### T6 — UI (`web/`)
Real-product feel: Launch Control Room (countdown to 22 Nov 20:00, readiness per edition, top risks), agent activity feed, supplier thread view, approval inbox, drop/changes banner. Clean consistent design; show the human decision moment clearly.

### T7 — Orchestration + drop handling
Event loop: periodically run `bridge/sync.py`, on change re-run affected extraction → truth → alerts. State persisted; agents use tools, not one giant prompt. Must visibly handle a new data drop in the demo.

### T8 — Submission assets
README, architecture diagram, 3-min demo script, backup demo video plan, business case (price per launch/supplier, other manufacturers with hard ship dates).

## Rules
- Use the data only for this hackathon; don't share outside the team.
- Never commit `.soony_token` or `data/`.
- Don't hardcode answers; everything derived from files. Cite sources for every claim.
- Keep a `FINDINGS.md` of discoveries (contradictions, hidden risks) — these feed the pitch and office-hour questions.
- Office hours (book in portal): Felix Brunner (suppliers/trucks/stock), Dr. Maren Vogt (money, priorities, sign-off), Nils Berger (data/exports, precise questions only).
