# NUMBERS.md — the single frozen number set (deck, demo, video must use ONLY these)
The dashboard, deck, and pitch use the default readiness model. These figures are from the complete post-drop snapshot. When publishing a new snapshot, refresh its fingerprint and forecast together, then update the deck and video.

## Later Hamburg goods receipt (T98 corrected live-snapshot rerun)

The later portal mirror contains goods receipt `5000413070` for 28,000 cards on PO `4500318735` line 2 (`soony/erp/goods_receipts_update.csv`, row 4). The receipt matches AWB `020-48113256` in `soony/erp/open_shipments.csv` (row 17) and in the shipping advice (page 1). The planning engine retires the matching inbound lot. Cards on hand rise from 70,100 to **98,100**. Eligible inbound falls from 28,000 to **0**, leaving **6,800 short** against 104,900 remaining cards required.

With the matched lot already received, the 500-run Collector’s-first rerun gives **639,100 Standard** and **66,100 Collector’s** at the median, with **0 of 500** trials reaching either edition’s target. The published 19:25 forecast below remains the starting state for the [game-card demo](GAME_CARD_DEMO.md).

## After the 19:25 drop (Sat 21 Nov, current baseline; the sections below it are STALE history)
Source of the new inputs: `soony/context/launch_status.xlsx` (Saturday 13:00), `soony/master/bom_delta_2026-11-21.csv`, `components_update_2026-11-21.csv`, `products.csv` (day_one_qty), supplier `profile.json` v2, PackRight `components_delta.csv`, CPO memo, org chart v2, `soony/news/2026-11-21_export_controls.json`. Rules the engine applies (src/truth): the latest dated source wins for packed counts (launch status 13:00 beats the pack-out log, which ends 19 Nov; both are shown in the issues), rates come from the launch status, and the stock snapshot (20 Nov) is reduced by the parts of the copies packed since the log (42,000 STD + 6,300 CE) x BOM quantity. ECN-2026-118: the 64,000 rev B sleeves (GR 5000413064 of PO 4500318738 line 1, PackRight) are not usable stock for Standard, and PackRight's open rev B inbound is not counted. Collector's first (CPO memo) is the baseline policy (`ce_first`). Remaining pack-out time starts at the status time: Sat 13:00-22:00 plus Sun 06:00-20:00 = 23 h (was 30 h).

- Forecast snapshot: `2026-11-21_1925`.
- Forecast input SHA-256: `808d217e353478e99bdfb31b6f8fdf54790471a80d943f5d96ca3ccce86b74dd`.
- Launch cutoff: `2026-11-22T20:00:00+01:00` (20:00 CET at DC-HAM). Demand 640,000 STD + 72,000 CE.
- Packed (launch_status, Saturday 13:00): STD 554,000 (86.6%), CE 53,100 (73.8%). Remaining: STD 86,000, CE 18,900. Rates 6,000/h and 900/h. (Pack-out log to 19 Nov: STD 512,000, CE 46,800.)

## Forecast (default model, 500 runs, 30-minute slots, CE first)

| Edition | Target | Expected packed (p10 / p50 / p90) | P(reach target) | First stop |
|---|---|---|---|---|
| STD | 640,000 | 614,650 / 614,650 / 626,650 | 0% | Game card 128 GB |
| CE | 72,000 | 62,550 / 62,550 / 64,350 | 0% | Game card 128 GB |

Unchanged against the 14:36 forecast, as expected: need and stock fall by the same amount, and the game card stops both lines. At the median, STD is 25,350 copies short and CE is 9,450 short. STD-first alternative: STD 615,100 / CE 62,100. Historical-delay sensitivity (`python3 -m src.truth.sensitivity`): CE median 66,100, STD 614,650, 0 of 500 trials reach either target. Pack-out optimizer (docs/PACKPLAN.md) at CE weight 1: CE 66,100 / STD 611,100 (same as before).

