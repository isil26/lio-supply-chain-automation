import { useEffect, useState } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import "./offers.css";

// T90 mail-agent: every supplier offer in one table, best offer per part on top,
// Approve / Decline per offer. Approve names the PP-07 signer and asks the supplier to
// reserve; Decline sends a polite no-thanks. Both emails go out through the mail agent.

type Deal = {
  revision?: string; required_by?: string; thread_id?: string; order_quantity?: number | null; expires_at?: string | null;
  offer_state?: "quoted" | "incomplete" | "late" | "unavailable" | "expired" | "superseded" | "approval_required";
  offer_kind?: "goods" | "freight"; carrier?: string | null; freight_charge?: number | null;
  review_reason?: string;
  history?: { revision: string; action: string; by: string; at: string; terms: { order_quantity?: number; total_eur?: number; signer?: string } }[];
  id: string; supplier_id?: string; eta_text?: string | null; supplier: string; material: string; needed: number; quantity: number | null;
  unit_price: number | null; currency: string | null; price_eur: number | null; total_eur: number | null;
  eta: string | null; p_on_time: number | null; score: number | null; best: number; eligible: number;
  proof: string | null; incoterm: string | null; payment_terms: string | null; moq: number | null;
  list_price: number | null; conditions: string | null; excerpt: string | null; signer: string;
  status: "pending" | "approved" | "declined" | "changed" | "superseded"; decided_by: string | null; decided_at: string | null;
};
type Data = { deals: Deal[]; best: Deal[]; notes?: Record<string, string>; as_of?: string };

// Suppliers are shown by name and country of origin, e.g. "Hwaseong Memory (South Korea)".
const COUNTRY: Record<string, string> = {
  "SUP-0010": "South Korea", "SUP-0011": "USA", "SUP-0018": "India",
  "SUP-0019": "China", "SUP-0028": "Poland", "SUP-0029": "China",
};
const PRODUCT: Record<string, string> = {
  "CMP-GAM-001": "Game cards", "CMP-GAM-010": "Statues", "CMP-GAM-008": "Art books",
  "CMP-GAM-004": "Cover sleeves", "CMP-GAM-003": "Card cases", "CMP-GAM-007": "Collector's boxes",
};
function country(d: Deal) {
  const origin = d.supplier_id ? COUNTRY[d.supplier_id] : undefined;
  return origin && origin !== d.supplier ? `${d.supplier} (${origin})` : d.supplier;
}
function product(material: string) { return PRODUCT[material] ?? material; }

const STATUS: Record<Deal["status"], string> = { pending: "Open", approved: "Approved", declined: "Declined", changed: "Changed, decide again", superseded: "Superseded by supplier update" };

function eur(value: number | null) { return value == null ? "–" : `€${Math.round(value).toLocaleString("en-US")}`; }
function when(iso: string | null) {
  if (!iso) return "no date";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
}
function arrives(d: Deal) { return d.eta_text ?? when(d.eta); }
function unit(d: Deal) { return d.unit_price == null ? "no price" : `${d.unit_price} ${d.currency ?? ""}`; }

function exampleData(): Data {
  const data = sample as unknown as Data;
  return { ...data, best: data.deals.filter((d) => d.best) };
}

