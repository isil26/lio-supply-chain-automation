# WIN PLAN (Team Manti) - research + punch list

## 1. Lio in their own words (so we speak it)
- Lio: "World's first multi-agent system for direct and indirect Procurement", "virtual procurement department", "Edge cases included", "Stop experimenting with AI and start working with it", "creates value on day one". Agents "execute the workflow themselves" instead of assisting humans (CEO Vladimir Keil). Agents do matching, supplier chasing, exception handling, negotiation prep. Sits on top of existing ERPs. https://www.lio.ai , https://techcrunch.com/2026/03/05/lio-ai-series-a-a16z-30m-raise-automate-enterprise-procurement/
- Funding: $30M Series A led by a16z (Mar 2026), ~$33M total, YC S23. Claims "175+ large enterprises"; named on site: tesa, BASF Coatings, Novonesis, Schaeffler, Bilfinger. I could NOT verify BMW/Siemens/ZEISS publicly - do not name them in the pitch unless a Lio person says so.
- ROI: Lio publishes no pricing and no hard ROI number on its site; only "weeks to minutes" and one unnamed manufacturer automating 75% of outsourced procurement ops in 6 months (self-reported).
- Pitch wording to borrow: "agents execute, humans approve", "edge cases included", "virtual procurement department", "SAP-side truth vs real-world truth". Frame us as a Lio-style agent for the exception layer: the launch-critical 5% of lines where ERP lies.

## 2. Business-case benchmarks (all consultant/vendor claims, uncertain)
- McKinsey: agentic AI typically 3-6% of addressed external spend; pilots 20-30% staff efficiency; only ~2% at scale. https://www.mckinsey.com/capabilities/operations/our-insights/agentic-ai-in-strategic-sourcing-hype-or-hero
- BCG: 8-15% cost savings, OTIF +5-15 pts, sourcing cycle -30-60%. https://www.bcg.com/publications/2026/ai-in-procurement-drives-competitive-advantage
- Bain: 3-7% incremental savings, 60%+ productivity. https://www.bain.com/insights/the-rise-of-autonomous-intelligent-procurement/
- These are SAVINGS benchmarks; our value is AVOIDANCE (missed ship date, expediting). More relevant: LeanDNA survey (vendor): 84% of manufacturers had 2+ shortages in 12 months, expediting top immediate cost (37%) https://www.sdcexec.com/sourcing-procurement/manufacturing/news/22964498/leandna-supply-chain-failures-occur-at-factoryspecific-execution-stage-leandna ; APQC: 1-day vs 1-month impact identification = $16.05 vs $19.57 procurement cost per $1,000 revenue; 46% need a week+ https://www.sdcexec.com/safety-security/risk-compliance/article/22915184/apqc-the-need-for-speed-in-the-face-of-supply-disruptions ; McKinsey via Wiss: up to 50% of expedited shipments preventable https://wiss.com/supply-chain-visibility-financial-impact-manufacturing/ (secondhand). Safest line: use our own data (EUR 1.52M + 0.87M of finished goods at risk at std cost) plus ONE cited stat, flagged "industry survey".
- START Hack / Hack League judging: search found nothing public beyond the brief. Do not assume weights; rely on the four criteria given. Generic winning pattern (my judgement, not sourced): one sharp story, live demo that works, a visible number, a "why now / who pays" answer.

## 3. Review against the four criteria (from repo state)
- Pitch: strong hook and one real insight ("SAP vs reality"). Weak: no quote or story from Soony staff yet; Vogt's cost-per-copy is still [A]. Doc has two versions of numbers (PITCH_3MIN says game card ~6,800 gap and "case 0"; DEMO.md leads with 5,900 / 3,400 / 20k balance) - unify.
- Business case: pilot EUR 12k/launch is an unvalidated guess; break-even maths is honest but thin; no "who else" beyond one list.
- Technical depth: good (SHA-256 drop sync, OCR + cited facts, Monte Carlo, chaser with approval gate, replay mode). Risks: many findings still AGENT-reported not verified; LLM is optional/local so judges may ask "where is the AI?"; FINDINGS magnets conflict (BOM double count vs total CE stop) unresolved.
- Taste: control-room.html is a single dark page; README links point to private/ files. Needs one clean hero screen.

