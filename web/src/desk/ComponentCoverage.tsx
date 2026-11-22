import { useState } from "react";
import type { Risk } from "../api";
import { Heading } from "./UI";

const count = new Intl.NumberFormat("en-GB");
const measured = (r: Risk): r is Risk & Required<Pick<Risk, "required" | "onHand" | "inbound" | "gap">> =>
  [r.required,r.onHand,r.inbound,r.gap].every(n => typeof n === "number" && Number.isFinite(n) && n >= 0) && (r.required ?? 0) > 0;

export function ComponentCoverage({ risks }: { risks: Risk[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const rows = risks.filter(measured).sort((a,b) => b.gap / b.required - a.gap / a.required || b.gap - a.gap);
  return <section className="card coverage"><Heading icon="layers">Component coverage</Heading>
    <p className="chart-caption">Supply for remaining launch demand, ranked by the share still missing.</p>
    {rows.length ? <><div className="coverage-legend"><span>Usable stock</span><span>Due by launch</span><span>Short</span></div>
      {rows.map(r => {
        const id = r.id ?? r.component;
        const stock = Math.min(r.onHand, r.required);
        const inbound = Math.min(r.inbound, r.required - stock);
        return <div className="coverage-row" key={id}>
          <button onClick={()=>setExpanded(expanded === id ? null : id)} aria-expanded={expanded === id}>
            <span className="coverage-label">{r.component}</span>
            <strong className={r.gap ? "gap-count" : "covered-count"}>{r.gap ? count.format(r.gap)+" short" : "Covered"}</strong>
            <span className="coverage-track" aria-hidden="true">
              <i style={{width:100*stock/r.required+"%"}}/><i style={{width:100*inbound/r.required+"%"}}/>
              <i style={{width:100*r.gap/r.required+"%"}}/>
            </span>
          </button>
          {expanded === id && <p className="coverage-detail">{count.format(r.onHand)} usable · {count.format(r.inbound)} expected inbound · {count.format(r.required)} required</p>}
        </div>;
      })}</> : <p className="empty">{risks.length ? "Component quantities are unavailable in this snapshot." : "No component risks reported."}</p>}
  </section>;
}
