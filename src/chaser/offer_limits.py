"""Product-specific unit price ceilings for nonbinding supplier reservations."""
import math
from datetime import datetime
from statistics import median

from . import deals, recovery
from .negotiate import fx_rates


def schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS offer_limits (
        material TEXT PRIMARY KEY, limit_eur REAL NOT NULL, actor TEXT NOT NULL)""")


def market(con, rows):
    """Prefer quoted goods prices. Use supplier catalogue prices where a quote is missing."""
    schema(con)
    rates = fx_rates()
    catalog = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='supplier_components'").fetchone():
        for material, supplier, amount, currency in con.execute(
            "SELECT component_id,supplier_id,unit_price,currency FROM supplier_components WHERE unit_price>0"
        ):
            if currency in rates:
                catalog[material, supplier] = round(amount * rates[currency], 4)
    saved = {m: (price, actor) for m, price, actor in con.execute("SELECT * FROM offer_limits")}
    policies = {}
    for row in rows:
        material = row["material"]
        row["catalog_eur"] = catalog.get((material, row["supplier_id"]))
        policies.setdefault(material, {})
    for material in policies:
        prices = [r["price_eur"] for r in rows if r["material"] == material and r["price_eur"]
                  and r["offer_kind"] == "goods" and r["offer_state"] != "superseded"]
        source = "Supplier quotes" if prices else "Supplier catalogue"
        if not prices:
            prices = [v for (part, _), v in catalog.items() if part == material and v > 0]
        limit, actor = saved.get(material, (0, None))
        ref = median(prices) if prices else None
        top = max(prices) * 1.5 if prices else 0
        step = max(0.0001, 10 ** (math.floor(math.log10(top)) - 2)) if top else 0.01
        maximum = max(limit, round(math.ceil(round(top / step, 9)) * step, 4))
        policies[material] = dict(limit=limit, actor=actor, reference=ref, source=source,
                                  maximum=maximum, step=step)
    return policies


def set_limit(con, material, limit, previous, actor):
    if not isinstance(material, str) or not isinstance(actor, str) or not actor.strip():
        raise ValueError("A product and a signed-in reviewer are required.")
    if type(limit) not in (float, int) or not math.isfinite(limit) or limit < 0 or round(limit, 4) != limit:
        raise ValueError("Select a valid unit price.")
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        deals.schema(con)
        rows = deals.list_deals(con)["deals"]
        policy = market(con, rows).get(material)
        if not policy or previous != policy["limit"]:
            raise ValueError("The saved limit changed. Reload the offers before saving.")
        if limit and (not policy["reference"] or limit > policy["maximum"]):
            raise ValueError("Select a limit within the current supplier price range.")
        if limit != previous:
            con.execute("INSERT OR REPLACE INTO offer_limits VALUES(?,?,?)", (material, limit, actor))
            value = f"€{limit:g} per unit" if limit else "Off"
            con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                        (deals._now(), actor, f"{material} automatic reservation limit · {value}", "info"))


def apply(con, truth, watermark, *, demo):
    schema(con)
    if not con.execute("SELECT 1 FROM offer_limits WHERE limit_eur>0 LIMIT 1").fetchone():
        return
    if not truth.get("deadline"):
        return
    deals.sync(con, truth["deadline"])
    launch = datetime.fromisoformat(truth["deadline"])
    candidates = con.execute("""SELECT id,material FROM deals WHERE best=1 AND eligible=1
                               AND status='pending' AND offer_kind='goods'""").fetchall()
    for deal_id, material in candidates:
        with con:
            if not con.in_transaction:
                con.execute("BEGIN IMMEDIATE")
            row = deals._stored(con, deal_id)
            policy = con.execute("SELECT limit_eur,actor FROM offer_limits WHERE material=?", (material,)).fetchone()
            gap = (truth.get("parts", {}).get(material, {}).get("shortfall") or 0)
            if not (policy and row["best"] and row["eligible"] and row["status"] == "pending"
                    and row["offer_kind"] == "goods" and 0 < (row["price_eur"] or 0) <= policy[0]
                    and 0 < (row["order_quantity"] or 0) <= gap):
                continue
            if not row["required_by"] or datetime.fromisoformat(row["required_by"]) > launch:
                continue
            # A buyer must reconcile an earlier reservation before another supplier or revision is held.
            if con.execute("""SELECT 1 FROM deal_decision_history h JOIN deals d ON d.id=h.deal_id
                              WHERE d.material=? AND h.action='approved'
                                AND json_extract(h.terms, '$.required_by') = ? LIMIT 1""",
                           (material, row["required_by"])).fetchone():
                continue
            if not demo and (recovery.superseded_offer(con, deal_id) or recovery.pending_revision(con, watermark)):
                continue
            try:
                deals.decide(con, deal_id, "approve", policy[1], f"Automatic reservation · €{policy[0]:g}/unit limit",
                             revision=row["revision"], defer_send=True)
            except ValueError:
                # decide() also revalidates the source, revision, expiry and outbound draft.
                continue
