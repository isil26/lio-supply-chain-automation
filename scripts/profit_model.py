#!/usr/bin/env python3
"""Profit model for the GH6 launch recovery (T92, sonnet-profit).

Pure Python, deterministic, no network. Run:
    .venv/bin/python scripts/profit_model.py                # base case, markdown
    .venv/bin/python scripts/profit_model.py --scenario low|base|high   # cost range
    .venv/bin/python scripts/profit_model.py --set L_STD_LATE=10 --set P_A=0.4
Every number is an entry in PARAMS with value, unit, source and status
(DATA = from the repo files, ENGINE = engine output, ASSUME = our assumption,
 UNCONFIRMED = told to us but not verified). Change a value, rerun, everything re-derives.

Model in one line: for each subset S of 7 actions, expected net value =
  E[ L_CE*(CE_short_empty - CE_short_S) + L_STD*(STD_short_empty - STD_short_S) ] - costs(S),
where the packed copies come from a closed-form part-constraint model (min over shared parts),
so actions interact (art books and statues only pay with Collector's first; game cards bind both).
Action success is random (independent Bernoulli); costs are paid whether or not it succeeds.
"""
import argparse
import itertools
import math

# name: (value, unit, source, status)
PARAMS = {
    # --- targets and packed (docs/NUMBERS.md, kickoff snapshot; totals stay valid after the 19:25 drop per NEW_DROP note) ---
    "TARGET_CE": (72000, "copies", "docs/NUMBERS.md (launch plan)", "DATA"),
    "TARGET_STD": (640000, "copies", "docs/NUMBERS.md / products.csv day_one_qty", "DATA"),
    "PACKED_CE": (46800, "copies", "NUMBERS.md kickoff; drop 19:25 says 53,100 and the same totals", "DATA"),
    "PACKED_STD": (512000, "copies", "NUMBERS.md kickoff; drop 19:25 says 554,000 and the same totals", "DATA"),
    # --- part limits (additional copies that each part allows) ---
    "CARD_STOCK": (118400, "cards", "NUMBERS.md CMP-GAM-001 usable stock", "DATA"),
    "CARD_AIR_LOT_COPIES": (24349, "cards usable", "VOGT_BREAKEVEN A: 21,216 STD + 3,133 CE (engine counterfactual)", "ENGINE"),
    "ART_STOCK_CE": (19300, "CE", "NUMBERS.md CMP-GAM-008 usable 19,300", "DATA"),
    "ART_BUY_CE": (5900, "CE", "NUMBERS.md Karton buy 5,900 of 8,000 offered", "DATA"),
    "STATUE_STOCK_CE": (21800, "CE", "NUMBERS.md CMP-GAM-010 usable 21,800", "DATA"),
    "STATUE_RELEASE_CE": (3400, "CE", "NUMBERS.md gap 3,400 (lot of 5,600 on hold)", "DATA"),
    "CASE_STOCK_STD": (96000, "STD", "NUMBERS.md CMP-GAM-003 stock", "DATA"),
    "CASE_TERMINAL": (350000, "cases", "NUMBERS.md 350,000 at Hamburg terminal, needs pickup", "DATA"),
    "SLEEVE_REVC_STD": (122000, "STD", "coord/HANDOFFS T89: usable rev C 122,000 (rev B unusable, ECN-118)", "DATA"),
    "SLEEVE_BUY_STD": (6000, "STD", "NEW_DROP: Standard sleeve gap about 6,000, to be recomputed", "ENGINE"),
    "BASE_CE_ADD": (15750, "CE", "PACKPLAN baseline CE first: 62,550 - 46,800", "ENGINE"),
    "CE_RATE_CAP": (27000, "CE", "900/h x 30 h of shifts (PACKPLAN shifts, launch_status rate)", "DATA"),
    # --- value of a missing or late copy ---
    "L_CE": (120.0, "EUR/copy", "Dr. Vogt, office hours 21 Nov 19:00 (refund of what Soony receives)", "DATA"),
    "L_STD_VOGT": (32.0, "EUR/copy", "Dr. Vogt, wording short, Isil to confirm", "UNCONFIRMED"),
    "P_CANCEL_STD": (0.05, "share", "share of late Standard buyers that cancel (CPO memo: Tuesday copy is still sold)", "ASSUME"),
    "DELAY_COST_STD": (1.4, "EUR/copy", "service contact / small voucher per late Standard copy", "ASSUME"),
    "STD_COST": (11.9, "EUR/copy", "products.csv std_cost_eur", "DATA"),
    "CE_COST": (34.5, "EUR/copy", "products.csv std_cost_eur", "DATA"),
    # --- probabilities of success (all assumptions; how to learn: see PROFIT_PLAN section 1) ---
    "P_A": (0.60, "prob", "PACKPLAN: only ~29% chance the lot fits shifts with no action; dock slot + early customs raises it", "ASSUME"),
    "P_B": (0.85, "prob", "collect cases: terminal pickup, tracker error known", "ASSUME"),
    "P_B_IDLE": (0.30, "prob", "cases reach the line with nobody acting (tracker says in transit)", "ASSUME"),
    "P_C": (0.80, "prob", "Karton express offer quoted, DAP, 4 h load + 9 h drive, Karton in downtime", "ASSUME"),
    "P_D": (0.75, "prob", "100% sort of 5,600 lot: expected good 5,600 x (1 - 9/125) = 5,197 >= 3,400; Quality signs", "ASSUME"),
    "P_E": (0.30, "prob", "Karton prints rev C while in downtime until Mon 06:00", "ASSUME"),
    "P_F": (0.90, "prob", "CPO memo mandates Collector's first; shop-floor execution risk", "ASSUME"),
    "P_G": (0.95, "prob", "balance flight 23 Nov lands 24 Nov (success = lands, but after the cutoff)", "ASSUME"),
}

