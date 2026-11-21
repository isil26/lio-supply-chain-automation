# Break-even with Dr. Vogt's numbers (T84)

isil-agent, Sat 21 Nov ~19:45. Forecast engine `counterfactual`, 500 trials, seed 1029. Expected (mean) copies gained versus today.

**Loss per copy not packed by Sun 20:00** (Dr. Vogt, office hours Sat 19:00, recorded by Isil; see `docs/NUMBERS.md`):
- **L_CE = €120** per Collector's copy: Soony refunds it even if the copy ships one day late. **Hard number.**
- **L_STD = €32** per Standard copy: **unconfirmed.** The CPO memo (19:25 drop) says a late Standard copy still sells, so the true loss may be close to €0. Every action below is shown both ways.

> **Baseline warning:** these runs use the pre-drop snapshot (128,000 Standard / 25,200 Collector's left to pack). The 19:25 drop says 86,000 / 18,900 are left, and ECN-118 blocks rev B sleeves. Refresh this page once T88 updates the engine.

## Which actions pay off
| Action | Copies gained | Worth (L_STD €32) | Worth (Standard costs €0) | Known cost | Verdict |
|---|---|---:|---:|---|---|
| **A. Dock slot + early customs** for the 28,000-card air lot (AWB 020-48113256, unloaded ≤4 h after landing Sun 12:00) | +21,216 STD, +3,133 CE | **€1,054,872** | **€375,960** | Fee unquoted | **Do it.** Any fee below €376k pays even if Standard costs nothing. |
| **B. Karton art books**, 5,900, on their own | ≈0 | ≈€0 | ≈€0 | €12,390 + freight | **Only as part of C or D.** Game cards run out first. |
| **C. Collector's first**: B + 3,400 statues + game cards to Collector's before Standard (the CPO memo now mandates this order) | +5,848 CE, −14,292 STD vs A | **€232,026** net | **€689,370** net | €12,390 + statue sorting or rework | **Do it.** Pays at either Standard value. |
| **D. Full save plan**: release the held Boise lot (SHP-2026-04314, 36,000 cards, EXW, planned Tue 24 Nov) and have it on the line by **Sun 08:00**, plus B and statues | +22,564 STD, +9,033 CE → **640,000 STD and 72,000 CE** | **€1,806,008** | **€1,083,960** | Emergency air or charter from the US, unquoted | **Do it if freight is below ~€1.08M.** Above €200k it goes to the CPO the same hour (CPO memo, PP-07 §4). |

Arithmetic: worth = ΔSTD × L_STD + ΔCE × L_CE; net = worth − known cost. Statue cost, freight and dock fee are not quoted, so treat net figures as upper bounds.

## What this means for the action queue (T81)
1. **D is the only action that saves every copy.** It needs the Boise lot released (EXW, forwarder) and in Hamburg by Sunday 08:00. Ask Felix Brunner whether that's physically possible (Sun 09:00 slot) and get a freight quote now.
2. **A is the fallback and is worth it on Collector's refunds alone.** It needs Katrin Jansen's dock release (PP-07 §3).
3. **C is policy now:** the CPO memo puts Collector's first, and Quality & Compliance must release the statues (statue is now critical; Pune's conditional release expired 30 Oct).
4. Do not buy the art books unless C or D goes ahead.

Limits: a model, not quotes. The 4 h handling, the Sun 08:00 Boise arrival and the statue yield are assumptions for Logistics and Quality to confirm.
