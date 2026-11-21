import type { DashboardData } from "./api";

type Timeline = NonNullable<DashboardData["inboundTimeline"]>;
type Lot = Timeline["lots"][number];

const HOUR = 3600000;
const clock = new Intl.DateTimeFormat("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

// Triangular handling delay (min, mode, max) in hours, as used by the forecast.
function cdf(x: number, [a, c, b]: [number, number, number]) {
  if (x <= a) return 0;
  if (x >= b) return 1;
  return x <= c ? (x - a) ** 2 / ((b - a) * (c - a)) : 1 - (b - x) ** 2 / ((b - a) * (b - c));
}
function median([a, c, b]: [number, number, number]) {
  return (c - a) / (b - a) >= 0.5 ? a + Math.sqrt((b - a) * (c - a) / 2) : b - Math.sqrt((b - a) * (b - c) / 2);
}

// When does the critical air cargo get unloaded, compared with the truck cut-off?
export function ArrivalTimeline({ timeline }: { timeline: Timeline }) {
  const cutoff = new Date(timeline.deadline).getTime();
  const inWindow = timeline.lots.filter((lot) => !lot.held && lot.lagHours && new Date(lot.earliest).getTime() < cutoff);
  const later = timeline.lots.filter((lot) => !inWindow.includes(lot));
  if (!inWindow.length && !later.length) return null;

  const starts = inWindow.map((lot) => new Date(lot.earliest).getTime());
  const ends = inWindow.map((lot) => new Date(lot.earliest).getTime() + lot.lagHours![2] * HOUR);
  const from = Math.min(cutoff - 10 * HOUR, ...starts.map((t) => t - 2 * HOUR));
  const to = Math.max(cutoff + 3 * HOUR, ...ends) + HOUR;
  const x = (t: number) => `${((t - from) / (to - from)) * 100}%`;
  // Hour marks every 4 h, aligned to the cut-off so they read 12:00, 16:00, 20:00 …
  const ticks = Array.from({ length: 40 }, (_, i) => cutoff + (i - 20) * 4 * HOUR).filter((t) => t > from && t < to);

  const describe = (lot: Lot) => {
    const land = new Date(lot.earliest).getTime();
    const lag = lot.lagHours!;
    const slack = (cutoff - land) / HOUR;
    return { land, lag, chance: cdf(slack, lag), typical: land + median(lag) * HOUR, fastest: land + lag[0] * HOUR, slack };
  };

  return <section className="card timeline-card" aria-label="Arrival timeline">
    <h3>The race to 20:00</h3>
    {!inWindow.length && <p className="tl-headline"><strong>No {(later[0]?.label ?? later[0]?.material ?? "parts").replace(/\s*[–-]\s*Grand Heist 6/i, "")} can reach Hamburg before the trucks leave.</strong> Everything still open arrives after launch.</p>}
    {inWindow.map((lot) => {
      const d = describe(lot);
      const late = d.typical > cutoff;
      return <div className="tl-lot" key={lot.id}>
        <p className="tl-headline">
          <strong>{fmt(lot.quantity)} × {(lot.label ?? lot.material).replace(/\s*[–-]\s*Grand Heist 6/i, "")}</strong> land {clock.format(d.land)} by {lot.mode}.{" "}
          {late ? <>At normal unloading speed they are ready around <strong>{clock.format(d.typical)}</strong>, after the trucks leave.</> : <>They should be unloaded by {clock.format(d.typical)}.</>}
        </p>
        <div className="tl-track">
          {ticks.map((t) => <span key={t} className="tl-tick" style={{ left: x(t) }}><i>{clock.format(t).slice(-5)}</i></span>)}
          <span className="tl-range" style={{ left: x(d.fastest), width: `calc(${x(d.land + d.lag[2] * HOUR)} - ${x(d.fastest)})` }} title="Possible unloading times"/>
          <span className="tl-ok" style={{ left: x(d.fastest), width: `calc(${x(Math.min(cutoff, d.land + d.lag[2] * HOUR))} - ${x(d.fastest)})` }}/>
          <span className="tl-land" style={{ left: x(d.land) }} title="Plane lands"><b>✈</b></span>
          <span className="tl-typical" style={{ left: x(d.typical) }} title="Typical unloading finished"/>
          <span className="tl-cutoff" style={{ left: x(cutoff) }}><em>{clock.format(cutoff).slice(-5)} trucks leave</em></span>
        </div>
        <div className="tl-legend">
          <span><i className="k ok"/>unloaded in time</span>
          <span><i className="k late"/>too late</span>
          <span className="tl-chance"><strong>{Math.round(d.chance * 100)}%</strong> chance at normal speed · a booked dock slot makes it</span>
        </div>
      </div>;
    })}
    {later.map((lot) => <p className="tl-later" key={lot.id}>
      + {fmt(lot.quantity)} more {lot.held ? "held at the supplier" : "on the way"} · earliest {clock.format(new Date(lot.earliest))}{new Date(lot.earliest).getTime() > cutoff ? ", after launch" : ""}
    </p>)}
  </section>;
}
