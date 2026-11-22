# Business case

Owner: isil-agent, 22 Nov 2026. Money figures come from [NUMBERS.md](NUMBERS.md) and [PROFIT_PLAN.md](PROFIT_PLAN.md). Hours come from [scripts/hours_model.py](../scripts/hours_model.py). Each figure is labelled **DATA** (from the case files), **MODEL** (from our engine or scripts) or **ASSUME** (our estimate, to be validated).

## The conclusion in four lines

1. **The money is in avoided loss, not saved hours.** At Soony about **€1.95M** is at stake this launch weekend. Our best five-action package protects about **€840k** of expected contribution for **€31.5k** of action costs.
2. **The hours show why nobody does this work today.** Doing it by hand takes about **228 person-hours per launch**, which means **9–10 people** working at the same time in a 48-hour crunch. With Manti about **24 hours** of human review are left (**89% less**).
3. **We replace a peak load, not a permanent team.** Per year that is about **0.8 FTE**. We sell "a 10-person war room on demand", not job cuts.
4. **Customers pay a small share of what we protect.** At a 5% success fee Soony pays about **€42k** and keeps about **€798k**, a return of about 20x.

## 1. Who our customers are

**Ideal customer:** brand owners with about €200M–5B revenue that have:

- launches on a fixed date, where a late product means refunds, cancellations or penalties
- products built from many parts (10+ BOM components) supplied by many companies in several countries and languages
- SAP or another ERP whose records differ from the paper: delivery notes, handwritten corrections, quality holds, shipping advices
- one packing line or central warehouse that stops if a single part is missing

