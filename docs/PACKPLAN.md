# Pack-out plan (T73)

`python3 -m src.decide.packplan` (add `--mc` for the truth.simulate() Monte Carlo baselines; `--lag earliest|mode|mean|median`).
Agent tool: `packplan(changes?)` in `TOOLS`. Runtime about 0.3 s for the plan, no new dependency.

## Inputs (all from `src.truth.readiness`)
- Independent recipes: parts supplied fitted inside another part are excluded (the 4 lid magnets per CE sit inside CMP-GAM-007). Printed on every run: *assumes magnets are supplier-fitted; if the BOM line is real, CE cannot be packed* (`magnet_fitted=False` shows that case: CE = 0).
- Usable stock after adjustments (`parts[].on_hand`), non-held inbound with `earliest`, shifts (06:00-22:00 Sat, 06:00-20:00 Sun, cut at the launch cutoff), rates, remaining targets, 30-minute buckets with `floor(rate*hours)` caps, same as `simulate()`.
- Arrival time is deterministic: `earliest` plus the median of the triangular handling lag for the transport mode (`--lag` selects mode, mean or none). Held lots stay out unless `release_held` is set.

## Method (exact)
For final totals (X CE, Y STD) the schedule that packs each edition as late as its rate allows has the pointwise smallest cumulative consumption of every part. Part limits read "cumulative use <= cumulative availability" and availability never decreases, so (X, Y) is feasible iff that late schedule is. That gives a closed form: for each integer X, Ymax(X) = min over parts and supply steps of `after_Y + floor((S - a*max(0, X - after_X)) / b)` (parts used by one edition reduce to caps). The objective `w*CE + STD` is maximised exactly by scanning X (ties: more units, then more CE). The frontier output is the upper hull of (X, Ymax(X)). An early forward schedule for the chosen point is built with the same feasibility test (largest feasible pack per bucket, CE decided first); the latest schedule is the exact fallback. Both baseline policies (same per-bucket logic as `truth.simulate`, CE-first and STD-first) are feasible points, so the w=1 optimum can never be worse than the better of them (asserted in tests).

`w` is the value of one CE unit in STD units: w=1 maximises total units, w>1 favours Collector's, w<1 Standard, 1,000,000 is Collector's first. The cost L per missing copy is unknown (needs Dr. Vogt), so no w is picked for you.

## Result on the published snapshot (median arrivals)
Baselines reproduce NUMBERS.md exactly (they equal the truth engine's p50): CE first = STD 614,650 / CE 62,550; STD first = STD 615,100 / CE 62,100. Both add 118,400 units, the game card stock (CMP-GAM-001). The 28,000 air lot lands after the cutoff at the median lag.

| Plan | CE total | STD total | Units added |
|---|---:|---:|---:|
| baseline CE first | 62,550 | 614,650 | 118,400 |
| baseline STD first | 62,100 | 615,100 | 118,400 |
| w=1 / Collector's first (max CE 19,300) | 66,100 | 611,100 | 118,400 |
| w<=0.5 (STD only) | 46,800 | 630,400 | 118,400 |

Honest gain: **0 units in total** versus the better baseline. The game card is the binding shared part, so the plan only reallocates it. What the optimizer adds is the split: CE can reach 66,100 (+3,550 vs CE first) because the CE line is rate-capped at 900/h while game cards run out, and reserving them for CE lifts it to the art book limit (19,300 additional) at the cost of 3,550 STD. First stop of every plan: CMP-GAM-001 (CE alone: art book CMP-GAM-008 when STD gets the cards).

What-if (delta vs unchanged, STD in brackets for the Collector's-first point):
- Restore 5,900 art books: CE +2,500 (statue lot now binds at 21,800), STD -2,500, total 0.
- Release 5,600 quarantined statues alone: 0 (art book still binds).
- Game card air lot 12 h earlier: +28,000 STD units (it then fits before the cutoff).
- Release the held game card lot: 0 (it arrives 24 Nov, after the cutoff).
So the lever is the game card lot timing; art book and statue only matter for the CE share.

## Numbered Collector's Edition allocation
All 72,000 CE are numbered and pre-ordered, but the data has no customer-level records (no order numbers, timestamps, tiers or regions). The function returns three rules (first-come by order number, highest tier first, regional split) and the consequence for each: with 66,100 CE in total (best case), 72,000 - 66,100 = 5,900 numbered pre-orders get no copy. Human decision, owner Head of Procurement / Head of Sales; they need to supply order timestamps, tiers, region constraints and whether a later ship date is acceptable. Which numbers the already packed 46,800 carry is not in the data; if they are not the first 46,800 order numbers, the rules apply to the whole 72,000.

## Assumptions and limits
- Median arrival times, not the Monte Carlo distribution; the 28,000 air lot is the swing item (about 29% chance of arriving inside the shifts, p90 +12,000 STD). Use `--lag earliest` for the optimistic case and `--mc` for the simulation's p10/p50/p90 under the same inputs. The plan is one deterministic schedule, not a robust plan under arrival uncertainty.
- The magnet line is a flagged assumption (confirm with Felix Brunner).
- No changeover time, labour contention, carton staging, truck capacity or per-bucket partial-line effects; each line may switch edition at any bucket.
- Usable stock is `on_hand` rounded by the truth engine.
