"""Manual-effort model: how many person-hours the Manti agents replace per launch.

All task times are ASSUMPTIONS (triangular min / most likely / max, minutes per unit).
Unit counts come from case-data/ (308 files) and docs/ where marked DATA.
Run: python scripts/hours_model.py [--runs 10000] [--seed 7]
"""
import argparse
import random
import statistics as st

DROPS = 4  # ASSUME: initial set + 14:36 + 19:25 + late goods receipt (docs/NUMBERS.md)

# (agent, job it replaces, task, units, unit source, manual min/unit (lo, mode, hi),
#  human minutes/unit still needed with Manti (lo, mode, hi))
TASKS = [
    ("Intake", "Procurement assistant", "Check portal, diff and file each drop", DROPS, "ASSUME", (20, 40, 90), (2, 5, 10)),
    ("Intake", "Procurement assistant", "Open, name and file every document", 308, "DATA files", (0.5, 1, 2), (0, 0, 0.2)),
    ("Document reader", "Data clerk + translator", "Read PDFs/scans, key in numbers (PL/KO/ZH, handwriting)", 277, "DATA 217 pdf + 60 scans", (3, 6, 12), (0.2, 0.5, 1)),
    ("Document reader", "Data clerk + translator", "Re-read new files in later drops", 3 * 30, "ASSUME 30 new files x 3 drops", (3, 6, 12), (0.2, 0.5, 1)),
    ("Analyst", "Inventory / procurement analyst", "Match goods receipts to delivery notes", 392, "DATA goods_receipts.csv rows", (1, 2, 4), (0.05, 0.1, 0.3)),
    ("Analyst", "Inventory / procurement analyst", "Trace open shipments (ERP vs tracker vs advice)", 25 * DROPS, "DATA 25 shipments x drops", (5, 10, 25), (0.5, 1, 2)),
    ("Analyst", "Inventory / procurement analyst", "Check PO confirmations vs ERP (dates, Incoterms)", 447, "DATA PO lines", (1, 2, 5), (0.05, 0.1, 0.3)),
    ("Verifier", "Second analyst (four-eyes)", "Re-check each finding against its source", 40, "ASSUME 40 findings", (5, 10, 20), (1, 2, 4)),
    ("Planner", "Supply planner", "Net 12 parts x 2 editions (MRP) per drop", DROPS, "DATA 12 components", (120, 240, 480), (5, 10, 20)),
    ("Planner", "Supply planner", "Build what-if for each option", 7, "DATA 7 options", (60, 120, 240), (5, 10, 20)),
    ("Planner", "Supply planner / controller", "Break-even and profit case (once)", 1, "DATA", (180, 360, 720), (20, 30, 60)),
    ("Chaser", "Buyer", "Read or write supplier emails (incl. translation)", 93, "DATA 93 messages / 9 threads", (10, 20, 40), (2, 4, 8)),
    ("Chaser", "Buyer", "Track open threads per day", 9 * 3, "DATA 9 threads x 3 days", (5, 10, 20), (0.5, 1, 2)),
    ("Approval router", "Procurement manager / PMO", "Find PP-07 signer, write memo, chase sign-off", 7, "DATA 7 options", (30, 60, 120), (2, 5, 10)),
    ("Approval router", "Procurement manager / PMO", "Escalations (vacancy, SLA, limits)", 4, "ASSUME", (20, 45, 90), (2, 5, 10)),
    ("Triage", "War-room lead", "Re-prioritise after each drop", DROPS, "ASSUME", (30, 60, 120), (10, 15, 30)),
    ("Claims", "Contract buyer / legal", "Check late-delivery claims per PO line", 30, "DATA 30 Hwaseong lines", (10, 20, 40), (1, 3, 5)),
]


def tri(lo, mode, hi, rng):
    return lo if hi == lo else rng.triangular(lo, hi, mode)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    agents = list(dict.fromkeys(t[0] for t in TASKS))
    man = {g: [] for g in agents}
    res = {g: [] for g in agents}
    tot_m, tot_r, launches, rate = [], [], [], []
    for _ in range(a.runs):
        sm, sr = 0.0, 0.0
        for g in agents:
            m = sum(t[3] * tri(*t[5], rng) for t in TASKS if t[0] == g) / 60
            r = sum(t[3] * tri(*t[6], rng) for t in TASKS if t[0] == g) / 60
            man[g].append(m); res[g].append(r); sm += m; sr += r
        tot_m.append(sm); tot_r.append(sr)
        launches.append(tri(4, 6, 10, rng))  # ASSUME launches per year
        rate.append(tri(55, 70, 90, rng))    # ASSUME loaded EUR/h, DACH procurement

    print(f"{'Agent':16} {'Manual h p10/p50/p90':>24} {'With Manti p50':>15} {'Saved p50':>10}")
    for g in agents:
        print(f"{g:16} {pct(man[g],.1):7.1f}/{pct(man[g],.5):6.1f}/{pct(man[g],.9):6.1f} "
              f"{pct(res[g],.5):15.1f} {pct([m-r for m,r in zip(man[g],res[g])],.5):10.1f}")
    saved = [m - r for m, r in zip(tot_m, tot_r)]
    print(f"{'TOTAL':16} {pct(tot_m,.1):7.1f}/{pct(tot_m,.5):6.1f}/{pct(tot_m,.9):6.1f} "
          f"{pct(tot_r,.5):15.1f} {pct(saved,.5):10.1f}")
    print(f"Saved per launch p10/p50/p90: {pct(saved,.1):.0f} / {pct(saved,.5):.0f} / {pct(saved,.9):.0f} h")
    print(f"Share of manual time removed (p50): {1 - st.median(r/m for r, m in zip(tot_r, tot_m)):.0%}")
    print(f"Person-weeks (40 h) per launch p50: {pct(tot_m,.5)/40:.1f}")
    crunch = [m / 24 for m in tot_m]  # 2-day crunch, 12 h/day per person
    print(f"People needed to finish in a 48 h crunch (12 h/day) p10/p50/p90: "
          f"{pct(crunch,.1):.1f} / {pct(crunch,.5):.1f} / {pct(crunch,.9):.1f}")
    yr = [s * l for s, l in zip(saved, launches)]
    print(f"Hours saved per year p10/p50/p90: {pct(yr,.1):.0f} / {pct(yr,.5):.0f} / {pct(yr,.9):.0f}"
          f"  (= {pct(yr,.5)/1600:.2f} FTE at 1,600 h/yr)")
    eur = [s * r for s, r in zip(saved, rate)]
    print(f"Labour EUR saved per launch p10/p50/p90: {pct(eur,.1):,.0f} / {pct(eur,.5):,.0f} / {pct(eur,.9):,.0f}")


if __name__ == "__main__":
    main()