# cost (EUR) low / base / high per action; cost is paid whether or not the action succeeds
COSTS = {
    "A": (3000, 8000, 25000),   # dock priority + broker + FRA-HAM truck + weekend premium (ranges bounded by web [S] figures, see doc)
    "B": (500, 1500, 6000),     # terminal pickup trucks + detention
    "C": (13390, 14390, 17390), # EUR 12,390 materials (NUMBERS.md) + dedicated 9 h truck (1,000 / 2,000 / 5,000)
    "D": (2800, 5600, 12000),   # 100% sort 5,600 pcs at EUR 0.5 / 1.0 / 2.1 each
    "E": (1000, 3000, 8000),    # express rev C sleeves 6,000 pcs
    "F": (0, 2000, 10000),      # CE cell overtime / re-sequencing
    "G": (3500, 5600, 9000),    # 20,000 cards x 0.05 kg = 1,000 kg x USD 4.3-5.4/kg [S] + clearance + truck
}
NAMES = {
    "A": "Dock slot + early customs, 28,000-card air lot",
    "B": "Collect the 350,000 cases from the terminal",
    "C": "Karton art-book express buy (5,900)",
    "D": "Statue lot sort / concession (3,400)",
    "E": "Order rev C sleeves (ECN-118)",
    "F": "Collector's first + slow Standard to feed it",
    "G": "Air freight of the 20,000-card balance (lands 24 Nov)",
}
APPROVER = {
    "A": "Site lead Katrin Jansen (dock); freight/fees <= EUR 200k/month: Category Lead Tobias Brandt; above: CPO",
    "B": "Site lead Katrin Jansen / DC-HAM receiving (Felix Brunner confirms); no PP-07 spend limit hit",
    "C": "Buyer Paul Winter (< EUR 50k)",
    "D": "Supplier Quality Lead Daniel Okafor + exception by Head of Procurement (Collector's seat vacant)",
    "E": "Sofia Marchetti (artwork rev C) + buyer Paul Winter (< EUR 50k)",
    "F": "CPO Jonas Lindqvist (memo already mandates); pack-out plan owner",
    "G": "Category Lead Tobias Brandt (< EUR 200k/month); no launch effect",
}
ACTIONS = list("ABCDEFG")


def pv(p, name):
    return p[name][0]


def l_std(p):
    """EUR per Standard copy not packed by the cutoff (late, not refunded)."""
    return p["P_CANCEL_STD"][0] * p["L_STD_VOGT"][0] + p["DELAY_COST_STD"][0]