## Component gaps after the 19:25 drop (remaining need vs usable stock + inbound that can reach DC-HAM before 20:00)
| Part | Need | SAP stock | Usable stock | Inbound counted | Gap before inbound | Gap | Reason |
|---|---|---|---|---|---|---|---|
| CMP-GAM-001 Game card 128 GB | 104,900 | 118,400 | 70,100 | 28,000 | 34,800 | **6,800** | need and stock both fell by 48,300 (packed since the snapshot); air lot 020-48113256 flew 28,000 of 48,000; lot 020-48113304 held at supplier dock |
| CMP-GAM-008 Art book (CE) | 18,900 | 91,300 | 13,000 | 0 | 5,900 | **5,900** | 19,300 after the GR 5000413065 handwriting correction, minus 6,300 packed since the snapshot |
| CMP-GAM-010 Statue (CE, now critical) | 18,900 | 27,400 | 15,500 | 0 | 3,400 | **3,400** | 21,800 after the 5,600-pc quality hold, minus 6,300 |
| CMP-GAM-004 Sleeve (STD, rev C only) | 86,000 | 186,000 | 80,000 | 20,000 | **6,000** | 0 | 186,000 - 42,000 packed since the snapshot - 64,000 rev B lot (ECN-2026-118) = 80,000 usable rev C. Gap 0 only if Karton's 20,000 (SHP-2026-04313, road, booked, PO 4500318775 line 2, due 21 Nov) reaches Hamburg; PackRight's 150,000 rev B on NHMU7718206 and the rest of the ~675,000 open rev B must not be accepted |
| CMP-GAM-003 Case | 86,000 | 96,000 | 54,000 | 350,000 | 32,000 | 0 | 350,000 at Hamburg terminal (tracker wrongly says in transit); needs pickup |
| CMP-MAG-005 Lid magnet | 75,600 | 0 | n/a | n/a | n/a | 0 (assumed) | Supplier fits magnets inside CMP-GAM-007 box (BOM double count); CONFIRM with Felix Brunner. Export control hits deliveries after 2026-12-01 only |

Changed against the stale table: need and usable stock of every part fell with the packed copies; the three gaps 6,800 / 5,900 / 3,400 and the SAP-believed naive view are unchanged; new line: Standard sleeve, 6,000 before inbound. Poster CMP-GAM-009 (ECN-2026-119, rev A -> B, use up rev A) is no block. Statue CMP-GAM-010 critical = Y; Pune qualification expired 2026-10-30 (PP-07 section 5).

Money: use EUR 120 per Collector's copy as the hard number (CPO memo: a missing pre-order is refunded). The EUR 32 per Standard copy is unconfirmed: a late Standard copy is still sold. Collector's exposure at the median: 9,450 x EUR 120 = EUR 1,134,000 (unchanged).

## Invariants checked by tests (tests/test_numbers.py)
Packed STD 554,000 / CE 53,100; forecast table above; gaps 6,800 / 5,900 / 3,400 / 0 (sleeve); usable game card 70,100, sleeve 80,000; the sleeve rev B hold of 64,000.


## STALE (14:36 snapshot, before the 19:25 drop): Launch
- Old forecast snapshot: `2026-11-21_1436` (superseded; the test no longer checks it).
- Old input SHA-256: `12779acaf1251c18d55b3a084f906a3cee40c995cbd88ec524c4abfc8296d3e5`.
- Cutoff and demand unchanged (see the section above).
- Packed (packout_log, = launch plan): STD 512,000 (80%), CE 46,800 (65%). Remaining: STD 128,000, CE 25,200.

## STALE forecast at the 14:36 snapshot (500 runs, 30-minute slots, CE first)

| Edition | Target | Expected packed (p10 / p50 / p90) | P(reach target) | First stop |
|---|---|---|---|---|
| STD | 640,000 | 614,650 / 614,650 / 626,650 | 0% | Game card 128 GB |
| CE | 72,000 | 62,550 / 62,550 / 64,350 | 0% | Game card 128 GB |

The default forecast uses triangular handling delays by transport mode. P(reach target) is the share of simulations that meet the target. At the median, STD is 25,350 copies short and CE is 9,450 short.

## Historical supplier delay sensitivity

On the same snapshot and cutoff, `python3 -m src.truth.sensitivity` uses historical purchase-order delays. The CE median in that scenario is **66,100**. Zero of 500 trials reach the 72,000 CE target. Label this result as a sensitivity scenario when presenting it alongside the dashboard forecast.

## Forecast drift check

Run `DEMO_DATA_DIR=case-data python3 -m unittest discover -s tests -p test_numbers.py` from the repo root. The test runs the offline dashboard on the published snapshot and compares the launch cutoff and each edition’s target, P10, P50, P90, and target probability. The fingerprint hashes sorted relative POSIX paths as `path<TAB>file-sha256<LF>` lines, excluding hidden files and directories.

