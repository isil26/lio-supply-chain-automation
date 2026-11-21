# FINDINGS (living doc)

Status key: VERIFIED = checked by me against files; AGENT = reported by a subagent, not yet verified.

## Docs/receiving audit (subagent, 200 OCs parsed, 6 of 60 scans viewed)
- VERIFIED: PO 4500318768 line 3 (SUP-0028, CMP-GAM-008 art book): ordered 8,000, GR 5000413065 booked 80,000 "over delivery accepted" (delivery note WZ-261116-473 has 80.000 struck through, handwritten 8 000). Stock inflated by ~72,000 art books if SAP is believed. Art book is a Collector's Edition part. 
- VERIFIED (partially): PO 4500318727 (SUP-0018 statues CMP-GAM-010, 5,600) booked 5,600 unrestricted in GR 5000413063. AGENT: inspection report says 9/125 defective, accept limit 3 -> lot fails AQL, block requested. Statues are a CE part.
- AGENT: SUP-0029 order confirmations print the cover sleeve (CMP-GAM-004) to artwork rev B, SUP-0028 prints rev C. Likely stale artwork.
- AGENT: SUP-0029 OCs say lid closure magnets (RM-N42-D0401, 4 pcs/box) are fitted in their plant, included in unit price -> relates to the "no lid magnets in stock list" question.
- AGENT: SUP-0011 OCs: EXW Boise, "DDP is not agreed"; ERP says DDP Hamburg for several 2026 POs -> freight/duties may be billed on top.
- AGENT: SUP-0028 WZ-260930-528 sleeve delivery partial 47,400 of 70,000 (PO 4500318731), ~22,600 outstanding.
- AGENT: SUP-0019 pins (PRM-GH6-PIN): 3 delivery notes (78,000 pcs) with blank PO, booked to misc.
- AGENT: SUP-0019 open PO 4500318744 confirmed 2026-12-28 vs promised 12-21 (after launch).
- AGENT: price drift OC vs PO on 4 lines (SUP-0010 x3, SUP-0011 x1). No quantity differences on any OC line.
- AGENT: unconfirmed open POs: 4500318769, 4500318775, 4500318782, 4500318783; 4500318784/791 awaiting approval.

## Document formats (for extraction agent)
- OC: `OA<8d>_<PO>.pdf`, text-based, same table layout for all suppliers (Item 00010 -> po_line 1, material, qty with comma thousands, price, currency, confirmed ISO date); footers hold the free-text risks. SUP-0029 uses own codes PR-CC-0312=CMP-GAM-003, PR-SL-0604=CMP-GAM-004, PR-RB-2207=CMP-GAM-007.
- Delivery notes: images, prefixes DN- (SUP-0010/11/18), SN- (0019/0029, Chinese), WZ- (0028, Polish). Dots/spaces are thousands separators; handwritten corrections override printed values.
- Tooling: no pdftotext/tesseract on this machine; `gs -sDEVICE=txtwrite` works for PDF text; images need VLM.

## Contracts & notices scan (subagent; scanned contracts for SUP-0019/0028 read visually; AGENT-reported, not verified by me)
- Karton Nowak (SUP-0028, sleeve/art book/poster/leaflet) technical downtime notice (Polish, 09.11.2026): offset line + hardcover bindery down 21.11 14:00 -> 23.11 06:00. Only finished stock ships; rush only on digital line, max 15,000 per 36 h. Offset rush cutoff 21.11 09:00 (likely passed). Contract s3.2 promises 50,000 in 36 h at +35% -> conflict (contractual argument, no capacity). Art book/poster/leaflet are single-source; art book not covered by rush clause.
- Magnets: PackRight (SUP-0029) fits NdFeB lid magnets inside the collector's box (Annex B sub-supplier Jiangxi RareMag, Ganzhou). Force majeure explicitly covers rare-earth export restrictions -> no remedy for Soony. Answers the "no lid magnets in stock list" question: magnets are not stocked separately (CMP-MAG-005 in the supplier's price).
- Steel case CMP-GAM-006: single source Dongguan (70 d lead). Statue CMP-GAM-010: 80% Dongguan / 20% Pune; Pune only "conditional" - PPAP + written release by Supplier Quality and Category Lead required (the Category Lead position is vacant!) -> Pune statues cannot be counted on; also see failed AQL lot.
- 128 GB card: 70% Hwaseong (63 d) / 30% Boise (28 d, EXW, seller-favourable contract: delay liability capped at product price, shipping dates "estimates").
- Hwaseong LTA expires 31 Dec 2026, renewal signed by 15 Dec or list price/NET30/no capacity reservation. Late-delivery damages 2%/week cap 10% (Soony can claim). Others 0.5%/week cap 5%.
- Price drift vs components.csv (stale master): Boise +7.2% (10.20 -> 10.93), Dongguan about +6.1%, PackRight +4% (2025 notice vs "fixed for calendar year" clause).
- Artwork clause mismatch: PackRight prints to revision in component master at PO date; Karton to last revision released in writing -> explains rev B vs rev C sleeve conflict.
- Dongguan CNY shutdown up to 12 days (schedule due 30 Nov); post-launch only.


