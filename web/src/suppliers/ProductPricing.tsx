import { useState } from "react";

export type PricePolicy = {
  limit: number; actor: string | null; reference: number | null; source: string; maximum: number; step: number;
};
const euros = new Intl.NumberFormat("en-IE", {style: "currency", currency: "EUR", maximumFractionDigits: 4});
export const unitEuros = (value: number) => euros.format(value);

export function PriceCeiling({ policy, product, save, readOnly = false }: {
  policy: PricePolicy; product: string; save: (value: number) => Promise<void>; readOnly?: boolean;
}) {
  const [edit, setEdit] = useState<{value:number; previous:number} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const value = edit?.value ?? policy.limit;
  const changed = value !== policy.limit;
  const stale = edit !== null && edit.previous !== policy.limit;

  async function submit() {
    setBusy(true);
    setError("");
    try { await save(value); setEdit(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save this limit."); }
    finally { setBusy(false); }
  }
  return <section className="demo-ceiling" aria-label={product + " automatic approval"}>
    <label><span>Automatic approval ceiling</span><b>{value ? unitEuros(value) + " / unit" : "Off"}</b>
      <input type="range" min={0} max={policy.maximum || 1} step={policy.step} value={value}
        disabled={readOnly || busy || (!policy.reference && !policy.limit)} aria-label={product + " automatic approval ceiling"}
        aria-valuetext={value ? unitEuros(value) + " per unit" : "Off"}
        onChange={e => { setEdit({value:Number(e.target.value), previous:policy.limit}); setError(""); }}/>
    </label>
    <small>{policy.maximum ? "Off – "+unitEuros(policy.maximum)+" / unit · "+policy.source : "Awaiting supplier pricing"}</small>
    <p>Eligible offers within your ceiling can be approved automatically. You review the supplier email before sending.</p>
    {stale && !busy && <p role="status">The saved ceiling changed to {policy.limit ? unitEuros(policy.limit) + " per unit" : "Off"}. Adjust the slider to review your change.</p>}
    {changed && <button className="outline-btn" disabled={readOnly || busy || stale} onClick={submit}>{busy ? "Saving…" : value ? "Save limit" : "Turn off"}</button>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
