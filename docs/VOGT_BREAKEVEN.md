# Vogt break-even table: turn her "cost per missing copy" into decisions

isil-agent, Sat 21 Nov ~18:20. Forecast engine `counterfactual`, 500 trials, seed 1029, published snapshot. Expected (mean) packed copies; medians in brackets.
L_STD and L_CE = what one missing Standard / Collector's copy costs Soony on day one (her answer to question 1).

## Copies each decision gains
| Decision | Standard | Collector's | Known price |
|---|---:|---:|---|
| Today | 617,436 (614,650) | 62,967 (62,550) | — |
| **A. Dock slot + early customs for the 28,000-card air lot** (unloaded ≤4 h after landing Sun 12:00) | **+21,216** | **+3,133** | Fee unquoted |
| B. Karton art books, 5,900 (alone or after A) | ≈0 | ≈0 to +52 | €12,390 materials + freight |
| C. "Collector's complete": A + B + 3,400 statues + slow the Standard line to 4,000/h so game cards go to Collector's | −14,292 vs A | +5,848 vs A (reaches 72,000) | €12,390 + statue concession/rework (unquoted) |

Why B is worthless alone: game cards run out Saturday night for both lines, so extra art books cannot be packed. Art books and statues only pay off together with C. (Matches `docs/PACKPLAN.md`.)

## How to read her answer
- **A is worth any fee below 21,216 × L_STD + 3,133 × L_CE.** Even at cost of goods (L_STD €11.90, L_CE €34.50) that is about **€360,000**. Recommend A at any realistic fee; it still needs Katrin Jansen's dock release (PP-07 §3).
- **C is worth it only if 5,848 × L_CE > 14,292 × L_STD + €12,390 + statue cost.** Rule of thumb: a missing Collector's must cost **more than about 2.5× a missing Standard**.
  - Equal cost per copy → **no**, keep both lines at full speed.
  - L_STD €20 → yes only if L_CE > about **€51** (plus statue cost).
  - At cost of goods (€11.90 / €34.50) → marginally yes (€201,800 vs €182,500, before statue cost).
- **B on its own → no.** Do not buy the art books unless C is chosen.

## What to say in the room
After she names L_STD and L_CE: "Then the dock slot is clearly worth it. Saving game cards for the Collector's Edition [is / is not] worth losing about 14,000 Standard copies. Do you agree?" Her yes/no is the pack-out priority decision (question 2).

Limits: a model, not a quote. Fees for A, freight for B and the statue cost are unknown; the 4 h handling is an assumption to confirm with the site lead.
