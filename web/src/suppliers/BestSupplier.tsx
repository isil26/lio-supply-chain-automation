import { useEffect, useState } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./sample.json";
import "./bestSupplier.css";

// T77 mail-agent: best supplier per part, split plan, negotiation and reminder drafts.
// Live: GET /api/suppliers/best. Hosted/static builds show a labelled example.
// The button only creates drafts; a person still reviews and sends every email.

type Row = { supplier: string; score: number; eligible: boolean; reasons: string[]; factors: Record<string, number> };
type Negotiation = { supplier: string; asks: { lever: string; target?: number | string; from?: number; currency?: string; units?: number }[]; draft_id: string; body: string; saved: boolean };
type Material = {
  material: string; need: number; why: string; pick: string | null;
  context: { mode: string; time_pressure: number; price_spread_pct: number; on_time_floor: number; hours_left: number };
  weights: Record<string, number>;
  plan: { allocation: { supplier: string; units: number; expected_on_time_units: number }[]; uncovered: number; split: boolean };
  ranking: Row[]; negotiations: Negotiation[];
};
type Reminder = { supplier: string; waited_hours: number; wait_limit_hours: number; action: "remind" | "call"; draft_id?: string };
type Report = { materials: Material[]; reminders: Reminder[]; fx_eur_assumed?: Record<string, number> };

const MODE: Record<string, string> = {
  "time-critical": "Time is short, so on-time delivery counts most",
  "cost-critical": "Prices differ a lot, so price counts most",
  balanced: "Balanced: delivery, price and risk count evenly",
};
const LEVER: Record<string, string> = {
  price: "lower price", earlier: "earlier delivery", partial: "early part shipment", express: "free express", moq: "smaller minimum order",
};
const FACTOR: Record<string, string> = {
  on_time: "On time", cover: "Quantity", price: "Price", buffer: "Buffer", evidence: "Proof", speed: "Reply speed",
  track: "Track record", logistics: "Shipping & customs", approval: "Approval", moq: "Min. order", terms: "Payment terms", diversity: "Spread risk",
};

function pct(value: number) { return `${Math.round(value * 100)}%`; }

export function BestSupplier() {
  const example = hostedReplayBuild || isStaticMode();
  const [report, setReport] = useState<Report | null>(example ? (sample as Report) : null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function load() {
    try {
      const response = await fetch("/api/suppliers/best", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      setReport(await response.json());
      setError(null);
    } catch {
      setError("Supplier comparison is not available right now.");
    }
  }

  useEffect(() => {
    if (example) return;
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [example]);

  async function prepare() {
    setBusy(true);
    try {
      const response = await fetch("/api/suppliers/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "all" }) });
      if (!response.ok) throw new Error(String(response.status));
      const data: Report = await response.json();
      setReport(data);
      const made = data.materials.reduce((n, m) => n + m.negotiations.length, 0) + data.reminders.filter((r) => r.action === "remind").length;
      setNote(made ? `${made} email draft${made === 1 ? "" : "s"} ready. Review and send them under Agents.` : "Nothing new to draft.");
    } catch {
      setNote("Could not prepare drafts. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const materials = report?.materials ?? [];
  const reminders = report?.reminders ?? [];
  const drafts = materials.reduce((n, m) => n + m.negotiations.length, 0) + reminders.filter((r) => r.action === "remind").length;

  return (
    <section className="card best-supplier" aria-labelledby="best-supplier-title">
      <div className="bsup-head">
        <div>
          <h3 id="best-supplier-title">Best supplier</h3>
          <p className="card-sub">{example ? "Example with sample replies." : "From the latest supplier replies."} Emails go out only after you send them.</p>
        </div>
        {!example && drafts > 0 && <button className="primary-button" onClick={() => void prepare()} disabled={busy}>{busy ? "Preparing…" : `Prepare ${drafts} email${drafts === 1 ? "" : "s"} for review`}</button>}
      </div>
      {note && <p className="bsup-note" role="status">{note}</p>}
      {error && !report && <p className="empty">{error}</p>}
      {report && materials.length === 0 && <p className="empty">No supplier has replied yet. The ranking appears with the first answer.</p>}

      {materials.map((m) => (
        <article className="bsup-material" key={m.material}>
          <header>
            <p className="bsup-part">{m.material} · need {m.need.toLocaleString("en-US")}</p>
            <p className="bsup-pick">{m.pick ? <>Pick <strong>{m.pick}</strong></> : "No supplier can make it on time yet"}</p>
            <p className="muted bsup-mode">{MODE[m.context.mode] ?? m.why} · time pressure {pct(m.context.time_pressure)} · prices {m.context.price_spread_pct}% apart</p>
          </header>

          {m.plan.split && <p className="bsup-split">Split the order: {m.plan.allocation.map((a) => `${a.supplier} ${a.units.toLocaleString("en-US")}`).join(" + ")}</p>}
          {m.plan.uncovered > 0 && <p className="bsup-warn">{m.plan.uncovered.toLocaleString("en-US")} units still not covered on time.</p>}

          <ol className="bsup-rank">
            {m.ranking.map((row) => (
              <li key={row.supplier} className={row.eligible ? "" : "bsup-backup"}>
                <div className="bsup-row">
                  <span className="bsup-name">{row.supplier}{!row.eligible && <span className="muted"> · backup</span>}</span>
                  <span className="bsup-score" aria-label={`score ${row.score} of 100`}>{Math.round(row.score)}</span>
                </div>
                <div className="bsup-bar" aria-hidden="true"><span style={{ width: `${Math.max(2, Math.min(100, row.score))}%` }}/></div>
                <details>
                  <summary>Why</summary>
                  <ul className="bsup-reasons">{row.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                  <dl className="bsup-factors">
                    {Object.entries(row.factors).sort((a, b) => (m.weights[b[0]] ?? 0) - (m.weights[a[0]] ?? 0)).map(([k, v]) => (
                      <div key={k}><dt>{FACTOR[k] ?? k} <span className="muted">({pct(m.weights[k] ?? 0)} weight)</span></dt><dd>{pct(v)}</dd></div>
                    ))}
                  </dl>
                </details>
              </li>
            ))}
          </ol>

          {m.negotiations.map((n) => (
            <details className="bsup-negotiate" key={n.draft_id}>
              <summary>Ask {n.supplier} for: {n.asks.map((a) => LEVER[a.lever] ?? a.lever).join(", ")}</summary>
              <pre>{n.body}</pre>
            </details>
          ))}
        </article>
      ))}

      {reminders.length > 0 && <div className="bsup-reminders">
        <p className="bsup-part">Waiting for an answer</p>
        <ul>{reminders.map((r) => <li key={r.supplier + r.action}>{r.supplier}: silent for {Math.round(r.waited_hours)} h. {r.action === "call" ? "Two reminders sent, please call them." : "A reminder is ready."}</li>)}</ul>
      </div>}
    </section>
  );
}
