# GAME_THEORY.md: making the chaser smarter and the pitch more rigorous

Author: research-gt. Inputs: docs/NUMBERS.md (frozen numbers), FINDINGS.md (supplier facts, several AGENT-reported), src/chaser/guardrails.py and agent.py. Literature names below (Akerlof, Spence, Myerson, Holmstrom, Cachon on supply contracts) are cited from memory and NOT opened or verified; do not put paper titles or IDs on a slide. The reasoning stands without them.

## 1. The launch-weekend game

Players: Soony buyer (us, via the agent) and each supplier. Time: now to Sun 22 Nov 20:00. Moves: we ask, offer, escalate; the supplier replies, ships, or stalls.

**Private information.** The supplier knows its true capacity, its line status and its real ETA; we see a promised date. This is adverse selection plus moral hazard: a supplier that cannot deliver gains from staying vague (it keeps the order, avoids the penalty claim, may hope to slip). Evidence in our data: PO 4500318744 confirmed 2026-12-28 vs promised 2026-12-21; Karton Nowak's contract promises 50,000 in 36 h at +35% while its own downtime notice says digital line only, max 15,000 per 36 h (FINDINGS, AGENT-reported); SUP-0019 promises about 8 days after requested date (AGENT).

**Cheap talk vs costly signals.** "We will do our best" costs nothing, so it carries no information; an ETA typed in an email is nearly as cheap. A signal is informative when lying costs the liar more than it costs the truth-teller. Ranking of what we can ask for, cheapest to lie about first:
1. A date in prose (cheap talk).
2. A date plus the quantity per lot plus the named person who confirmed it.
3. A document that exists only if the goods exist: pick list, packing list, booking number with carrier, forwarder release, truck plate and slot. Fabricating these is costly and checkable.
4. A scan or photo of the pallet label (lot number) against the lot we expect.

**Elicitation levers (mechanism design).**
- *Verifiable commitment:* ask for the shipping document or booking number, not the date. Supplier who has it sends it in minutes; supplier who lacks it reveals itself by delay. Silence is itself a signal and the agent should score it.
- *Tiered requests:* ask first for what is cheap and truthful to give ("what quantity is physically finished and palletised right now?"), then for the ETA of the rest. Partial truth about stock-on-hand anchors the answer about the remainder.
- *Menu / option contract:* offer a menu so each supplier self-selects: (a) a small fee for a firm slot on lot X by time T, forfeited if missed; (b) no fee, no priority. A supplier with real capacity takes (a); one without does not. This is a separating mechanism, the same logic as option contracts in supply chains.
- *Incentive-compatible penalty:* only a penalty that is already in the contract is credible. Quote it, do not invent one (see 2).
- *Deadline effect:* give a response deadline that is real and short (for example "reply by 14:00 today") and a stated next step. A deadline with no consequence is cheap talk from us. Each rung of the ladder must be something we will actually do.

**Repeated game and reputation.** Suppliers care about next year's volume (Hwaseong LTA expires 31 Dec 2026, renewal due 15 Dec; this is leverage we hold). Use each supplier's real lateness history as the prior for P(on time): SUP-0010 about 50% of lines late, avg 4.2 d, max 17; SUP-0019 about 8 d after requested; others 16-29% late (AGENT-reported, re-verify against the CSVs before quoting). The agent should discount a promised ETA by that supplier's historical slip and update after each reply (a simple Beta-style hit rate per supplier is enough). Caution: a threat to the relationship is only credible where we have alternatives; for single sources it is not.

## 2. Chaser policy: escalation ladder and archetypes

**Ladder (extends tone_for_state: reminder, firm_request, phone_call, plan_b).**

| Rung | When (hours before deadline, Sun 20:00) | Content | Gate |
|---|---|---|---|
| R0 Probe | T-48h or at first shortage signal | Neutral ask: quantity physically finished, lot numbers, earliest pick-up. No deadline slack disclosed | Human approves send |
| R1 Document ask | no verifiable reply within 3 h | Ask for packing list or booking number; restate contract date | Human approves |
| R2 Incentive | T-30h | Offer a lever (below), short response window | Human approves; guardrail on premium |
| R3 Voice | T-24h or silence 6 h | Flag human to phone; agent prepares call script with facts | Human acts |
| R4 Plan B | T-18h or credible "cannot" | Recommend priced alternative; start in parallel, not after | Approval by PP-07 owner |