**Sectors:** video game and console publishers (physical and collector's editions), consumer electronics, toys and seasonal retail (Q4 peak), cosmetics and gift sets, limited-edition and merchandise drops.

| Role | Who at Soony |
|---|---|
| Buyer of our product | Head of Procurement or VP Supply Chain (Dr. Vogt) |
| Daily users | Buyers, category leads, planners, site leads |
| Approvers | The PP-07 signers (site lead, category lead, CPO) |

## 2. What problems we solve

| Problem | What Manti does |
|---|---|
| "We find out at the dock." SAP counts stock that isn't usable. | Reads every document and finds what SAP misses: 80,000 art books booked where 8,000 were ordered, a statue lot that failed inspection, sleeves of the wrong revision. |
| Nobody knows the real launch risk. | A forecast in 30-minute steps (500 runs) shows how many copies will be packed and which part stops the line first. |
| Chasing suppliers is slow, manual and in foreign languages. | Drafts and sends information and quote requests in the supplier's language, then reads the replies. |
| Decisions don't reach the right person in time. | Routes each action to the right PP-07 signer with a deadline and escalates when it passes. |
| Money is left on the table after launch. | Finds claims and leverage: late-delivery damages, price-clause breaches, contract renewals. |

## 3. Money saved (Soony launch)

| Item | Amount | Label |
|---|---|---|
| Exposure this weekend | **€1.95M** (Collector's €1.134M + Standard €811k) | MODEL. €120 per Collector's copy is firm (Dr. Vogt); €32 per Standard copy is unconfirmed |
| Collector's exposure only | **€1.134M** | MODEL, firm price |
| Best package (actions A, B, C, D, F) | **€840k expected net for €31.5k cost** | MODEL, base case, our own success probabilities |
| Dock slot + early customs alone | **€376k–1.05M** avoided | MODEL; depends on the Standard price |
| Recoverable after launch | Hwaseong damages **€105–175k**; PackRight price clause **€0–42k** | DATA + ASSUME, medium to low confidence |
| Cost to run our agents | **USD 0.01–0.04 per run** (USD 10–40 per launch) | DATA, measured |

**Conclusion:** one launch protects roughly €0.8–1.1M. Our running cost is negligible; the real cost is human review time.

## 4. Hours saved per agent (one launch)

Volumes are DATA from case-data: 308 files (217 PDFs, 60 scans), 392 goods-receipt rows, 447 PO lines, 25 shipments, 93 supplier emails in 9 threads, 7 options, 30 claim lines, 4 data drops. Minutes per task are ASSUME (minimum, most likely, maximum). The model draws 10,000 times; p10/p50/p90 are the low, typical and high cases.

| Agent | Job it replaces | Manual h (p10 / p50 / p90) | With Manti (p50) | Saved (p50) |
|---|---|---|---|---|
| Intake | Procurement assistant | 7 / 9 / 12 | 0.7 | 8.5 |
| Document reader | Data clerk + translator | 31 / 42 / 55 | 3.4 | 38 |
| Analyst | Inventory / procurement analyst | 44 / 57 / 71 | 4.0 | 53 |
| Verifier | Second analyst (four-eyes check) | 5 / 7.5 / 11 | 1.5 | 6 |
| Planner | Supply planner / controller | 33 / 42 / 51 | 2.7 | 39 |
| Chaser | Buyer | 29 / 40 / 56 | 7.5 | 33 |
| Approval router | Procurement manager / PMO | 8.5 / 11 / 15 | 1.0 | 10 |
| Triage | War-room lead | 3 / 4.5 / 6.5 | 1.2 | 3 |
| Claims | Contract buyer / legal | 8 / 11 / 16 | 1.5 | 10 |
| **Total** | | **204 / 228 / 253** | **24** | **204 (89%)** |

| What it means | Value |
|---|---|
| Work per launch | **5.7 person-weeks** |
| People needed in a 48 h crunch (12 h days) | **9–10 at once** |
| Hours saved per year (4–10 launches, 6 most likely) | **1,000–1,750 h, about 0.8 FTE** |
| Labour value per launch (€55–90/h) | **€12–17k** |

**Conclusion:** the labour saving (€12–17k) is small next to the loss avoided (€840k). Hours prove the work can't be done by hand in time. They are not the main reason to buy.

**Caveat:** the model treats each task's error as independent, so the real range is wider than p10–p90. Say "roughly 150–300 hours". To back it up, time a few tasks by hand: read 5 delivery notes, answer 2 supplier emails, run one MRP update.

## 5. Pricing

| Option | Soony example | Comment |
|---|---|---|
| Success fee: 5% of verified net avoided loss | **≈ €42k per launch** | Current proposal ([PROFIT_PLAN.md](PROFIT_PLAN.md) §5). Soony pays only when it wins. |
| Platform fee + smaller success fee | e.g. fixed fee per launch + 2–3% | Suggested. "Avoided loss" is a counterfactual, so customers may dispute it; a fixed part makes revenue predictable. |
| Paid pilot | One launch with a design partner | First step to prove the numbers. |

At 5%, the fee is about 3x the labour value and about 1,000–4,000x our model cost.

## 6. What is automated and where a human decides

**Fully automated**

- Portal sync and change detection on every file (SHA-256)
- Reading documents in several languages, including handwriting, with file, page and quote for every fact
- Reconciling SAP against the paper evidence
- Parts planning (MRP) and a 500-run forecast in 30-minute steps
- Re-ranking the action list after every data drop
- Drafting supplier emails in the supplier's language
- Sending non-binding information and quote requests to allowlisted supplier domains (kill switch `CHASER_AUTO_SEND=0`)
- Reading supplier replies
- Routing approvals by PP-07, with deadlines and escalation
- A verifier agent that rejects numbers without a source
- A full audit log

**Human in the loop** ([APPROVALS.md](APPROVALS.md))

| Mode | What it covers |
|---|---|
| One click by the named PP-07 approver | Purchase orders, dock slots, air freight |
| Escalate | Approver vacant, deadline missed, or above the limit (air freight over €200k a month goes to the CPO) |
| Never automatic | Quality releases, missing evidence, anything revealing our walkaway price or break-even, €5M+ without the CPO or CFO |
| Human review | Supplier claims, unfamiliar files |
| AUTO by delegation | Only information-only or reversible actions, under a written delegation and below its limit; the approver is notified, and a kill switch turns it off |

## 7. How far automation can grow

| Level | What the agents do | Status |
|---|---|---|
| L1 | Read, reconcile, forecast | Done |
| L2 | Draft and route; send non-binding mail | **Done (today)** |
| L3 | Act on reversible, low-value items under written delegation: hold-and-quote, refundable dock bookings, small POs from approved suppliers within price bands | Built; the delegation is not yet confirmed in writing |
| L4 | Negotiate within approved price bands; book freight through APIs; draft corrections back into SAP; file claims before deadlines | Roadmap |
| L5 | Always-on monitoring across all launches, supplier scorecards, second-source proposals | Roadmap |

**Never automated:** quality release, commitments above an approver's limit, revealing our walkaway position. We widen autonomy only when the data supports it: how often humans accept the agent's proposal unchanged, and how often they override it.

## 8. Name (to decide)

Shortlist so far, before trademark and domain checks:

| Name | Angle |
|---|---|
| **Partpilot** | Automation + supply chain: autopilot for every part |
| **Kitflow** | Procurement word "kit" + workflow |
| **Fullkit** | Planning term: start only when every part is there |
| **Matchpoint** | From procurement's "three-way match" |
| **Nightshift** | The war room that works the weekend crunch |
| **Paperline** | "We read the paper SAP never sees" |
| **Countersign** | Agents prepare, a named human signs |
| **Manti** (current) | Many small pieces in one wrap, like parts in one box |

Avoid names of existing supply-chain and procurement companies: Altana, Prewave, Everstream, Interos, Resilinc, Keelvar, Pactum, Didero, Tacto, Zip, Fairmarkit, Arkestro, Globality, Sievo, Ivalua, Jaggaer, Levelpath, Omnea, Scoutbee, Procurify, Supplyframe, Lio.

## 9. Founding decisions still open

- **Team and roles:** who goes full-time; CEO/business, CTO, product/agents, domain/operations, regulatory.
- **Equity:** an equal split is simplest; 4-year vesting with a 1-year cliff.
- **Legal entity:** Swiss GmbH (CHF 20k capital) or German GmbH (€25k) / UG, depending on where we are based.
- **Funding path:** paid pilot with a design partner first, then pre-seed. Grants to check: Innosuisse (CH), EXIST (DE), EIC Accelerator (EU).

## 10. Still missing from the business case

- **Competitors and why us:** SAP IBP, Kinaxis, o9, Coupa, Keelvar, Pactum, Lio (partner or competitor?). Our edge: the paper layer, cited evidence, approval rules as code.
- **Market size** (TAM/SAM/SOM) and **go-to-market:** pilot design, first 3 target customers, sales cycle.
- **Integrations:** SAP, email (SMTP/IMAP), supplier portals, freight APIs.
- **Security, privacy, regulation:** GDPR for supplier emails; EU AI Act transparency and human oversight (a strength); liability if an agent sends something wrong.
- **KPIs:** exceptions found before the dock, time to decision, override rate, euros protected.
- **Risks:** the Standard €32 price is unconfirmed; success probabilities are our judgement; no real quotes yet; task times in the hours model are estimates.
- **The ask:** what we want from the jury or Lio (pilot, intro, funding).