## 4. Top 10 punch list (next ~20h, in priority order)
1. Freeze ONE number set. One owner reconciles PITCH_3MIN / DEMO / dashboard so demo, deck, video say identical figures (art book 5,900, statue 3,400, ...). Verify the AGENT-only claims you will show on stage against raw files.
2. Use office hours to get 3 facts (section 6) and put them on slide 1 and the business slide as "Soony told us". This is a stated judging item.
3. Make the live demo a single 90-second loop: drop lands -> agent detects change -> readiness drops/rises -> chaser drafts Polish/Korean mail -> human approves under PP-07 -> reply parsed -> decision card with price. Rehearse 10x with a timer; cut anything else (no tour of all 25 shipments).
4. Show agent autonomy visibly: a "what the agent did / why / what it escalated" activity feed with tool calls and citations; explicit escalation case (Pune statue release blocked: Category Lead vacant, so route to Head of Procurement). That answers "agents decide, write, escalate".
5. Show nothing-hardcoded: during the demo, drop a NEW unseen file (not the staged one) if feasible, or at least say replay uses real held-back portal files.
6. Make the LLM role explicit and working: have at least one hosted/local model step live (handwriting-correction read, Polish email understanding) with quote validation. Judges will probe "is it just regex?".
7. Business slide rebuilt: Soony's cost of a missed copy (from Vogt) x gap units -> value at stake; price as % of that; 3 adjacent buyers (consoles/collectibles, consumer electronics launches, seasonal retail); positioning "exception layer on top of SAP/Lio-style procurement". Cite one benchmark, flag as vendor-sourced.
8. Taste pass: one hero screen (readiness gauge, top 3 breaks, activity feed), consistent type/colour, no raw JSON, no debug labels; deck 6 slides max.
9. Submission hygiene by Sun 12:00: README run steps tested on a clean checkout (Tesseract langs!), fix README links to private/ files, <=3 min video (existing MP4: re-record if numbers changed), deck PDF, no .soony_token in the repo (check .gitignore).
10. Rehearsal and roles: one speaker, one driver. Run the full 3+2 twice with a stranger asking Q&A; offline fallback (video) one keypress away; laptop on power, local server started 30 min before.

Cut: portal live polling on stage, real SMTP, React prototype if the HTML control room is the demo (pick one UI), the long forecast methodology.

## 5. Judge Q&A (12) with answers
1. Why not just use SAP/Lio? - SAP is correct about what was booked, wrong about what is true: 80,000 art books booked vs 8,000 on the note. We are the exception layer on top, reading what ERP never ingests.
2. Where is the AI, not just OCR? - LLM reads Polish/Korean/Chinese notices, handwriting, replies; drafts mails; every extracted fact must quote its source; numbers come from deterministic MRP/simulation tools.
3. Is anything hardcoded? - Inputs are the portal files, hash-diffed; the replay stages real held-back files; a new drop reruns ingestion, readiness and decisions. Offer to drop a file live.
4. How do you stop hallucinations? - Quote validation, confidence and source page on each fact, human gate on every send and purchase commitment.
5. Who pays and how much? - Launch/programme owner with an emergency budget; EUR 12k per hard-date launch pilot [hypothesis, to validate with Maren]; break-even 600 saved copies at EUR 20.
6. Cost of a missed copy? - Use Vogt's number; fallback: goods at stake EUR 1.52M Standard + 0.87M CE at std cost, 2 weeks before Christmas.
7. Who else has this problem? - Any fixed-date launch with multilingual paper suppliers: consoles, collectibles, consumer electronics, seasonal retail. Survey data: 84% of manufacturers had 2+ shortages a year (vendor survey).
8. What if your forecast is wrong? - Probabilities are scenario frequencies under stated assumptions; we show assumptions and let buyers override; the product is the evidence trail, not an oracle.
9. Why trust handwritten-scan reading? - Show the scan and the quote side by side; eight scans flagged for human review rather than guessed.
10. Autonomy vs approvals? - Agent drafts and routes; PP-07 limits (buyer <50k, category lead <500k, head <2M) decide who approves; vacant Category Lead handled by escalation.
11. Security/data? - Loopback API, data stays local, optional local model, no credentials in repo; EU deployment story.
12. What would you build next / scale? - Ingest supplier email/IMAP live, per-supplier reliability learning, multi-site; moat = cross-customer supplier-behaviour benchmarks (Lio claims the same kind of market intelligence).

## 6. Exactly 5 office-hours questions (10 min)
1. Dr. Vogt: "What does one missing Collector's Edition cost you on launch day (lost margin, retailer penalty, brand), and which air-freight budget is left?"
2. Dr. Vogt: "If a tool told you 48h earlier that art books are 5,900 short, what would you actually do and who signs it?" (gets the story for the pitch)
3. Felix: "Are the 350,000 cases really at CTA Hamburg and the 48,000 cards booked air - and is the lid magnet BOM line real or double-counted?"
4. Felix: "Can Karton Nowak split a finished-goods lot and load within hours given the bindery downtime?"
5. Nils: "Why does the tracker omit 11 ERP shipments, and which stock snapshot field shows whether a goods receipt is already included?"
(Ask Vogt "what would you pay per launch?" as a follow-up inside Q1 if time remains.)

## 7. Live-demo risks and mitigations
- Venue Wi-Fi/portal down: run --demo replay offline; MP4 backup one click.
- Initial OCR takes minutes: warm the server 30 min earlier; keep DB pre-built; never cold-start on stage.
- Numbers on screen differ from slides: single reconciled set (item 1); rehearse against final build.
- Staged drop does not apply / state already consumed: reset script for fresh replay DB, test before each run.
- LLM/local model slow or down: cached outputs, deterministic baseline still shows; say so honestly.
- Wrong claim from unverified AGENT findings (e.g. magnets): demo only VERIFIED items; phrase others as "flagged for confirmation".
- Approval/send mishap: dry-run only; never real SMTP on stage.
- Time overrun: hard cut at 2:30 of demo; one speaker, one driver; Q&A answers 20s each.
- Tesseract or Python env breaks on the demo laptop: freeze a working venv, test on a second machine.
- Private token or data leaked in submission repo: scan before pushing.