def packed(p, s):
    """Closed-form packed totals for success set s (dict action->bool). Returns (CE_total, STD_total)."""
    cards = pv(p, "CARD_STOCK") + (pv(p, "CARD_AIR_LOT_COPIES") if s["A"] else 0)
    cap_art = pv(p, "ART_STOCK_CE") + (pv(p, "ART_BUY_CE") if s["C"] else 0)
    cap_stat = pv(p, "STATUE_STOCK_CE") + (pv(p, "STATUE_RELEASE_CE") if s["D"] else 0)
    need_ce = pv(p, "TARGET_CE") - pv(p, "PACKED_CE")
    need_std = pv(p, "TARGET_STD") - pv(p, "PACKED_STD")
    if s["F"]:
        ce_add = min(need_ce, cap_art, cap_stat, pv(p, "CE_RATE_CAP"), cards)
    else:
        a_ce = 3133 if s["A"] else 0  # engine split of the air lot under baseline policy
        ce_add = min(pv(p, "BASE_CE_ADD") + a_ce, cap_art, cap_stat, need_ce)
    case_cap = pv(p, "CASE_STOCK_STD") + (pv(p, "CASE_TERMINAL") if s["B"] else 0)
    sleeve_cap = pv(p, "SLEEVE_REVC_STD") + (pv(p, "SLEEVE_BUY_STD") if s["E"] else 0)
    std_add = min(need_std, case_cap, sleeve_cap, max(0, cards - ce_add))
    return pv(p, "PACKED_CE") + ce_add, pv(p, "PACKED_STD") + std_add


def loss(p, ce, std):
    return pv(p, "L_CE") * (pv(p, "TARGET_CE") - ce) + l_std(p) * (pv(p, "TARGET_STD") - std)


def probs(p):
    return {a: pv(p, "P_" + a) for a in ACTIONS}


def distribution(p, subset):
    """Yield (probability, ce, std, loss) over joint success of the selected actions (+ idle luck for B)."""
    pr = probs(p)
    rand = list(subset)
    if "B" not in subset:
        rand.append("B")  # B may still happen with nobody acting
    for bits in itertools.product([0, 1], repeat=len(rand)):
        w = 1.0
        s = {a: False for a in ACTIONS}
        for a, b in zip(rand, bits):
            q = pr[a] if (a in subset) else pv(p, "P_B_IDLE")
            w *= q if b else 1 - q
            s[a] = bool(b)
        ce, std = packed(p, s)
        yield w, ce, std, loss(p, ce, std)


def evaluate(p, subset, cost_idx, empty_loss_mean):
    cost = sum(COSTS[a][cost_idx] for a in subset)
    dist = list(distribution(p, subset))
    gains = [(w, empty_loss_mean - l - cost) for w, ce, std, l in dist]
    mean = sum(w * g for w, g in gains)
    var = sum(w * (g - mean) ** 2 for w, g in gains)
    gs = sorted(gains, key=lambda x: x[1])
    cum, p10 = 0.0, gs[0][1]
    for w, g in gs:
        cum += w
        if cum >= 0.10:
            p10 = g
            break
    ce_m = sum(w * ce for w, ce, std, l in dist)
    std_m = sum(w * std for w, ce, std, l in dist)
    return {"subset": "".join(sorted(subset)) or "-", "cost": cost, "net": mean, "sd": math.sqrt(var),
            "p10": p10, "ce": ce_m, "std": std_m}


def run_all(p, cost_idx):
    empty_loss = sum(w * l for w, ce, std, l in distribution(p, ()))
    rows = []
    for k in range(len(ACTIONS) + 1):
        for sub in itertools.combinations(ACTIONS, k):
            rows.append(evaluate(p, sub, cost_idx, empty_loss))
    return rows, empty_loss


def pareto(rows):
    out = []
    for r in rows:
        if not any((o["net"] >= r["net"] and o["sd"] <= r["sd"]) and (o["net"] > r["net"] or o["sd"] < r["sd"]) for o in rows):
            out.append(r)
    return sorted(out, key=lambda r: -r["net"])


