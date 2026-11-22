import type { Readiness } from "../api";
import { Heading } from "./UI";
import { editionName } from "./Forecast";

const number = new Intl.NumberFormat("en-GB");
const euros = new Intl.NumberFormat("en-IE", {style: "currency", currency: "EUR", maximumFractionDigits: 0});
const compact = new Intl.NumberFormat("en-GB", {notation: "compact", maximumFractionDigits: 2});
const valid = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n >= 0;

export function LaunchExposure({readiness}: {readiness: Readiness[]}) {
  const editions = [...readiness].sort((a, b) => Number(b.edition === "CE") - Number(a.edition === "CE"));
  const hasRates = editions.some(r => valid(r.missCostEur) && valid(r.p50));
  const labels = hasRates ? ["If packing stopped now", "At launch forecast"] : ["Packed to date", "Launch target"];
  const format = hasRates ? euros : number;
  const rows = editions.map(r => {
    const loss = (boxes: number) => valid(boxes) && valid(r.target) && valid(r.missCostEur)
      ? Math.max(0, r.target - boxes) * r.missCostEur : null;
    return {edition: r.edition, values: hasRates ? [loss(r.packed), loss(r.p50)] : [r.packed, r.target],
      basis: hasRates && valid(r.missCostEur) ? euros.format(r.missCostEur) + " per missing box · " + (r.missCostConfirmed ? "confirmed" : "assumed") : null};
  });
  const peak = Math.max(0, ...rows.flatMap(r => r.values.filter(valid)));
  const magnitude = peak ? 10 ** Math.floor(Math.log10(peak)) : 1;
  const maximum = Math.ceil(peak / magnitude) * magnitude;
  const axis = (n: number) => (hasRates ? "€" : "") + compact.format(n);
  const comparable = hasRates && rows.every(r => r.values.every(valid));
  const reduction = comparable ? rows.reduce((total, r) => total + r.values[0]! - r.values[1]!, 0) : 0;
  return <section className="card exposure" aria-label={hasRates ? "Launch loss exposure" : "Packing progress"}>
    <Heading icon="chart">{hasRates ? "Launch loss exposure" : "Packing progress"}</Heading>
    <div className="chart-legend exposure-legend">{labels.map((label, i) => <span className={'series-' + i} key={label}>{label}</span>)}</div>
    {rows.length ? <div className="exposure-chart">
      {rows.map(row => <div className="exposure-group" key={row.edition}>
        <div className="exposure-label"><strong>{editionName(row.edition)}</strong>{row.basis && <small>{row.basis}</small>}</div>
        {row.values.map((value, i) => <div className={'exposure-row series-' + i} key={i} aria-label={labels[i]}>
          <div className="exposure-track" aria-hidden="true">{valid(value) && value > 0 && <i style={{width: 100 * value / maximum + "%"}}/>}</div>
          <span><span className="sr-only">{labels[i]} </span>{valid(value) ? format.format(value) : "Unavailable"}</span>
        </div>)}
      </div>)}
      {maximum > 0 && <div className="exposure-axis" aria-hidden="true"><span>{axis(0)}</span><span>{axis(maximum/2)}</span><span>{axis(maximum)}</span></div>}
    </div> : <p className="empty">No packing figures in this forecast.</p>}
    {comparable && reduction >= 0 && <div className="exposure-impact"><span>Estimated loss avoided by forecast pack-out</span><strong>{euros.format(reduction)}</strong></div>}
  </section>;
}