## Stock / shipments / BOM analysis (subagent; items marked V re-checked by me in the files)
- V: Packed 512,000 STD / 46,800 CE (packout_log). Remaining STD 128,000, CE 25,200.
- V: Stock figures are book values. Usable stock (my check of batches): 008 art book 91,300 book but 80,000 batch is the 8,000/80,000 booking error -> ~19,300 usable vs 25,200 needed (short ~5,900). 010 statue 27,400 book, batch 5,600 is the AQL-failing lot -> ~21,800 usable vs 25,200 (short ~3,400; AGENT: 10,000 more ETA 11-27).
- V: CMP-MAG-005 (lid magnet, 4 per CE in bom.csv): stock 0, no PO/GR/shipment found. AGENT: 100,800 needed; yet 46,800 CE were packed -> BOM line likely stale/double counted OR a total CE stop. Contract notice says PackRight fits magnets in the box (CMP-GAM-007) -> likely BOM double count; confirm with Felix/Engineering.
- AGENT: 001 game card needs 153,200, stock 118,400; short 34,800 unless air lot SHP-2026-04311 (48,000, ICN->FRA) arrives. V: that shipment is status "booked", ETD 11-20 ETA 11-21, not in the tracker. Realistic DC-HAM arrival 11-22/23 -> little or no use before 20:00.
- AGENT: 003 case needs 128,000, stock 96,000; 350,000 in SHP-2026-04276 is at CTA Hamburg ("arrived_port, available for pick-up") but tracker says "in transit, call terminal". Action: truck it out now.
- AGENT: at plan rate (900 CE/h) art book runs out ~Sun 11:30, statue ~Sun 14:00, game card ~Sun 07:00 without air lot.
- AGENT: tracker xlsx has 14 rows vs 25 in ERP; missing all air and road shipments (04310, 04311, 04313, ...). Status conflicts 04276, 04281. ERP shipment->PO links are cartesian (no line level, no qty).
- AGENT: ETAs = ETD + standard transit with no port/customs/drayage lag; 04298 and 04305 delayed. Vessel lat/lon values are over land (interpolated, unreliable).
- AGENT: supplier lateness: SUP-0010 50% of lines late (avg 4.2 d, max 17); SUP-0019 promises ~8 d after requested; others 16-29% late (<=4 d). Single sources: 006 (0019), 007 (0029), 008/009 (0028).
- AGENT: stock last_count predates recent GRs; cancellation lines (-23,000 / -9,500) cancel already-delivered POs; legacy PO file: MM/DD/YYYY, decimal comma, LIFNR numeric, EINDT=requested, ZZCONF=confirmed, WEDAT=actual, line 00510 -> 51.

## What breaks first (draft ranking)
1. CE: magnets (BOM question) 2. CE: art book 3. CE: statues (AQL-failed lot; release needs vacant Category Lead) 4. Both: 001 game cards 5. STD: 003 cases stuck at CTA.

## Still pending
- T1 ingestion (Codex), T6 UI (Copilot), T3 readiness engine (me).

## Questions for office hours
- Dr. Vogt: cost of a missing copy; who signs air freight (see approval_policy_PP-07.pdf).
- Felix Brunner: lid magnets; which parts are single-sourced; real status of the 20 open shipments.