Key rule: **start Plan B costing in parallel from R1, not after R3.** The credibility of the ladder depends on our alternative being real; a supplier who sees us waiting knows our walkaway is weak.

**What to offer.** Expedite fee sharing (we pay the incremental freight or overtime, supplier carries the base); volume guarantee on a future order we already plan; early payment (cash is cheap for us relative to a miss); documentation of an existing penalty clause. Always inside guardrails: proposed_price_premium_pct must stay at or below max_price_premium_pct, and forbidden phrases ("we guarantee", "will arrive", "is confirmed") stay out of drafts. The agent must not make a binding commitment; the human does.

**What NOT to reveal.** Our deadline slack, how much stock we already have, our alternative suppliers and their price, our maximum premium, and the cost of a missed copy. Revealing slack removes the supplier's urgency; revealing the maximum premium invites it to be taken. State the date we need and the contractual date, nothing about what happens if we cannot hit it.

**Per archetype (facts from FINDINGS, AGENT-reported unless noted):**
- *Karton Nowak (SUP-0028, art book, single source for art book/poster/leaflet):* downtime 21.11 14:00 to 23.11 06:00, finished stock only, digital rush max 15,000 per 36 h, express offer 8,000 pcs overrun stock loaded within 4 h, about 9 h drive. Policy: do not argue the contract 50,000/36 h clause (no capacity, and it irritates the only source); take the express offer; ask for the pallet label and the truck slot as the verifiable commitment; offer to pay freight. Estimated EUR 12,390 (NUMBERS.md, materials only).
- *Boise Semi (SUP-0011, EXW, seller-favourable, delay liability capped at product price, dates are estimates):* penalties give us no leverage, so ask for nothing contractual. Lever is speed and money: we pay freight, ask for forwarder booking and release of the dock-held lot (020-48113304). Our real risk is the forwarder, so ask for the forwarder contact.
- *Hwaseong (63 d lead, chronically late):* use the contract: late damages 2%/week cap 10%, LTA renewal by 15 Dec as the relationship lever. Start Plan B from R1 because the prior is slip.
- *Pune (statue, conditional):* approval needs PPAP and written release by Supplier Quality and Category Lead, and the Category Lead role is vacant. The binding constraint is internal, not the supplier; the agent should route to a human, not chase Pune.
- *Dongguan (steel case, single source, 70 d lead):* no alternate, so no credible walkaway; use cooperative levers only (early payment, volume), never threats. For cases, NUMBERS.md says 350,000 sit at the Hamburg terminal and need pickup: that is an internal action.

## 3. Small expedite model

Choose option i in {wait, air split, partial, alternate source} to minimise

  E[Cost_i] = C_i + L x Q x (1 - P_i)

where C_i is the extra cost of the option, Q the missing units, L the loss per missing copy, P_i the probability that the option lands before Sun 20:00 (our Monte Carlo conditioned on the option).

**Threshold rule (two options):** expedite iff C_e < L x Q x (P_e - P_w), i.e. L > L* = C_e / (Q x ΔP), ΔP = P_e - P_w.

**Worked example, art book (only numbers from NUMBERS.md):** Q = 5,900 finished units; C_e = EUR 12,390 (express offer, materials only; freight and dock slot not yet priced, so C_e is a lower bound). Cost per unit = 12,390 / 5,900 = EUR 2.10. So **L* = 2.10 / ΔP**.

Break-even L per missing copy: ΔP 0.2 gives EUR 10.50; ΔP 0.5 gives EUR 4.20; ΔP 0.8 gives EUR 2.63.

**Parameters Dr. Vogt must supply:** L (lost margin, retailer penalty, brand cost per missing CE copy), and the air or freight budget. **ΔP is an unknown we set by judgement**: NUMBERS.md gives only P(reach target) = 0% overall and p50 gaps; it does not give P(on time) for wait vs express on art books. We must run the Monte Carlo per option before showing ΔP as a result.

Net benefit = ΔP x L x 5,900 - 12,390 (EUR):

| L (EUR/copy) | ΔP 0.2 | ΔP 0.5 | ΔP 0.8 |
|---|---|---|---|
| 2 | -10,030 | -6,490 | -2,950 |
| 5 | -6,490 | 2,360 | 11,210 |
| 10 | -590 | 17,110 | 34,810 |
| 35 | 28,910 | 90,860 | 152,810 |