## STALE component gaps at the 14:36 snapshot (remaining need vs usable stock + inbound that can reach DC-HAM before 20:00)
| Part | Need | SAP stock | Usable stock | Inbound counted | Gap | Reason |
|---|---|---|---|---|---|---|
| CMP-GAM-001 Game card 128 GB | 153,200 | 118,400 | 118,400 | 28,000 | **6,800** | Air lot 020-48113256 flew 28,000 vs 48,000 planned; lot 020-48113304 held at supplier dock (EXW/forwarder) |
| CMP-GAM-008 Art book (CE) | 25,200 | 91,300 | 19,300 | 0 | **5,900** | GR 5000413065 booked 80,000 vs 8,000 ordered; handwritten correction on WZ-261116-473 |
| CMP-GAM-010 Statue (CE) | 25,200 | 27,400 | 21,800 | 0 | **3,400** | 5,600-pc lot on quality hold (9/125 defective, limit 3) |
| CMP-GAM-003 Case | 128,000 | 96,000 | 96,000 | 350,000 | 0 | 350,000 at Hamburg terminal (tracker wrongly says in transit); needs pickup |
| CMP-MAG-005 Lid magnet | 100,800 | 0 | n/a | n/a | 0 (assumed) | Supplier fits magnets inside CMP-GAM-007 box (BOM double count) — **CONFIRM with Felix Brunner** |

SAP-believed view (naive netting): game card 34,800, case 32,000, magnet 100,800 short; art book and statue show NO gap. That contrast is the pitch.

## Price of the first decision
- Art book hold: request 5,900 finished units (supplier express offer: 8,000 pcs overrun stock, loaded within 4 h, about 9 h drive). Estimated EUR 12,390 (materials estimate only; needs freight + dock slot). Owner per PP-07: buyer < EUR 50k.
- Other options (7 total): quality decision on statue, air split game card, air split statue, alternate source check, pack-out priority. No price yet on most — do not quote them.

## Data-quality claims we can state
- 282 documents processed, 0 extraction errors (orchestrator dataQuality).
- Delivery-note false alarms fell from about 12 to 3 after the T2 thousands-separator fix.
- SAP vs tracker: tracker xlsx lists 14 of 25 ERP shipments (agent finding, verified in one case: 04311 absent).
- Incoterm conflicts: 8 POs say DDP Hamburg in ERP vs EXW Boise on order confirmations.
- PO 4500318744 confirmed 2026-12-28 vs promised 2026-12-21.

## Value at stake (cost of goods, from products.csv std_cost_eur)
- STD 128,000 x 11.9 = EUR 1,523,200. CE 25,200 x 34.5 = EUR 869,400. NOT revenue. Revenue/penalty per missing copy: [ASK DR. VOGT].

## Open / not to claim until verified
- Magnet BOM line (double count vs real stop). Whether the 350k cases can be collected today. Real status of the dock-held game card lot. Any price other than the art book option. The EUR 12k pilot fee (a guess).


## Dr. Vogt's numbers (office hours Sat 21 Nov 19:00, recorded by Isil; reading to be confirmed). Medians and gaps are unchanged after the 19:25 drop; the CPO memo makes EUR 32 per Standard copy doubtful (late Standard copies are still sold), use EUR 120 per Collector's copy
- **L_CE = EUR 120** per Collector's Edition not delivered on time (retail 199.99; Soony receives 120 and must refund it). **L_STD = EUR 32** per Standard copy. Collector's Edition has priority. (Her wording on Standard was short; Isil to confirm.)
- **At stake today (baseline medians):** 25,350 Standard x 32 = EUR 811,200, plus 9,450 Collector's x 120 = EUR 1,134,000, **total about EUR 1,945,200.**
- **Dock slot + early customs for the 28,000-card air lot:** +21,216 Standard x 32 + 3,133 Collector's x 120 = **EUR 1,054,872** avoided (a fee below this pays).
- **Collector's-complete package** (art books + statues + game cards to Collector's first): +5,848 Collector's x 120 - 14,292 Standard x 32 = EUR 244,416, less EUR 12,390 art books = **about EUR 232,000** net, before the unquoted statue sort cost.
- **Optimizer protecting Collector's (docs/PACKPLAN.md, 66,100):** Collector's gap 5,900 (EUR 708,000) vs baseline 9,450 (EUR 1,134,000), but 3,550 fewer Standard (EUR 113,600): net about EUR 312,000.
- All figures are exposure assuming every copy not packed by Sunday 20:00 triggers the loss; not a forecast of actual refunds.
- **Approval authority is NOT pre-granted.** Isil recorded: she can only give information; approvals stay with the PP-07 owners (see docs/AUTHORIZATIONS.md).
