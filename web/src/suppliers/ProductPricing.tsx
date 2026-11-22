import { Heading } from "../desk/UI";
import { useState } from "react";

export type PricePolicy = {
  limit: number; actor: string | null; reference: number | null; source: string; maximum: number; step: number;
};
export type SupplierPrice = { id: string; supplier: string; price_eur: number | null; catalog_eur?: number | null };
const euros = new Intl.NumberFormat("en-IE", {style: "currency", currency: "EUR", maximumFractionDigits: 4});
export const unitEuros = (value: number) => euros.format(value);

export function PriceCeiling({ policy, product, save, readOnly = false }: {
  policy: PricePolicy; product: string; save: (value: number) => Promise<void>; readOnly?: boolean;
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
  return <section className="demo-ceiling" aria-label={product + " automatic approval"}>
    <label><span>Automatic approval ceiling</span><b>{value ? unitEuros(value) + " / unit" : "Off"}</b>
      <input type="range" min={0} max={policy.maximum || 1} step={policy.step} value={value}
        disabled={readOnly || busy || (!policy.reference && !policy.limit)} aria-label={product + " automatic approval ceiling"}
        aria-valuetext={value ? unitEuros(value) + " per unit" : "Off"}
        onChange={e => { setValue(Number(e.target.value)); setError(""); }}/>
    </label>
    <small>{policy.maximum ? "Off – "+unitEuros(policy.maximum)+" / unit · Supplier price range" : "Awaiting supplier pricing"}</small>
    <p>Eligible offers within your ceiling can be approved automatically. You review the supplier email before sending.</p>
    {changed && <button className="outline-btn" disabled={busy} onClick={submit}>{busy ? "Saving…" : value ? "Save limit" : "Turn off"}</button>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

export function PriceChart({rows, product}: {rows: SupplierPrice[]; product: string}) {
  const top = Math.max(0, ...rows.map(r=>Math.max(r.price_eur??0, r.catalog_eur??0)));
  return <section className="card demo-chart"><Heading icon="layers">Unit price comparison</Heading><p>{product} · EUR per unit</p>
    {rows.map(r=><div key={r.id}><b>{r.supplier}</b>
      <span className="demo-track" aria-hidden="true"><i style={{width:(top ? (r.catalog_eur??0)*100/top : 0)+"%"}}/></span>
      <small>Catalogue {r.catalog_eur==null?"unavailable":unitEuros(r.catalog_eur)} · Quote {r.price_eur==null?"unconfirmed":unitEuros(r.price_eur)}</small></div>)}</section>;
}
