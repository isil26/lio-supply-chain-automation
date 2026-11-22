import { useState } from "react";

export type PricePolicy = {
  limit: number; actor: string | null; reference: number | null; source: string; maximum: number; step: number;
};
export type SupplierPrice = { id: string; supplier: string; price_eur: number | null; catalog_eur?: number | null };
const euros = new Intl.NumberFormat("en-IE", {style: "currency", currency: "EUR", maximumFractionDigits: 4});
export const unitEuros = (value: number) => euros.format(value);

export function PriceCeiling({ policy, product, save }: {
  policy: PricePolicy; product: string; save: (value: number) => Promise<void>;
}) {
  const [value, setValue] = useState(policy.limit);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const changed = value !== policy.limit;

  async function submit() {
    setBusy(true);
    setError("");
    try { await save(value); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save this limit."); }
    finally { setBusy(false); }
  }
  return <section className="price-ceiling" aria-label={product + " automatic approval"}>
    <label><span>Automatic approval ceiling</span><b>{value ? unitEuros(value) + " / unit" : "Off"}</b>
      <input type="range" min={0} max={policy.maximum || 1} step={policy.step} value={value}
        disabled={busy || (!policy.reference && !policy.limit)} aria-label={product + " automatic approval ceiling"}
        aria-valuetext={value ? unitEuros(value) + " per unit" : "Off"}
        onChange={e => { setValue(Number(e.target.value)); setError(""); }}/>
    </label>
    <div className="price-axis"><span>Off</span><span>{policy.maximum ? unitEuros(policy.maximum) + " / unit" : "Awaiting supplier pricing"}</span></div>
    <p>{policy.reference ? policy.source + " · " + unitEuros(policy.reference) + " median per unit. " : ""}
      Eligible recommended offers within the ceiling are approved automatically. You review the supplier email before sending.</p>
    {changed && <button className="ghost-button" disabled={busy} onClick={submit}>{busy ? "Saving…" : value ? "Save limit" : "Turn off"}</button>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

export function PriceChart({ rows, limit, product }: { rows: SupplierPrice[]; limit: number; product: string }) {
  const top = Math.max(limit, ...rows.map(r => Math.max(r.price_eur ?? 0, r.catalog_eur ?? 0)));
  return <figure className="price-chart" aria-label={product + " unit price comparison"}>
    <figcaption><strong>Unit price comparison</strong><span>{product} · EUR per unit</span></figcaption>
    {top > 0 ? <>
      <div className="price-key"><span>Supplier quote</span><span>Catalogue</span>{limit > 0 && <span>Ceiling {unitEuros(limit)}</span>}</div>
      {rows.map(row => <div className="price-series" key={row.id}>
        <b>{row.supplier}</b><div className="price-plot">
          {limit > 0 && <i className="limit-marker" style={{left: Math.min(99.8, limit / top * 100) + "%"}}/>}
          {[row.price_eur, row.catalog_eur].map((price, index) => <div key={index} className={"price-track series-" + index}>
            {price != null && price > 0 && <i style={{width: (price / top * 100) + "%"}}/>}
          </div>)}
        </div><small>Quote {row.price_eur ? unitEuros(row.price_eur) : "unconfirmed"} · Catalogue {row.catalog_eur ? unitEuros(row.catalog_eur) : "unavailable"}</small>
      </div>)}
    </> : <p className="empty">The suppliers have not provided comparable unit prices.</p>}
  </figure>;
}
