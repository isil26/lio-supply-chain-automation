import { useEffect, useState } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import "./offers.css";

// T90 mail-agent: every supplier offer in one table, best offer per part on top,
// Approve / Decline per offer. Approve names the PP-07 signer and asks the supplier to
// reserve; Decline sends a polite no-thanks. Both emails go out through the mail agent.

type Deal = {
  id: string; supplier: string; material: string; needed: number; quantity: number | null;
  unit_price: number | null; currency: string | null; price_eur: number | null; total_eur: number | null;
  eta: string | null; p_on_time: number | null; score: number | null; best: number; eligible: number;
  proof: string | null; incoterm: string | null; payment_terms: string | null; moq: number | null;
  list_price: number | null; conditions: string | null; excerpt: string | null; signer: string;
  status: "pending" | "approved" | "declined" | "changed"; decided_by: string | null; decided_at: string | null;
};
type Data = { deals: Deal[]; best: Deal[] };

const STATUS: Record<Deal["status"], string> = { pending: "Waiting for you", approved: "Approved", declined: "Declined", changed: "Changed, decide again" };

function eur(value: number | null) { return value == null ? "–" : `€${Math.round(value).toLocaleString("en-US")}`; }
function when(iso: string | null) {
  if (!iso) return "no date";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
}
function unit(d: Deal) { return d.unit_price == null ? "no price" : `${d.unit_price} ${d.currency ?? ""}`; }

function exampleData(): Data {
  const deals = (sample as { deals: Deal[] }).deals;
  return { deals, best: deals.filter((d) => d.best) };
}

export function Offers() {
  // Hosted recording and static builds have no live backend: show a labelled example,
  // and keep Approve / Decline in this browser only (nothing is sent).
  const example = hostedReplayBuild || isStaticMode();
  const [data, setData] = useState<Data | null>(example ? exampleData() : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function load() {
    try {
      const response = await fetch("/api/deals", { cache: "no-store" });
      if (response.ok) setData(await response.json());
    } catch { /* keep the last table */ }
  }

  useEffect(() => {
    if (example) return;
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [example]);

  async function decide(deal: Deal, action: "approve" | "decline") {
    if (example) {
      const status = action === "approve" ? "approved" : "declined";
      setData((old) => {
        if (!old) return old;
        const deals = old.deals.map((d) => d.id === deal.id ? { ...d, status, decided_by: "you" } as Deal : d);
        return { deals, best: deals.filter((d) => d.best) };
      });
      setNote(`Example only: in the live app this ${action === "approve" ? "asks " + deal.supplier + " to reserve the units (the purchase order needs the " + deal.signer + ")" : "sends " + deal.supplier + " a polite no-thanks"}. Nothing was sent here.`);
      return;
    }
    setBusy(deal.id + action);
    try {
      const response = await fetch(`/api/deals/${deal.id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ by: "Control room" }) });
      if (!response.ok) throw new Error(String(response.status));
      setNote(action === "approve"
        ? `${deal.supplier} approved. They are asked to reserve it; the purchase order needs the ${deal.signer}.`
        : `${deal.supplier} declined. A polite email is on its way.`);
      await load();
    } catch {
      setNote("That did not work. Refresh and try again.");
    } finally {
      setBusy(null);
    }
  }

  if (!data) return null;
  const rows = data.deals;

  return (
    <section className="card offers" aria-labelledby="offers-title">
      <h3 id="offers-title">Supplier offers</h3>
      <p className="card-sub">{example ? "Example with sample replies, not live prices. " : ""}Every offer the suppliers sent, with price and timing. You decide; the mail agent tells the supplier.</p>
      {note && <p className="offers-note" role="status">{note}</p>}
      {rows.length === 0 && <p className="empty">No offers yet. They appear here as suppliers reply.</p>}

      {data.best.length > 0 && <div className="offers-best">
        {data.best.map((d) => (
          <div className="offers-best-item" key={d.id}>
            <p className="offers-label">Best offer · {d.material}</p>
            <p className="offers-best-line"><strong>{d.supplier}</strong> · {d.quantity?.toLocaleString("en-US") ?? "?"} units · {unit(d)} · arrives {when(d.eta)}</p>
            <p className="muted">Total {eur(d.total_eur)} · PO signer: {d.signer} · {STATUS[d.status]}</p>
          </div>
        ))}
      </div>}

      {rows.length > 0 && <div className="offers-scroll">
        <table className="offers-table">
          <thead>
            <tr><th scope="col">Supplier</th><th scope="col">Part</th><th scope="col">Units</th><th scope="col">Unit price</th><th scope="col">Total</th><th scope="col">Arrives</th><th scope="col">On time</th><th scope="col">Proof</th><th scope="col">Terms</th><th scope="col">Decision</th></tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id} className={d.best ? "is-best" : d.eligible ? "" : "is-backup"}>
                <th scope="row">{d.supplier}{d.best ? <span className="offers-tag">Best</span> : null}
                  {d.excerpt && <details><summary>Their words</summary><p>{d.excerpt}</p>{d.conditions && <p className="muted">{d.conditions}</p>}</details>}
                </th>
                <td>{d.material}</td>
                <td className="num">{d.quantity?.toLocaleString("en-US") ?? "–"}<span className="muted"> / {d.needed.toLocaleString("en-US")}</span></td>
                <td className="num">{unit(d)}{d.list_price != null && d.unit_price != null && d.unit_price > d.list_price && <span className="muted"> (contract {d.list_price})</span>}</td>
                <td className="num">{eur(d.total_eur)}</td>
                <td>{when(d.eta)}</td>
                <td className="num">{d.p_on_time == null ? "–" : `${Math.round(d.p_on_time * 100)}%`}</td>
                <td>{d.proof ?? "–"}</td>
                <td>{[d.incoterm, d.payment_terms, d.moq ? `min ${d.moq.toLocaleString("en-US")}` : null].filter(Boolean).join(" · ") || "–"}</td>
                <td>
                  <p className="offers-status">{STATUS[d.status]}{d.decided_by && d.status !== "pending" && d.status !== "changed" ? ` by ${d.decided_by}` : ""}</p>
                  {(d.status === "pending" || d.status === "changed") && <div className="offers-actions">
                    <button className="primary-button" disabled={busy !== null} onClick={() => void decide(d, "approve")}>{busy === d.id + "approve" ? "…" : "Approve"}</button>
                    <button className="ghost-button" disabled={busy !== null} onClick={() => void decide(d, "decline")}>{busy === d.id + "decline" ? "…" : "Decline"}</button>
                  </div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}
    </section>
  );
}