def eur(x):
    return f"{x:,.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["low", "base", "high"], default="base")
    ap.add_argument("--set", action="append", default=[], help="NAME=value override of a PARAMS entry")
    ap.add_argument("--no-sensitivity", action="store_true")
    a = ap.parse_args()
    p = dict(PARAMS)
    for kv in a.set:
        k, v = kv.split("=")
        p[k] = (float(v), p[k][1], p[k][2] + " [OVERRIDE]", "ASSUME")
    cost_idx = {"low": 0, "base": 1, "high": 2}[a.scenario]

    print(f"# Profit model output (scenario {a.scenario})\n")
    print("## Parameters\n| Name | Value | Unit | Status | Source |\n|---|---:|---|---|---|")
    for k, (v, u, s, st) in p.items():
        print(f"| {k} | {v:g} | {u} | {st} | {s} |")
    print(f"\nDerived: L_STD effective (late, not refunded) = P_CANCEL_STD x L_STD_VOGT + DELAY_COST_STD = EUR {l_std(p):.2f} per Standard copy. "
          f"CE margin if shipped = {pv(p,'L_CE') - pv(p,'CE_COST'):.1f} EUR (L_CE - std cost).\n")

    rows, empty_loss = run_all(p, cost_idx)
    ce0, std0 = packed(p, {x: False for x in ACTIONS})
    print(f"Do-nothing exposure (expected, B idle luck {pv(p,'P_B_IDLE'):.0%}): EUR {eur(empty_loss)}; "
          f"closed form with no action and cases collected = CE {ce0:,.0f}, STD {std0:,.0f}.\n")

    print("## Actions standalone (vs doing nothing)\n| Action | Cost EUR | Exp. copies CE | Exp. copies STD | Net EUR | ROI (net/cost) | P(success) | Approver (PP-07) |\n|---|---:|---:|---:|---:|---:|---:|---|")
    base_ce = next(r for r in rows if r["subset"] == "-")
    singles = []
    for x in ACTIONS:
        r = next(r for r in rows if r["subset"] == x)
        singles.append((x, r))
    for x, r in sorted(singles, key=lambda t: -t[1]["net"]):
        roi = r["net"] / r["cost"] if r["cost"] else float("inf")
        print(f"| {x} {NAMES[x]} | {eur(r['cost'])} | {r['ce'] - base_ce['ce']:+,.0f} | {r['std'] - base_ce['std']:+,.0f} | {eur(r['net'])} | {roi:,.1f} | {pv(p, 'P_' + x):.0%} | {APPROVER[x]} |")

    best = max(rows, key=lambda r: r["net"])
    print(f"\n## Best subset (of 2^7 = 128)\n**{best['subset']}**: net EUR {eur(best['net'])} expected, sd {eur(best['sd'])}, p10 {eur(best['p10'])}, cost {eur(best['cost'])}, "
          f"expected CE {best['ce']:,.0f}, STD {best['std']:,.0f}.\n")
    print("Top 8 subsets by expected net:\n\n| Subset | Net EUR | Cost EUR | sd | p10 | CE | STD |\n|---|---:|---:|---:|---:|---:|---:|")
    for r in sorted(rows, key=lambda r: -r["net"])[:8]:
        print(f"| {r['subset']} | {eur(r['net'])} | {eur(r['cost'])} | {eur(r['sd'])} | {eur(r['p10'])} | {r['ce']:,.0f} | {r['std']:,.0f} |")

    print("\nMarginal value of each action inside the best subset (drop one):\n\n| Action | Net lost if dropped EUR |\n|---|---:|")
    bset = set(best["subset"]) - {"-"}
    for x in sorted(bset):
        sub = "".join(sorted(bset - {x})) or "-"
        r = next(r for r in rows if r["subset"] == sub)
        print(f"| {x} {NAMES[x]} | {eur(best['net'] - r['net'])} |")

    print("\n## Pareto frontier (max expected net, min sd)\n| Subset | Net EUR | sd | p10 | Cost EUR |\n|---|---:|---:|---:|---:|")
    for r in pareto(rows):
        print(f"| {r['subset']} | {eur(r['net'])} | {eur(r['sd'])} | {eur(r['p10'])} | {eur(r['cost'])} |")

    # interactions
    def net(sub):
        return next(r for r in rows if r["subset"] == "".join(sorted(sub)) or (not sub and r["subset"] == "-"))["net"]
    print("\n## Interactions (non-additivity)\n")
    print(f"- C alone {eur(net('C'))}; D alone {eur(net('D'))}; F alone {eur(net('F'))}; C+D alone {eur(net('CD'))}; F+C+D {eur(net('CDF'))} "
          f"(sum of singles {eur(net('C') + net('D') + net('F'))}).")
    print(f"- A alone {eur(net('A'))}; F alone {eur(net('F'))}; A+F {eur(net('AF'))} (game cards bind both lines).")
    print(f"- E (sleeves) alone {eur(net('E'))}; A+E {eur(net('AE'))} (sleeves only bind once the air lot adds cards).")

    if not a.no_sensitivity:
        print("\n## Sensitivity (base costs): best subset and net by Standard late-copy cost and fee of action A\n")
        fees = [("low", COSTS["A"][0]), ("base", COSTS["A"][1]), ("high", COSTS["A"][2]), ("250k", 250000)]
        print("| L_STD effective EUR | " + " | ".join(f"A fee {n} ({eur(v)})" for n, v in fees) + " |\n|---|" + "---|" * len(fees))
        for lstd in (0.0, 1.4, 3.0, 10.0, 32.0):
            cells = []
            for n, v in fees:
                q = dict(p)
                q["P_CANCEL_STD"] = (0.0, "", "", "ASSUME")
                q["DELAY_COST_STD"] = (lstd, "", "", "ASSUME")
                saved = COSTS["A"]
                COSTS["A"] = (v, v, v)
                rr, _ = run_all(q, 1)
                COSTS["A"] = saved
                b = max(rr, key=lambda r: r["net"])
                cells.append(f"{b['subset']} / {eur(b['net'])}")
            print(f"| {lstd:g} | " + " | ".join(cells) + " |")
        print("\nL_CE sensitivity (best subset / net):\n\n| L_CE | best | net EUR |\n|---|---|---:|")
        for lce in (60, 90, 120, 160, 199.99):
            q = dict(p)
            q["L_CE"] = (lce, "", "", "ASSUME")
            rr, _ = run_all(q, cost_idx)
            b = max(rr, key=lambda r: r["net"])
            print(f"| {lce:g} | {b['subset']} | {eur(b['net'])} |")
        print("\nP_A sensitivity (probability the dock slot + customs actually works):\n\n| P_A | best | net EUR | A alone net EUR |\n|---|---|---:|---:|")
        for pa in (0.2, 0.4, 0.6, 0.8, 1.0):
            q = dict(p)
            q["P_A"] = (pa, "", "", "ASSUME")
            rr, _ = run_all(q, cost_idx)
            b = max(rr, key=lambda r: r["net"])
            al = next(r for r in rr if r["subset"] == "A")
            print(f"| {pa:g} | {b['subset']} | {eur(b['net'])} | {eur(al['net'])} |")
        # break-even fee for A in best set
        q = dict(p)
        sav = COSTS["A"]
        COSTS["A"] = (0, 0, 0)
        rr0, _ = run_all(q, cost_idx)
        COSTS["A"] = sav
        a0 = next(r for r in rr0 if r["subset"] == "A")
        print(f"\nBreak-even fee for A alone (net = 0): EUR {eur(a0['net'])} (gross expected gain at zero fee).")

        print("\n## Value-based price of our product (proposal, parameterised)\n")
        share = 0.05
        gain = best["net"] + best["cost"]
        print(f"- Avoided loss in the best subset (expected, before action costs) = EUR {eur(gain)}; net of action costs EUR {eur(best['net'])}.")
        print(f"- Proposal: {share:.0%} of verified net avoided loss per launch = EUR {eur(share * best['net'])}; customer keeps {1 - share:.0%}. Flagged as a proposal, not a quote.")
        runs, usd = 1000, (0.01, 0.04)
        print(f"- Agent cost for {runs} runs per launch at USD {usd[0]}-{usd[1]} per run = USD {runs*usd[0]:.0f}-{runs*usd[1]:.0f}; "
              f"fee / agent cost = {share * best['net'] / (runs * usd[1]):,.0f}x to {share * best['net'] / (runs * usd[0]):,.0f}x (USD~EUR 1:1 for scale).")


if __name__ == "__main__":
    main()
