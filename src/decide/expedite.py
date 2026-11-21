"""Compare launch recovery options by incremental spend and expected loss."""

from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from math import isfinite
import re

from src.ingest.store import ROOT
from src.truth import MODEL_RUNS
from src.truth.sensitivity import SEED, counterfactual


LOSSES = (2, 5, 10, 35)
PROBABILITY_GAINS = (0.2, 0.5, 0.8)


def _nonnegative(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return value


def _break_even(cost_delta, quantity, probability_delta):
    benefit = quantity * probability_delta
    if benefit == 0 or cost_delta * benefit < 0:
        return None
    return cost_delta / benefit


def _sensitivity(cost_delta, quantity):
    return {
        "source": "assumption",
        "probability_gains": PROBABILITY_GAINS,
        "break_even_loss_eur": [_break_even(cost_delta, quantity, gain) for gain in PROBABILITY_GAINS],
        "grid": [
            {
                "loss_per_copy_eur": loss,
                "net_benefit_eur": [loss * quantity * gain - cost_delta for gain in PROBABILITY_GAINS],
            }
            for loss in LOSSES
        ],
    }


def choose(options, loss_per_copy, q_missing, *, truth=None, edition=None,
           lag_profiles=None, trials=MODEL_RUNS, seed=SEED):
    """Score options on the same at-risk copies, with the wait option first.

    Each option supplies a label, cost_eur and p_on_time, or replay changes
    when truth is available. The replay uses joint readiness unless an edition
    ID selects that edition's readiness. Use None for an unknown probability
    in a threshold-only comparison. All probabilities must refer to the same
    readiness event. Simulated changes are conditional on being carried out.
    """
    quantity = _nonnegative(q_missing, "q_missing")
    if loss_per_copy is not None:
        _nonnegative(loss_per_copy, "loss_per_copy")

    scored = []
    for index, option in enumerate(options):
        cost = _nonnegative(option["cost_eur"], "cost_eur")
        changes = option.get("changes", {} if index == 0 else None)
        probability, source = option.get("p_on_time"), "assumption"
        if truth is not None and changes is not None:
            replay = counterfactual(truth, changes, lag_profiles=lag_profiles, trials=trials, seed=seed)
            metric = replay["combined"] if edition is None else replay["editions"][edition]
            probability, source = metric["probability"], "counterfactual"
        expected = None
        if probability is None:
            source = "unknown"
        else:
            if _nonnegative(probability, "p_on_time") > 1:
                raise ValueError("p_on_time must be between 0 and 1")
            if loss_per_copy is not None:
                expected = cost + loss_per_copy * quantity * (1 - probability)
        scored.append(dict(option, cost_eur=cost, p_on_time=probability, source=source,
                           expected_cost_eur=expected))

    if not scored:
        raise ValueError("Provide a baseline option")
    thresholds = []
    for left, right in combinations(scored, 2):
        cost_delta = right["cost_eur"] - left["cost_eur"]
        p_left, p_right = left["p_on_time"], right["p_on_time"]
        p_delta = None if p_left is None or p_right is None else p_right - p_left
        thresholds.append({
            "from": left["label"],
            "to": right["label"],
            "cost_delta_eur": cost_delta,
            "probability_gain": p_delta,
            "break_even_loss_eur": None if p_delta is None else _break_even(cost_delta, quantity, p_delta),
        })
    baseline = scored[0]
    grids = [
        dict(_sensitivity(option["cost_eur"] - baseline["cost_eur"], quantity), option=option["label"])
        for option in scored[1:]
    ]
    if loss_per_copy is None:
        status, recommendation = "needs Dr. Vogt", None
    elif any(option["expected_cost_eur"] is None for option in scored):
        status, recommendation = "needs probabilities", None
    else:
        status = "scored"
        recommendation = min(scored, key=lambda option: (option["expected_cost_eur"], option["cost_eur"]))
    return {
        "status": status,
        "q_missing": quantity,
        "loss_per_copy_eur": loss_per_copy,
        "options": scored,
        "recommendation": recommendation,
        "thresholds": thresholds,
        "sensitivity": grids,
    }


def _art_book_example():
    numbers = ROOT / "docs" / "NUMBERS.md"
    for row, line in enumerate(numbers.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("- Art book hold:"):
            match = re.search(r"request ([\d,]+) finished units.*Estimated EUR ([\d,]+)", line)
            if match:
                quantity, cost = (int(value.replace(",", "")) for value in match.groups())
                return quantity, cost, {"file": "docs/NUMBERS.md", "row": row}
            break
    raise ValueError("Art-book quantity and materials estimate are missing from docs/NUMBERS.md")


def _money(number):
    rounded = Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}"


def main():
    quantity, cost, evidence = _art_book_example()
    report = choose([
        {"label": "Wait", "cost_eur": 0},
        {"label": "Express art books", "cost_eur": cost, "evidence": [evidence]},
    ], None, quantity)
    matrix = report["sensitivity"][0]
    columns = " | ".join(f"{gain:g}" for gain in matrix["probability_gains"])
    print("# Art-book expedite decision\n")
    print(f"Status **{report['status']}**. Express materials estimate **EUR {cost:,}** for **{quantity:,}** "
          f"units, with freight and dock slot still to price. [{evidence['file']}]({evidence['file']}#L{evidence['row']})\n")
    print("Each column assumes a gain in on-time probability. The net benefits are conditional on that "
          "gain applying to the at-risk copies, including availability of the other required parts.\n")
    print(f"| Gain in on-time probability | {columns} |")
    print("|---|---:|---:|---:|")
    values = " | ".join(_money(value) for value in matrix["break_even_loss_eur"])
    print(f"| Break-even loss (EUR per copy) | {values} |")
    for row in matrix["grid"]:
        values = " | ".join(f"{value:+,.0f}" for value in row["net_benefit_eur"])
        print(f"| Net benefit at EUR {row['loss_per_copy_eur']}/copy | {values} |")


if __name__ == "__main__":
    main()
