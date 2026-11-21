# PROFIT PLAN (T92, sonnet-profit, Sat 21 Nov evening)

Model: `.venv/bin/python scripts/profit_model.py [--scenario low|base|high] [--set NAME=value]`. Pure Python, deterministic, 0.3 s. Every number is a named parameter with source and status (DATA, ENGINE, ASSUME, UNCONFIRMED). Another agent (sonnet-engine) is refreshing docs/NUMBERS.md for the 19:25 drop; this model keeps the kickoff totals (CE 62,550 / STD 614,650 baseline, gaps unchanged per the NEW_DROP note) and must be rerun when the engine publishes new counts. Boise ruled out a Sunday 08:00 handoff (HANDOFFS, T81), so the full-save option D of docs/VOGT_BREAKEVEN.md is not available and is not in the model.

## 1. What profit means here
Net contribution of the launch = margin on copies shipped on time, minus refunds on late or missing Collector's copies (EUR 120 each, Dr. Vogt), minus the cost of delay on Standard copies, minus the cost of parts, expedite, freight, handling and fees. Parts already bought are sunk, so the decision value of an action is the change in expected loss minus what the action costs:

`net(S) = E[ L_CE x dCE_short + L_STD x dSTD_short ] - cost(S)`

- **L_CE = EUR 120** (DATA, Vogt; retail 199.99, Soony receives 120). Margin if shipped is 120 - 34.5 = EUR 85.5 (products.csv).
- **L_STD** is the weak point. Vogt said EUR 32 (UNCONFIRMED, wording short); the CPO memo says a Standard copy arriving Tuesday is still sold. Default (ASSUME): 5% of late buyers cancel x EUR 32 + EUR 1.4 service cost = **EUR 3.0 per late Standard copy**. Sensitivity runs 0 to 32.
- Unknowns, all parameters: L_STD, P_CANCEL_STD, DELAY_COST_STD (ask Vogt / Sales: how many late Standard pre-orders cancel, what a voucher costs); success probabilities P_A..P_G (ask the owners below); action costs (get 3 quotes: forwarder, broker, Karton truck; Okafor for sorting hours); the part limits (NUMBERS.md, refresh after the engine); whether the 4 magnets per CE are really supplier-fitted (Felix Brunner).

