import { useEffect, useRef, useState } from "react";
import type { DashboardData } from "../api";
import { drawLaunchCargo } from "./cargo";
import { Icon } from "./UI";

export const displayDate = (value: string, withTime = true) => {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value || "Time unconfirmed";
  return new Intl.DateTimeFormat("en-GB", {timeZone:"Europe/Berlin", weekday:"short", day:"numeric", month:"short",
    ...(withTime ? {hour:"2-digit", minute:"2-digit", timeZoneName:"short"} as const : {year:"numeric"} as const)}).format(date);
};
const count = (n: number) => n.toLocaleString("en-US");
const money = new Intl.NumberFormat("en-IE", {style:"currency", currency:"EUR", notation:"compact", maximumFractionDigits:2});
const edition = (id: string) => id === "CE" ? "Collector’s Edition" : id === "STD" ? "Standard Edition" : id;

function Clock({deadline}: {deadline: string}) {
  const [now, setNow] = useState(Date.now);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const observer = new ResizeObserver(() => { if (canvas.current) drawLaunchCargo(canvas.current); });
    observer.observe(canvas.current!);
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { observer.disconnect(); window.clearInterval(timer); };
  }, []);
  const seconds = Math.max(0, Math.ceil((Date.parse(deadline) - now)/1000));
  const units = [Math.floor(seconds/3600), Math.floor(seconds/60)%60, seconds%60];
  return <article className="stat countdown"><canvas ref={canvas} aria-hidden="true"/>
    <h2 className="stat-label"><span className="chip-icon"><Icon name="timer"/></span>Time to launch</h2>
    <div className="clock-readout" role="timer">{units.flatMap((value,i) => [
      i ? <em key={'sep'+i}>:</em> : null,
      <div key={i}><b>{Number.isFinite(value) ? String(value).padStart(2,"0") : "—"}</b><small>{["HOURS","MIN","SEC"][i]}</small></div>])}</div>
    <div className="cutoff">{displayDate(deadline)}</div></article>;
}

export function Forecast({data}: {data: DashboardData}) {
  const rows = [...data.readiness].sort((a,b) => Number(b.edition==="CE")-Number(a.edition==="CE"));
  return <section className="stats" aria-label="Launch forecast"><Clock deadline={data.launch.deadline}/>
    {rows.map(r => {
      const expected = r.p50 ?? r.packed;
      const gap = Math.max(0, r.target - expected);
      const percent = r.target ? Math.min(100, 100*expected/r.target) : 100;
      const unit = r.missCostEur ?? r.stdCostEur;
      return <article key={r.edition} className={'stat edition '+(gap?'short':'complete')}>
        <h2 className="stat-label"><span className="chip-icon"><Icon name={r.edition==="CE"?"box":"layers"}/></span>{edition(r.edition)}</h2>
        <div className="metric"><strong>{count(gap)}</strong><span>{gap ? "boxes short" : "short · target met"}</span></div>
        <div className="progress-wrap"><div className="track"><span style={{width:percent+"%"}}/></div>
          <div className="progress-caption"><span>{count(expected)} / {count(r.target)}</span><b>{Number(percent.toFixed(1))}%</b></div></div>
        <div className="loss"><span>{r.missCostEur==null?"At standard cost":r.missCostConfirmed===false?"Potential loss · estimate":r.edition==="CE"?"Refund exposure":"Potential loss"}</span>
          <b title={unit==null?undefined:"€"+count(unit*gap)}>{unit==null?"Unpriced":money.format(unit*gap)}</b></div>
      </article>;
    })}</section>;
}
