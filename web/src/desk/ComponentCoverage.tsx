import { useId, useState } from "react";
import type { Risk } from "../api";
import { Heading } from "./UI";

const count = new Intl.NumberFormat("en-GB");
const measured = (r: Risk): r is Risk & Required<Pick<Risk, "required" | "onHand" | "inbound" | "gap">> =>
  [r.required,r.onHand,r.inbound,r.gap].every(n => typeof n === "number" && Number.isFinite(n) && n >= 0) && (r.required ?? 0) > 0;

export function ComponentCoverage({ risks }: { risks: Risk[] }) {
  const chartId = useId();
  const [expanded, setExpanded] = useState<string | null>(null);
  const rows = risks.filter(measured).sort((a,b) => b.gap / b.required - a.gap / a.required || b.gap - a.gap);
  return <section className="card coverage"><Heading icon="layers">Component coverage</Heading>
    <p className="chart-caption">Available includes usable stock and arrivals expected by launch.</p>
    {rows.length ? <div className="coverage-rows">{rows.map(r => {
      const id = r.id ?? r.component;
      const available = r.onHand + r.inbound;
      const open = expanded === id;
      return <div className="coverage-row" key={id}>
        <button type="button" onClick={() => setExpanded(open ? null : id)} aria-expanded={open} aria-controls={chartId + "-" + encodeURIComponent(id)}>
          <span className="coverage-label">{r.component}</span>
          <span className={'coverage-numbers' + (r.gap ? ' has-gap' : '')}>
            <span>{count.format(available)} available</span><strong>{count.format(r.gap)} short</strong>
          </span>
          <span className="coverage-track" aria-hidden="true"><i style={{width: 100 * Math.min(available / r.required, 1) + "%"}}/></span>
        </button>
        <p id={chartId + "-" + encodeURIComponent(id)} className="coverage-detail" hidden={!open}>{count.format(r.required)} units required for remaining launch demand.</p>
      </div>;
    })}</div> : <p className="empty">{risks.length ? "Component quantities are unavailable in this snapshot." : "No component risks reported."}</p>}
  </section>;
}
