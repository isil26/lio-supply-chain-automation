# NUMBERS.md — the single frozen number set (deck, demo, video must use ONLY these)
The dashboard, deck, and pitch use the default readiness model. These figures are from the complete post-drop snapshot. When publishing a new snapshot, refresh its fingerprint and forecast together, then update the deck and video.

## Launch
- Forecast snapshot: `2026-11-21_1436` (post-drop).
- Forecast input SHA-256: `12779acaf1251c18d55b3a084f906a3cee40c995cbd88ec524c4abfc8296d3e5`.
- Launch cutoff: `2026-11-22T20:00:00+01:00` (20:00 CET at DC-HAM). Demand 640,000 STD + 72,000 CE.
- Packed (packout_log, = launch plan): STD 512,000 (80%), CE 46,800 (65%). Remaining: STD 128,000, CE 25,200.

## Forecast (default model, 500 runs, 30-minute slots, CE first)

| Edition | Target | Expected packed (p10 / p50 / p90) | P(reach target) | First stop |
|---|---|---|---|---|
| STD | 640,000 | 614,650 / 614,650 / 626,650 | 0% | Game card 128 GB |
| CE | 72,000 | 62,550 / 62,550 / 64,350 | 0% | Game card 128 GB |

The default forecast uses triangular handling delays by transport mode. P(reach target) is the share of simulations that meet the target. At the median, STD is 25,350 copies short and CE is 9,450 short.

## Historical supplier delay sensitivity

On the same snapshot and cutoff, `python3 -m src.truth.sensitivity` uses historical purchase-order delays. The CE median in that scenario is **66,100**. Zero of 500 trials reach the 72,000 CE target. Label this result as a sensitivity scenario when presenting it alongside the dashboard forecast.

## Forecast drift check

Run `DEMO_DATA_DIR=/path/to/2026-11-21_1436/soony-data python3 -m unittest discover -s tests -p test_numbers.py` from the repo root. The test runs the offline dashboard on the published snapshot and compares the launch cutoff and each edition’s target, P10, P50, P90, and target probability. The fingerprint hashes sorted relative POSIX paths as `path<TAB>file-sha256<LF>` lines, excluding hidden files and directories.

## Component gaps (remaining need vs usable stock + inbound that can reach DC-HAM before 20:00)
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