Reference only: std cost of a CE unit is EUR 34.5 (NUMBERS.md, cost of goods, not revenue). Even at L equal to a tenth of that, express wins unless ΔP is below 0.3. This is a statement about the formula, not a claim about Soony's real L.

Caveat: the model treats units as independent. In reality a CE copy needs all parts, so the binding gap is the max across components (game card 6,800, art book 5,900, statue 3,400), and fixing the art book alone does not recover a CE copy if the game card still misses. The decision layer should compute the joint P(all parts on time) and credit each option with its marginal change in the joint.

## 4. Pitch framing

- **Information asymmetry is the product.** SAP believes stock that is not there (art book booked 80,000 vs 8,000 ordered); suppliers believe we cannot see. The agent closes the gap on both sides: it reads documents the humans do not, and it asks for verifiable proof instead of promises.
- **Why agents beat phone-tag:** (1) speed: every rung of the ladder is drafted in seconds in Polish, Korean, Mandarin; (2) parallelism: seven options chased at once; (3) credible escalation: a deadline is credible only if the next rung is pre-built and priced, which a human buyer on a weekend cannot guarantee; (4) memory: per-supplier reliability priors, not a buyer's recollection.
- **Staff incentives (a point for us, treat as hypothesis until we hear it from Soony):** the person who reports a shortage is the person who gets blamed, so rational buyers delay bad news hoping it self-corrects. That is a principal-agent problem: the bad-news signal is suppressed at the source. A neutral agent that surfaces the gap from documents removes the personal cost of reporting. The human-approval gate keeps accountability where PP-07 puts it (buyer under EUR 50k). Do not claim Soony staff behave this way; say "typical incentive, to confirm with Dr. Vogt".
- Honest limit: we do not know supplier behaviour from outside our data; our models are priors, and the demo should show the priors updating, not assert them.

## 5. Three things to build in the next 6 hours

**A. Reliability prior and discounted ETA (src/decide/reliability.py).** Function `discounted_eta(supplier_id, promised_eta) -> (eta_p50, eta_p90, p_on_time)`. Compute from the PO and delivery CSVs: per supplier, share of late lines, mean and max slip days; if fewer than 5 lines, fall back to the global rate and mark `low_data=true`. Apply the slip to promised ETA, return p_on_time against the deadline. Add a Beta(1,1)-style update hook `update(supplier_id, hit: bool)` called by the chaser when a reply is parsed. Tests: SUP-0010 yields a later p50 than a 16% supplier; a supplier with no lines returns global prior with low_data flag. Numbers come from files, nothing hardcoded.

**B. Verifiable-commitment scoring in parse_reply (src/chaser).** Extend the parsed reply with `evidence` in {none, date_only, qty_and_date, document_ref} and `commitment_score` 0-3, using deterministic regex first (booking number, packing list, pallet or lot id, truck slot) and the LLM only as fallback. In agent.py, `needs_human` and the next rung depend on the score: score 3 stops the ladder and feeds P_i upward; score 0 after the response window raises the rung by one and logs `silence_signal`. Also add draft templates for R1 that ask for a document, not a date. Guardrails unchanged: keep forbidden phrases and the premium cap; add a check that a draft never contains our deadline slack or max premium (regex on "slack", "max premium", walkaway phrasing; add as a validate_draft rule).

**C. Expedite chooser (src/decide/expedite.py).** Function `choose(options, loss_per_copy, q_missing)`, where each option holds `cost_eur`, `p_on_time`, `label`. Returns the option minimising `cost + L*Q*(1-p)`, the pairwise thresholds L*, and a sensitivity grid over L in {2,5,10,35} and ΔP. `loss_per_copy` is a required parameter with no default; when absent, output L* and the grid rather than a recommendation, with the string "needs Dr. Vogt". p_on_time comes from the Monte Carlo rerun with that option applied; if not available, accept it as an explicit input and tag `source="assumption"` in the output so the UI shows it as such. Seed with the art book option (cost 12,390, Q 5,900); leave other options unpriced as NUMBERS.md says.

## Open and not to claim
L per copy; real ΔP for any option; whether the dock-held game card lot can move; supplier lateness stats until re-run on CSVs; any statement that Soony staff delay bad news.
