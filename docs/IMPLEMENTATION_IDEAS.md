# Implementation ideas for the last 16 hours (research-impl, Sat 21 Nov ~17:30)

Tags: [V] read in this repo or on a page I opened, [S] search snippet only, [A] my judgement or memory, unverified. Not repeated here: game theory (GAME_THEORY), Lio positioning (RESEARCH_2), architecture verdict (ARCHITECTURE_REVIEW), red-team scores (REDTEAM). Already planned or built (so excluded): supply map, what-if grid (T23), trace view (T44), chaser with KO/ZH/PL drafts, supplier simulator, claims module (src/decide/claims.py), briefer (src/agents/briefer.py), harness report (docs/AGENT_EVAL.md), real mail (T26).

## 1. What others automate, and where we are different

- Pactum: chatbot negotiates autonomously within targets set by human experts; Walmart used it for small contracts, closed deals with 68% of suppliers approached and averaged 3% savings, per Pactum/Walmart reporting [S: Fortune, Retail Dive, PYMNTS snippets]. Fee reported as USD 600-6,500 per successful negotiation, from Pactum's CEO [S].
- Zip, Keelvar, Fairmarkit, Tradeshift, project44, Flexport: I did not verify any of them in this session. From memory [A]: intake and approval routing (Zip), sourcing events and bid optimisation (Keelvar, Fairmarkit), network or carrier tracking (project44, Flexport). Do not cite specifics on a slide.
- Our defensible difference [A]: those tools mostly act on data inside their own system. Our finding is the opposite: the damage sits in contradictions between the ERP, scans, contracts and tracker (art book 80,000 vs 8,000, failed statue lot, tracker says in transit but cargo is at the terminal). Lead with "we read the 80% outside the system of record" (Lio's own phrase per RESEARCH_2), then show an agent that acts on it.
- Techniques usable in hours:
  - Conformal predictive distributions for fulfilment time: arXiv 2505.17340 and Kinaxis-linked delay-duration paper arXiv 2602.20271 [S]. Needs a calibration set; we have 25 shipments and few PO histories, so claim only "calibrated against PO history" if reliability.py really does it. Do not present conformal coverage.
  - Counterfactual explanation: "smallest change that flips HOLD to GO". We already have `counterfactual()` in src/truth/sensitivity.py, so this is cheap and is the best explanation device.
  - LLM-as-judge: our verifier already is one; the upgrade is to publish its pass rate (idea 5).
  - Evidence graph: finding -> quote -> file/page. Provenance already exists; drawing it is the cost.

## 2. Ranked ideas (impact x feasibility)

### A. Release Gate: what may safely go into the box (build now)
- What: for every BOM component of FG-GH6-STD/CE return GO / HOLD / HUMAN with a one-line reason and quote. Rules, all derivable from files I read [V]:
  1. Artwork revision: components.csv says CMP-GAM-004 drawing_rev B; SUP-0029 order confirmations print rev B, SUP-0028 prints rev C (FINDINGS). Karton prints to "last revision released in writing", PackRight to the revision in the master at PO date (FINDINGS). Gate: HOLD sleeve until a rev is confirmed; this is a real USK/PEGI-labelled part, so say "possible stale artwork", not "wrong".
  2. Quality: statue lot 5,600 pcs, 9/125 defective vs accept limit 3, booked unrestricted -> exclude from usable stock, HOLD.
  3. Magnet: CMP-MAG-005 has 0 stock and 100,800 need, but PackRight fits magnets in CMP-GAM-007 -> "BOM likely double counts, confirm with Felix". Gate returns HUMAN, never GO.
  4. Conditional supplier: Pune statues need PPAP plus written release by Supplier Quality and Category Lead, a vacant role -> HUMAN with named missing signer.
  5. Incoterm conflict (8 POs, DDP in ERP vs EXW on confirmations) -> HOLD freight claim.
  Labelling beyond the sleeve: no data found, so do not invent a labelling check.
- Why judges care: technical depth (cross-source reasoning, nothing hardcoded if rules read tables), pitch (one answer to "can we ship the box?"), taste (green/amber/red per part), brief direction 7.
- Plan: new `src/decide/release_gate.py` (pure functions over truth + docs tables; each rule returns status, evidence list reusing `search_documents` hits); expose as tool `release_gate` in src/agents/tools.py and `GET /api/gate` in src/orchestrator; one table in web with expandable quote. Add 4 tests (one per rule) and a harness scenario.
- Effort 4-5 h. Demo (20 s): drop a new inspection report; the statue row flips from GO to HOLD with the quote. Risk: rules look hardcoded; mitigate by driving thresholds from parsed fields (AQL limit from the report). Copilot can build it given the rule list above.

### B. Obligation ledger (contract intelligence, "who owes whom") (build now, merge into A's UI)
- What: per supplier, clauses extracted as {obligation, party, trigger, remedy, quote, page} and joined to live events. Known [V]: Karton contract s3.2 promises 50,000 pieces in 36 h at +35%, but the 9 Nov notice says digital line only, max 15,000 per 36 h and art book is outside the rush clause; PackRight force majeure explicitly covers rare-earth export limits, so no remedy for Soony; price-fixed-for-calendar-year clause vs the 2025 +4% notice. Output: "Karton owes us up to 50,000 in 36 h; they say 15,000: contractual argument, not capacity" as an evidence card feeding the chaser ladder.
- Why: business case (claims recovery is cash), depth. Plan: `src/docs` already extracts text; add `src/decide/obligations.py` (LLM extraction with quote validation, reusing reader pattern, results cached as JSON so demo is offline) plus a search box over clause text. Effort 4 h. Demo: type "force majeure" and see the six suppliers' clauses ranked; click the Karton card and the chaser draft cites s3.2. Risk: only 6 contracts, so "intelligence" is thin; frame as depth on a few. Copilot: yes.

### C. Self-evaluation page (build now, cheapest credibility)
- What: web tab rendering docs/AGENT_EVAL.md data: scenario, runs, pass rate, per-guard rule, failing evidence, live vs fake LLM. The existing table shows 6 scenarios at 1 run each, all 100% [V]. That is N=1; run each live 5 times first (cost about USD 0.09 per run per overview) and report honest rates, including any failures with the fix.
- Why: technical depth and honesty; counters REDTEAM "script with a UI". Plan: `scripts/eval_run.py` writes tests/agent_eval/results.json; `web/src/EvalPage.tsx` reads it (static in hosted mode). 2-3 h. Demo: a red row "hallucinated_number: BLOCKED by numeric_grounding" is the money shot. Risk: a live failure; then show it fixed, which is a better story. Copilot: yes.

### D. Tracker truth check using routes and ports (build now, small)
- Data [V]: routes.csv gives transit_days per route (e.g. RT-001 Busan-Hamburg 36 d via Singapore, RT-003 Nhava Sheva 24 d), ports.csv has coordinates, open_shipments has etd, eta, status, last_lat/lon, updated_at, and notes ("discharged at CTA Hamburg, available for pick-up").
- What: per shipment flags: (etd + transit_days) vs stated eta (plan inconsistency), position-vs-status contradiction (status in_transit but coordinates equal DEHAM), stale updated_at, ERP shipment missing in tracker xlsx (14 of 25 [V]). Output: "7 shipments you believe are moving are waiting; 11 invisible". Pure geometry, no model.
- Why: brief direction 5, taste (map already exists, add red rings), depth. Plan: `src/truth/tracker_check.py` + feed into network payload so SupplyMap draws rings; 3 h. Demo: ring pulses on Hamburg; click -> "350,000 cases collectable today, tracker says in transit". Risk: whether cases are collectable is unconfirmed (open question for Felix); word it "at terminal per tracker note". Copilot: yes. Skip conformal ETA here: 25 shipments cannot calibrate.

### E. 20-second buyer mode (build now, 1.5-2 h)
- What: one button, three sentences: what is wrong, what it costs, what I need from you, then speech via browser `speechSynthesis` (voice for free, one hour). Built on src/agents/briefer.py; every number must pass the numeric_grounding guard, same harness. Demo: press button, hear the answer, numbers highlight with source. Risk: robotic voice; keep text on screen. Copilot: yes. This is also the cheap answer to the voice question.

### F. Evidence pack per claim (maybe, 3 h)
- Extend src/decide/claims.py: one-click bundle (markdown/PDF) per supplier issue: PO, GR, delivery note page, contract clause, drafted claim letter in supplier language, unsigned. Why: business case (recoverable money). Needs the claim value, which depends on unconfirmed facts; show only quantities. Demo: pack appears with five linked sources. Risk moderate: overlaps B. Do after A and B if time.

### G. Negotiation what-if sandbox (maybe, 4 h)
- What: replay the chaser ladder against suppliers_sim personas N times with varied persona parameters and show distribution of rungs reached and commitment scores. Why: depth. Risk high: the simulator is our own code, so a judge will say circular; label strictly "rehearsal, not forecast". If built, show as a table inside the trace view, not a headline. Copilot: yes, but low marginal win.

### H. Evidence graph view (maybe, 3 h)
- Finding -> claims -> quote -> file nodes with d3 (d3-geo already in web). Pretty and on message for provenance; but a collapsible quote under each row (A, B) delivers 80% of it.

### I. Skip
- Real phone-call voice agent: telephony, consent and latency risk in 16 h; I have not verified what the brief permits beyond your statement. Use E instead.
- Cross-supplier substitution/Plan B search: data shows single sources (steel case, art book, poster, leaflet) and Pune conditional [V]; a search would mostly return "none", which is itself a finding. Fold that sentence into A rule 4 instead of building a search.
- Multilingual inbox loop: already built (chaser, T26); spend time rehearsing one round trip, not new code.
- Conformal ETA bounds: no calibration data; skip.

## 3. Build now / maybe / skip

| Idea | Verdict | Hours | Win impact | Feasibility | Copilot |
|---|---|---|---|---|---|
| A Release Gate | Build now | 4-5 | High | High | Yes |
| C Self-eval page | Build now | 2-3 | High (depth, honesty) | High | Yes |
| E 20-second mode + speech | Build now | 1.5-2 | Medium-high (demo) | High | Yes |
| B Obligation ledger | Build now | 4 | Medium-high | Medium | Yes |
| D Tracker truth check | Build now (small) | 3 | Medium | High | Yes |
| F Evidence pack | Maybe | 3 | Medium | Medium | Yes |
| G Negotiation sandbox | Maybe | 4 | Low-medium | Medium | Yes |
| H Evidence graph | Maybe | 3 | Low-medium | Medium | Yes |
| Voice phone agent | Skip | 8+ | Medium | Low | No |
| Substitution search | Skip | 4 | Low | Low (no data) | n/a |
| Conformal ETA | Skip | 5 | Low | Low | n/a |

## 4. If only three: A, C, E

1. Release Gate (A): the clearest "agent decides what may ship" moment, uses the verified findings, rules visibly derived from tables and quotes.
2. Self-evaluation page (C): converts "trust us" into measured pass rates and shows a blocked hallucination live; directly answers the red-team charge of a scripted pipeline.
3. 20-second buyer mode (E): the pitch moment a jury remembers, with grounded numbers, spoken.
D and B are next if a human has spare hours; B overlaps A's UI so one person can do both.

## 5. Uncertainties

- I did not open the contract PDFs; clause facts come from FINDINGS.md, written by earlier agents, so recheck page numbers before showing them (T22 verification sweep).
- Pactum numbers are snippets, not pages read. Other vendors unverified.
- Hour estimates assume the tool layer (T39) and wiring (T47) are stable; if the harness fails live, do C first.
- Business-case numbers remain blocked on Dr. Vogt (18:00); none of these ideas fixes that, so ask him for the cost per missing copy before anything else.
