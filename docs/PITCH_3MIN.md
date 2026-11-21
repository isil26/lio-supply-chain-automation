# 3-minute pitch + demo script (T8, owner: nick). ALL NUMBERS come from docs/NUMBERS.md (single source). Assumptions marked [A]

## Story in one line
"SAP shows the Collector's Edition fine. It isn't: an 80,000-vs-8,000 art-book booking and a failed statue lot are invisible to it. Our agents read the paper SAP never sees."

## 0:00-0:30 Problem (hook), spoken (about 80 words)
"Sunday, 8 p.m. Soony's Grand Heist launches: 640,000 standard boxes, 72,000 numbered Collector's Editions, one warehouse in Hamburg. Procurement told us: 'We find out at the dock.' SAP shows the Collector's Edition fine. It isn't. A goods receipt booked 80,000 art books where 8,000 were ordered, and a handwritten correction on the delivery note says so. A statue lot failed inspection but still counts as stock. We read the paper SAP never sees. Watch."
(Do NOT say "SAP says Soony is fine": SAP already shows game card, case and magnet gaps; what it hides is art book and statues. Game card 128 GB is the first line stop.)

## 0:30-2:15 Live demo (one storyline, start the demo early)
1. **SAP view vs reality** (control room). Naive BOM netting on SAP stock says only game cards, cases and lid magnets look short. Our system says different (verified independently from raw CSVs):
   | Part | SAP-believed gap | Our corrected gap | Why |
   |---|---|---|---|
   | Art book (CE) | 0 | ~5,900 | goods receipt booked 80,000 vs 8,000 ordered; delivery note has handwritten correction |
   | Statue (CE) | 0 | ~3,400 | 5,600-unit lot failed quality inspection (9/125 defects, limit 3) but booked unrestricted |
   | Game card 128 GB | 34,800 | 6,800 | air lot flew 28,000 of 48,000 planned (supplier shipping advice); a second lot is held at the supplier dock pending EXW/forwarder. Realistic ETAs, not tracker dates |
   | Case | 32,000 | 0 | 350,000 already at Hamburg terminal; tracker wrongly says "in transit" |
   | Lid magnet | 100,800 | 0 | supplier fits magnets inside the box (contract/OC footer) — BOM line double-counts |
   Click any number -> source file, page, quote (provenance).
2. **Forecast.** Monte Carlo over 30-minute shift buckets: today we expect about 614,650 of 640,000 Standard and 62,550 of 72,000 Collector's; game card 128 GB stops both lines first. State it as a scenario frequency, not a prediction.
3. **New data drop live** (replay mode): a supplier express offer lands (art book overrun stock, 8,000 pcs, loaded within 4 h, ~9 h drive). Gauge and options update.
4. **Agent acts.** Supplier Chaser drafts the request in the supplier's language, shows the approval gate (PP-07 limits: buyer < €50k, category lead < €500k, head of procurement < €2M). Human approves; mock supplier replies messily; agent parses and updates state.
5. **Decision card with a price** for Dr. Vogt (e.g. art book hold, quote ~EUR 12.4k in current build) vs cost of a missed copy.

## 2:15-2:45 How it works (one slide)
Portal sync (SHA-256 diff) -> typed ERP + OCR/LLM document facts with citations -> MRP + shift simulation (deterministic tools) -> chaser + decision agents -> control room. LLM reads/translates/drafts; every number comes from a tool; nothing hardcoded; re-runs when a drop arrives.

## 2:45-3:00 Business case
- Pain: every manufacturer with a hard ship date and multilingual paper suppliers (games, consumer electronics, launches, seasonal retail).
- Value at stake on Soony alone (from products.csv std cost, cost of goods not revenue): Standard 128,000 x EUR 11.9 = ~EUR 1.52M; CE 25,200 x EUR 34.5 = ~EUR 0.87M of finished goods that cannot ship if a part is missing. [A: revenue/penalty per missing copy from Dr. Vogt — ASK IN OFFICE HOURS]
- Price [A]: per-launch fee or per-supplier subscription; pitch as "<1% of goods at risk". Replace with Vogt's number.
- One line: "We spent EUR X to move P(on time) from A% to B%." (fill from final run)

## Backup plan
Replay mode (`python3 -m src.orchestrator --demo`), recorded 3-min video, cached outputs. Do not rely on venue Wi-Fi.

## Office-hour questions that sharpen this pitch
- Dr. Vogt: cost of a missing copy on day one? Who signs air freight? What would Soony pay per launch for this?
- Felix Brunner: are the 350k cases really at CTA and can they be picked up today? Real status of the 48k game cards (booked air)? Is the lid magnet in the BOM real?
- Nils Berger (precise only): why does the tracker omit 11 ERP shipments? Is the legacy PO export complete?
