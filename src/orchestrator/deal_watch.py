"""Persistent sourcing reviews driven by the live procurement worker."""
from datetime import timedelta

from src import chaser
from src.chaser import deals
from src.chaser.deadlines import current_plan, timestamp
from src.ingest.store import get_state, save_state

INTERVAL = timedelta(minutes=30)
KEY = "dealWatch"


def cutoff(truth):
    if not truth:
        return None
    end = timestamp(truth.get("deadline"))
    shifts = truth.get("shifts") or []
    last_shift = timestamp(shifts[-1][1]) if shifts else None
    return min(end, last_shift) if end and last_shift else end


def due(previous, truth, reply_id, clock):
    """Wake on the next deadline, on a new reply, or when the active case changes."""
    if not previous or not truth:
        return True
    if any(previous.get(key) != truth.get(key) for key in ("name", "site", "deadline")):
        return True
    end = cutoff(truth)
    if not end or end <= clock:
        return previous.get("status") != "closed"
    next_review = timestamp(previous.get("nextReviewAt"))
    return (not next_review or clock >= next_review or reply_id != previous.get("reviewedThrough"))


def publish(con, truth, reply_id, clock):
    """Publish changes after the forecast, source selection and recovery planners ran."""
    end = cutoff(truth)
    active = bool(end and end > clock)
    parts = {code: part for code, part in truth["parts"].items() if active and part.get("shortfall", 0) > 0}
    review = {key: truth.get(key) for key in ("name", "site", "deadline")}
    review.update(status="active" if active else "closed", checkedAt=clock.isoformat(),
                  nextReviewAt=None, reviewedThrough=reply_id,
                  shortages={code: part["shortfall"] for code, part in parts.items()}, offers={})
    if active:
        deals.sync(con, truth["deadline"], now=clock)
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        previous = get_state(con, KEY, {}) or {}
        if active:
            next_review = min(end, clock + INTERVAL)
            _, fallbacks, _ = current_plan(con)
            quotes = con.execute("""SELECT d.id,d.revision,d.supplier_id,d.supplier,d.material,d.quantity,
                        d.unit_price,d.currency,d.eta,d.expires_at,d.offer_kind,d.freight_charge,d.source_message,d.signer
                FROM deals d JOIN messages m ON m.external_id=d.source_message AND m.chase_id=d.thread_id
                WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox' AND lower(m.sender)=lower(d.address)
                  AND offer_state='quoted' AND eligible=1 AND status IN ('pending','changed')
                  AND julianday(required_by)=julianday(?)""", (truth["deadline"],))
            for quote in quotes:
                part = parts.get(quote["material"])
                if not part or not any(s.get("supplier_id") == quote["supplier_id"]
                                       and (s.get("supplier") or {}).get("status") not in ("inactive", "blocked")
                                       for s in part.get("suppliers", [])):
                    continue
                eta = timestamp(quote["eta"])
                expiry = timestamp(quote["expires_at"])
                if not eta or eta > end or clock >= fallbacks.get(quote["material"], end) or (expiry and expiry <= clock):
                    continue
                if expiry:
                    next_review = min(next_review, expiry)
                review["offers"][quote["id"]] = dict(quote)
                old = previous.get("offers", {}).get(quote["id"], {})
                if old.get("revision") != quote["revision"]:
                    cost = (f"freight {quote['freight_charge']:g} {quote['currency']}" if quote["offer_kind"] == "freight"
                            else f"{quote['unit_price']:g} {quote['currency']} per unit")
                    chaser.activity(con, "Supplier Deal Watch",
                                    f"{quote['supplier']} quoted {quote['quantity']:,} units of {quote['material']}, "
                                    f"{cost}, arriving {quote['eta']}. Open shortage: {part['shortfall']:,}. "
                                    f"{quote['signer']} to review the offer.")
            review["nextReviewAt"] = next_review.isoformat()
        save_state(con, KEY, review)
    return active