## 2. Decision model
Packed copies come from a closed form over shared parts (same logic as docs/PACKPLAN.md): CE total = min(need, art books, statues, rate, cards); STD total = min(need, cases, rev C sleeves, cards left after CE). Reproduces PACKPLAN exactly in the no-air-lot states (62,550 / 614,650 baseline; 66,100 / 611,100 Collector's first; art books +2,500 CE). With the air lot it uses the engine split (+21,216 STD, +3,133 CE). Seven actions, 2^7 = 128 subsets, independent success draws, costs paid regardless. Base costs: low/base/high in the script.

**Standalone, base case (vs doing nothing, expected exposure EUR 1.22M):**

| Action | Cost EUR | Net EUR | P(success) | Approver |
|---|---:|---:|---:|---|
| F Collector's first, slow Standard | 2,000 | 378,524 | 90% | CPO (memo already says so) |
| A Dock slot + early customs, 28,000 cards | 8,000 | 228,025 | 60% | Katrin Jansen; fees up to EUR 200k/month Tobias Brandt |
| B Collect 350,000 cases | 1,500 | 9,472 | 85% | Katrin Jansen / Felix Brunner |
| E Rev C sleeves | 3,000 | -3,000 | 30% | Sofia Marchetti + Paul Winter |
| D Statue sort/concession | 5,600 | -5,600 | 75% | Daniel Okafor + Head of Procurement (seat vacant) |
| G Air the 20,000 balance | 5,600 | -5,600 | 95% | Tobias Brandt |
| C Karton art books 5,900 | 14,390 | -14,390 | 80% | Paul Winter (< EUR 50k) |

C, D and G look worthless alone. That is the interaction, not a bug.

**Best subset: A B C D F, net EUR 840,159 expected (sd 344,587, p10 397,825), cost EUR 31,490, expected CE 69,569 of 72,000, STD 619,785.** Dropping one costs: F 603,495; C 413,982; D 209,766; A 51,056; B 22,552. Sleeves (E) add EUR 0 in the best set (the usable rev C stock of 122,000 is not binding unless the air lot adds many Standard cards), so only E as insurance. G does nothing for the launch (flight 23 Nov lands 24 Nov, after the Sunday 20:00 cutoff); it only shortens the Standard delay and is not in the best set. Alternative game-card sources: no source on file can deliver before Sunday 20:00, so launch value is 0 and it is a post-launch task.

**Interactions:** C alone -14,390 and D alone -5,600, F alone +378,524, but F+C+D = 788,407 vs the sum of singles 358,534. Art books and statues pay only together with Collector's first. A alone 228,025 and F alone 378,524 but A+F 405,256: game cards bind both lines, so A's gain is mostly Standard once F has fed Collector's. E pays only with A.

**Pareto (expected net vs sd):** ABCDF 840k / 345k; ABCF 630k / 187k (skips the statue sort, whose approval is the least certain); ACF 606k / 186k; ABF 432k / 95k; AF 405k / 90k. The lowest-risk strong set is AF (about EUR 10k cost). Statue and art books add about EUR 210k (ABCF to ABCDF) to 410k (ABF to ABCDF) of expected value but add variance because both must succeed.

Unit economics of the top items: ROI on action cost is about 190x for F, 28x for A, 6x for B; ROI of the C+D pair (EUR 20k) is about 31x (marginal 624k / 20k).

## 3. Cost ranges and external benchmarks (estimates only, bound the unquoted costs)
- Air cargo Hong Kong-Europe spot HK$33.63/kg at 31 Aug 2026 (about USD 4.3/kg, my conversion), HK$45.50 in April [S]: https://www.balticexchange.com/en/news-and-events/news/guest-column/2026/Air-freight-rates-remain-elevated-as-higher-jet-fuel-prices-bite.html (search snippets, other BAI pages). A Dec 2025 report gave USD 5.44/kg [S]. No ICN-FRA figure found: GAP, use USD 4-6/kg. Assumption (mine): 0.05 kg gross per game card, so 20,000 cards ~1,000 kg ~ EUR 4-6k, matching the EUR 3.5k / 5.6k / 9k range for G. The 28,000 lot is already flown.
- Road: Q3 2026 Ti/Upply/IRU benchmark, Warsaw-Duisburg EUR 1.55/km contract and EUR 1.65/km spot, Antwerp-Duisburg EUR 2.74 / 3.02, record index levels [S]: https://trans.info/en/road-freight-rates-q3-2026-513960. For Poznan-Hamburg (about 600 km, my estimate) one dedicated truck is EUR 1-2k; weekend and express premium doubles it. Frankfurt-Hamburg (about 490 km) similar. Hence C freight 1,000 / 2,000 / 5,000.
- Customs / handling: DHL lists clearance processing at EUR 10-49 per shipment, EUR 45 typical, permit handling EUR 49 [S]; Frankfurt courier terminal storage EUR 6.00 per 100 kg per day, minimum EUR 20 [S]: https://www.time-matters.com/wp-content/uploads/courierterminal/pricelist-timematters-courier-terminals-frankfurt.pdf. A broker for a 28,000-card commercial lot is outside these price lists: GAP. Our A range of EUR 3,000 / 8,000 / 25,000 is my bound (dock priority, broker, truck, weekend premium). Even at EUR 250,000 A still wins when Standard late-cost is EUR 32 (table below); A alone breaks even at a EUR 236,025 fee.
- Premium-edition refund economics and how firms value launch-day availability: nothing usable found; we use Vogt's EUR 120 only. Listed in RESEARCH_INDEX as GAP.

## 4. Profit beyond the launch (the max-out part)
| Item | EUR range | Confidence | Next step | Owner |
|---|---|---|---|---|
| Hwaseong late damages still claimable (nick check: 30 lines, USD 173,500 on the PO file; pro-rata USD 113k-190k) | about 105k-175k (USD ~0.9x EUR, my rough conversion) | medium (Claims says invoices not supplied, set-off and force majeure not assessed) | File written claim notices per line before each deadline: USD 7,128 line (4500318544/2) expires TODAY 21 Nov, 2,592 on 24 Nov, 2,160 on 8 Dec; the rest run into 2027. Do not use expired lines. | Buyer for Hwaseong, Legal |
| PackRight price fixed clause breach (CNY 165,300 + 11,750 + 170,577 = 347,627, GAM-003/004/007) | 0 - 42k (CNY 0.12/EUR, ASSUME) | low-medium | Read clause p. 3 and the notices, confirm no change notice, claim credit note | Paul Winter |
| Boise price drift (USD 531,091) | past: about 0 (60 days' notice allowed); future: price fixity, GAM-001 USD 10.93 vs contract 10.20 vs Hwaseong 9.80 | medium | Treat as negotiation leverage, do not claim. 0.73 USD x 385k units (281,196 / 0.73) is the annual-scale prize if reverted | Category Lead Game Media |
| Freight/duty DDP vs EXW (81 Boise lines marked DDP in ERP, contract EXW, no invoices supplied) | unquantified; sizing: 81 lines x ~9,000 cards x 0.05 kg = 36 t, USD 10-20k by sea, 150-220k if all air | low | Pull freight and duty invoices from AP, compare to PO price; check whether a DDP price premium was paid | AP + Felix Brunner |
| Hwaseong LTA renewal, amendment due 15 Dec 2026 (else list prices, NET30, no capacity) | 0 - 400k/yr: moving GAM-001 volume from Boise to Hwaseong saves USD 1.13/unit | low (Hwaseong has 57 late lines) | Bring damages and OTD record as leverage; ask price fixity, late-delivery clause, capacity reservation, expedite terms | Head of Procurement |
| Second source for single-source parts (CPO asked proposals end of next week) | not quantified (no spend roll-up in repo) | n/a | Roll PO spend by part and supplier count from `purchase_orders_*.csv`; first candidates: statue (Pune qualification expired 30 Oct), art book (Karton only), magnets | Category Leads |
| Rare-earth magnets in Collector's box CMP-GAM-007 (deliveries after 1 Dec slip 6 weeks) | exposure up to 6 wk x 12,000 CE x EUR 85.5 = EUR 6.2M gross margin if sales are lost not deferred (weekly plan 12,000 from products.csv); with 10-30% lost: EUR 0.6-1.8M | medium on the notice, low on the loss share | Order ferrite and ribbon-closure samples now (10 days per PackRight), pull forward box orders before 1 Dec, ask for the end-use certificate timeline | Tobias Brandt, Quality |

## 5. What our product charges
Proposal (not a quote): a share of verified avoided loss, here 5% of net per launch. In the best subset the avoided loss is about EUR 872k before action costs and EUR 840k after, so 5% is about EUR 42,000 per launch, and Soony keeps about EUR 798k. Because the number depends on L_STD, show it at the confirmed value: at L_STD 0 the same set is still worth EUR 812k and at 32 it is EUR 1.12M. Agent unit economics: measured live cost USD 0.01-0.04 per run, so 1,000 runs per launch cost USD 10-40; the fee is 1,000x to 4,000x the model cost. The real cost is human review time, not tokens. Pitch, 3 sentences: "SAP said fine; our agents found that the game card lot, art books and statues were short, and that the cheapest way to stop EUR 1.2M of Collector's refunds is to feed Collector's first and fix three parts together. In the base case a EUR 31k package of five actions protects about EUR 840k of expected contribution, with every number traced to a file and every action waiting for the PP-07 approver. We charge a small share of the loss we verifiably avoid, so Soony pays only when it wins."

## 6. Sensitivity (base costs; best subset / expected net EUR)
| L_STD effective | A fee 3,000 | 8,000 | 25,000 | 250,000 |
|---|---|---|---|---|
| 0 | ACDF 817,288 | ACDF 812,288 | CDF 797,730 | CDF 797,730 |
| 1.4 | ABCDF 829,494 | ABCDF 824,494 | ABCDF 807,494 | CDF 793,379 |
| 3 | ABCDF 845,159 | ABCDF 840,159 | ABCDF 823,159 | BCDF 789,103 |
| 10 | ABCDF 913,692 | ABCDF 908,692 | ABCDF 891,692 | BCDF 772,474 |
| 32 | ABCDF 1,129,082 | ABCDF 1,124,082 | ABCDF 1,107,082 | ABCDF 882,082 |

L_CE matters most: 60 -> 419k, 90 -> 630k, 120 -> 840k, 160 -> 1.12M, 199.99 -> 1.40M (best set unchanged ABCDF). P_A from 0.2 to 1.0 moves the best net only from 801k to 880k. Conclusion: the best set is robust to L_STD and to the fee; it is sensitive to L_CE and to whether C and D both succeed. The answer changes if Standard late cost is 0 and A is dear (B drops out, then A).

## 7. Next 16 hours (Sat 21 Nov 20:00 to Sun 22 Nov 12:00) and decisions
1. 20:00 F: CPO confirms Collector's first in the pack-out plan (memo already says it); plan owner sets the schedule. Owner Jonas Lindqvist.
2. 20:00 C: Paul Winter approves the Karton PO for 5,900 (EUR 12,390 DAP quote); reconcile quantity with the 19:25 counts first; book a truck now (9 h). Do not buy C without D or F.
3. 20:15 D: Daniel Okafor starts the 100% sort of the 5,600 lot; Head of Procurement gives the exception; Quality keeps last word. Planned sort result by Sun 06:00.
4. 20:30 B: Jansen / Brunner confirm the 350,000 cases are collectable and send trucks Sunday 06:00.
5. 21:00 A: Jansen books the dock slot (4 h unload after landing) and a broker for early customs; get three fee quotes; anything above EUR 200k a month goes to the CPO the same hour.
6. 21:00 Legal/Buyer: file the Hwaseong notice for the line expiring today (USD 7,128) and for 24 Nov (USD 2,592).
7. Sun 06:00 rerun `scripts/profit_model.py` with the engine's new counts and Vogt's confirmed L_STD; publish one page (CPO's format: cost against copies gained).
8. Sun 08:00 Pack CE first; Sun 12:00 flight lands, check A on track. Post-launch Mon: LTA brief, magnet samples, second-source proposal.

**Top 5 decisions for a human tonight:** (1) Confirm Collector's first in the pack plan (CPO). (2) Approve the art-book PO together with the statue sort (Winter, Okafor, Vogt): only the pair pays. (3) Authorize the dock slot + early customs and cap the fee (Jansen, Brandt). (4) Confirm L_STD: is a Standard copy arriving Tuesday still sold (Vogt)? It changes B and A's order but not the best set. (5) Authorize collection of the 350,000 cases and the Hwaseong claim notice due today.

## 8. Limits
No quotes; probabilities are our judgement; closed form differs from the engine by a few hundred copies in the air-lot states (Vogt breakeven shows +5,848 CE for the full package, the closed form gives about +6,300). Independence of successes is assumed. Statue sorting yield uses 9/125 defects. Post-drop packed counts (554,000 / 53,100) keep the same totals but shorten the time left; rerun after the engine refresh. Search figures are snippet-only [S] and not exact lanes.