export function Offers() {
  // Hosted recording and static builds have no live backend: show a labelled example,
  // and keep Approve / Decline in this browser only (nothing is sent).
  const example = hostedReplayBuild || isStaticMode();
  const [data, setData] = useState<Data | null>(example ? exampleData() : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>(null);

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
        return { ...old, deals, best: deals.filter((d) => d.best) };
      });
      setNote(`Example only: in the live app this ${action === "approve" ? "asks the supplier in " + country(deal) + " to reserve the units (the purchase order needs the " + deal.signer + ")" : "sends the supplier in " + country(deal) + " a polite no-thanks"}. Nothing was sent here.`);
      return;
    }
    setBusy(deal.id + action);
    try {
      const response = await fetch(`/api/deals/${deal.id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ by: "Control room", revision: deal.revision }) });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setNote(error.error ?? "The offer could not be updated. Review the latest terms.");
        await load();
        return;
      }
      setNote(action === "approve"
        ? `Reservation request recorded for ${deal.supplier}. ${deal.offer_kind === "freight" ? "Booking authorization" : "PO signer"} · ${deal.signer}.`
        : `Decline recorded for ${deal.supplier}.`);
      await load();
    } catch {
      setNote("That did not work. Refresh and try again.");
    } finally {
      setBusy(null);
    }
  }

  if (!data) return null;
  const materials = [...new Set(data.deals.map((d) => d.material))];
  const current = tab && materials.includes(tab) ? tab : materials[0];
  const rows = data.deals.filter((d) => d.material === current);
  const best = data.best.filter((d) => d.material === current);
  const tabNote = current ? data.notes?.[current] : undefined;

  return (
    <section className="card offers" aria-labelledby="offers-title">
      <h3 id="offers-title">Supplier offers</h3>
      <p className="card-sub">{example ? `Simulated supplier offers${data.as_of ? ` (${data.as_of})` : ""}. Decisions stay in this browser.` : "Review supplier quotes and request a nonbinding reservation. The authorized signer issues the purchase order."}</p>
      {note && <p className="offers-note" role="status">{note}</p>}
      {data.deals.length === 0 && <p className="empty">No offers yet. They appear here as suppliers reply.</p>}

      {materials.length > 0 && <div className="offers-tabs" role="tablist" aria-label="Products">
        {materials.map((m) => {
          const all = data.deals.filter((d) => d.material === m);
          return <button key={m} role="tab" aria-selected={m === current} className={m === current ? "is-on" : ""} onClick={() => setTab(m)}>
            {product(m)} <span className="muted">{all[0].needed.toLocaleString("en-US")} short · {all.length} supplier{all.length === 1 ? "" : "s"}</span>
          </button>;
        })}
      </div>}

      {tabNote && <p className="offers-tabnote">{tabNote}</p>}

      {best.length > 0 && <div className="offers-best">
        {best.map((d) => (
          <div className="offers-best-item" key={d.id}>
            <p className="offers-label">Best offer · {product(d.material)}</p>
            <p className="offers-best-line"><strong>{example ? country(d) : d.supplier}</strong> · {d.quantity?.toLocaleString("en-US") ?? "?"} units · {d.offer_kind === "freight" ? d.carrier : unit(d)} · arrives {arrives(d)}</p>
            <p className="muted">Total {eur(d.total_eur)} · {d.offer_kind === "freight" ? "Booking authorization" : "PO signer"} {d.signer} · {STATUS[d.status]}</p>
          </div>
        ))}
      </div>}

      {rows.length > 0 && <div className="offers-scroll">
        <table className="offers-table">
          <thead>
            <tr><th scope="col">Supplier</th><th scope="col">Units in time</th><th scope="col">Unit price</th><th scope="col">Total</th><th scope="col">Arrives</th><th scope="col">On time</th><th scope="col">Proof</th><th scope="col">Terms</th><th scope="col">Decision</th></tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id} className={d.best ? "is-best" : d.eligible ? "" : "is-backup"}>
                <th scope="row">{example ? country(d) : d.supplier}{d.best ? <span className="offers-tag">Best</span> : null}
                  {d.conditions && <p className="offers-cond">{d.conditions}</p>}
                  {!example && d.required_by && <p className="muted small-text">Required by {when(d.required_by)}</p>}
                  {d.excerpt && <details><summary>{example ? "What they said" : "Their words"}</summary><p>{d.excerpt}</p></details>}
                  {!example && d.thread_id && <a href={`?mail=1&thread=${encodeURIComponent(d.thread_id)}`}>Open supplier thread</a>}
                </th>
                <td className="num">{d.quantity?.toLocaleString("en-US") ?? "–"}<span className="muted"> / {d.needed.toLocaleString("en-US")}</span></td>
                <td className="num">{d.offer_kind === "freight" ? "Freight service" : unit(d)}{d.list_price != null && d.unit_price != null && d.unit_price > d.list_price && <span className="muted"> (contract {d.list_price})</span>}</td>
                <td className="num">{eur(d.total_eur)}</td>
                <td>{arrives(d)}</td>
                <td className="num">{d.p_on_time == null ? "–" : `${Math.round(d.p_on_time * 100)}%`}</td>
                <td>{d.proof ?? "–"}</td>
                <td>{[d.carrier, d.incoterm, d.payment_terms, d.moq ? `min ${d.moq.toLocaleString("en-US")}` : null].filter(Boolean).join(" · ") || "–"}</td>
                <td>
                  <p className="offers-status">{!example && d.status === "approved" ? "Reservation approved" : STATUS[d.status]}{d.decided_by && d.status !== "pending" && d.status !== "changed" ? ` (${d.decided_by})` : ""}</p>
                  {!example && (!!d.eligible || d.offer_state === "approval_required") && <p className="muted small-text">{d.order_quantity?.toLocaleString("en-US")} units · {eur(d.total_eur)} · {d.offer_kind === "freight" ? "Booking authorization" : "PO signer"} {d.signer}{d.expires_at ? ` · Expires ${when(d.expires_at)}` : ""}</p>}
                  {d.eligible && (d.status === "pending" || d.status === "changed") ? <div className="offers-actions">
                    <button className="primary-button" disabled={busy !== null} onClick={() => void decide(d, "approve")}>{busy === d.id + "approve" ? "…" : example ? "Approve" : "Request reservation"}</button>
                    <button className="ghost-button" disabled={busy !== null} onClick={() => void decide(d, "decline")}>{busy === d.id + "decline" ? "…" : "Decline"}</button>
                  </div> : null}
                  {!d.eligible && <p className="muted small-text">{d.review_reason ?? "No eligible offer for this delivery window."}</p>}
                  {!example && !!d.history?.length && <details><summary>Decision history ({d.history.length})</summary>
                    {d.history.map(h => <p key={h.revision}>{when(h.at)} · {h.by} · {h.action === "approved" ? "reservation approved" : "declined"} · {eur(h.terms.total_eur ?? null)}{h.revision !== d.revision ? " · prior terms" : ""}</p>)}
                  </details>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}
    </section>
  );
}
