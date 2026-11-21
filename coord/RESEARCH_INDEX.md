# RESEARCH INDEX — read before researching anything. Add a row when you start, update when done.
Rule: if a topic is listed as DONE, read the file instead of researching again. If listed as GAP, do not re-search it; ask a human (office hours) or accept the gap. Confidence: [V] opened and read, [S] search snippet only, [A] judgement.

## Done (read these first)
| Topic | File | Key takeaways | Owner |
|---|---|---|---|
| Methods, papers, architecture, winning demos (first pass) | docs/WIN_PLAN.md | Deterministic tools produce numbers, LLM reads/drafts; Monte Carlo + MRP; plan B by enumeration; provenance on every field; demo moves (live drop, click-through source, what-if slider) | research (1st agent) |
| Lio positioning, papers, business-case anchors (second pass) | docs/RESEARCH_2.md | Lio phrases ("virtual procurement department", "edge cases included", "agents execute, humans approve", "80% of work outside the system of record"); 5 verified papers incl. arXiv:2610.38046 (conformal order fulfilment + cost decision); air vs sea about 6.6x-16x cost; 10 pitch changes + 10 judge questions | research |
| Verified data findings (shortfalls, contracts, formats) | FINDINGS.md | Art book 80,000 vs 8,000 booking error, statue lot failed AQL, game card air lot 28,000 of 48,000, magnets fitted by box supplier, Karton downtime, price drift | nick + subagents |
| Frozen numbers for pitch | docs/NUMBERS.md | Single source for deck/demo/video | nick |
| Forecast sensitivity + supplier lateness calibration | src/truth/sensitivity.py (run `python3 -m src.truth.sensitivity`) | Game card first stop in 88% of trials; calibrated CE median 66,100 differs from NUMBERS.md 62,550 (unresolved, see coord/INBOX.md) | codex-sens |

| Game theory for chaser and expedite decision (cheap talk vs verifiable commitments, R0-R4 escalation ladder, expedite break-even L* = C/(Q*dP)). Author/paper names are from memory, UNVERIFIED, do not put on slides | docs/GAME_THEORY.md | research-gt |
| Red team: pitch 6 / business case 4 / depth 6 / taste 7, hook 'SAP says fine' is false (SAP hides art book + statue gaps), 15 Q&A, 5 demo failure modes, cut list | docs/REDTEAM.md | redteam |

## In progress (do not duplicate)
| Topic | Output file | Owner |
|---|---|---|
| Hidden findings hunt: artwork rev B vs C, Incoterms DDP vs EXW, 78k pins without PO, cancellations, stale stock counts, magnets, contract clauses | docs/HIDDEN_FINDINGS.md | codex-hunter |
| Surprise-drop robustness: unseen formats, encodings, languages, corrupt files | docs/DROP_ROBUSTNESS.md, tests/drops/ | codex-drops |
| Comparable procurement systems and scientific methods for evaluating recovery decisions. First pass covers paired simulations and correction ordering. Share findings and experiments through the team inbox. | coord/INBOX.md | codex-methods |

## Known GAPS (not found publicly or not answerable from files; do not re-search)
- Dr. Vogt's cost per missing copy / penalty per missed day: NOT in data ("ask me at the booth"). Office hours only.
- Lio pricing and ROI: Lio publishes none. Only self-reported claims [S]. Software price anchors (Zip/Coupa/Ariba about $73-93k/yr) are weak third-party sources [S].
- BMW/Siemens/ZEISS as Lio customers: in the brief but not verifiable on lio.ai [V]. Verified named customers: tesa, BASF Coatings, Novonesis, Schaeffler, Bilfinger. Do not name unverified ones.
- START Hack / Hack League judge feedback: nothing public found except the 2026 winner reportedly judged on "completeness, usability, storytelling" [S].
- Papers: none found on multilingual extraction WITH citations, none on expediting as such. Say so if asked.
- Stockout cost in consumer electronics/games and game-retailer penalties: not found. Needs Dr. Vogt or an explicit assumption.
- Lio team size conflict (YC 80 vs careers 135): unresolved, unused.
- Pages that returned 403 (Surventis, LeanDNA survey, Vendr/Zip price): numbers from them are snippet-only [S].

## Open data questions (office hours, humans only)
- Vogt: cost of one missing Collector's Edition; remaining air-freight budget; who signs air freight and a statue concession while the Category Lead is vacant.
- Brunner: are the 350k cases at CTA and collectable today; status of the dock-held game-card lot; is the lid-magnet BOM line real; can Karton split a finished-goods lot.
- Berger (precise only): why the tracker omits 11 of 25 ERP shipments; which stock field shows whether a goods receipt is already included.
