import { useEffect, useMemo, useRef, useState } from "react";
import { dashboardApi, hostedReplayBuild, isStaticMode, type DashboardData, type Source } from "../api";
import { MantiLogo } from "../SupplyMap";
import { activitySignals, findAgent, teams, type Agent, type Signal, type Team } from "./network";
import "./agentGraph.css";

const icons: Record<string, string> = {
  bridge: "M4 17h16M5 17V7m14 10V7M5 8q7 11 14 0M9 13v4m6-4v4",
  document: "M6 3h8l4 4v14H6z M14 3v5h4M9 12h6m-6 4h6",
  pulse: "M2 13h5l3-8 4 14 3-8 2 2h3",
  branch: "M6 5v12q0 2 2 2h9M6 12h4q5 0 5-5V5 M12 7l3-3 3 3m-3 9 3 3-3 3",
  shield: "M12 3l7 3v6q0 5-7 9-7-4-7-9V6z M8.5 11.5l2.5 2.5 4.5-5",
  recover: "M3 12a9 9 0 1 1 3 7M3 6v6h6 M12 7v5l3 2",
  loop: "M3 10l3-4h12l3 4m0-4v4h-5 M21 14l-3 4H6l-3-4m0 4v-4h5",
  signal: "M4 4l17 7-7 3-3 7z M11 13l5-4",
  mail: "M3 6h18v13H3z M3 7l9 7 9-7",
  plan: "M4 5h5v5H4z M15 14h5v5h-5z M7 10v7h8m0-12h5m-2.5-2.5v5",
  interpret: "M3 4h13v9H8l-4 3v-3H3z M10 16v2h6l4 3v-3h1V9h-2",
  brief: "M6 3h12v18H6z M9 8h6m-6 4h6m-6 4h4",
};

function Glyph({ icon }: { icon: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={icons[icon]}/></svg>;
}

const eventCount = (n: number) => n + (n === 1 ? " event" : " events");
const MAX_REPLAY = 12;
const PULSE_MS = 3400;

function useRecentSignals(signals: Signal[], connected: boolean) {
  const previous = useRef<Set<string> | null>(null);
  const [pulses, setPulses] = useState<Map<string, number>>(new Map());
  useEffect(() => {
    const known = previous.current;
    const ids = signals.map(signal => signal.id);
    // A projected event can briefly drop out of the feed between refreshes.
    const retained = [...new Set([...ids, ...(known ?? [])])];
    previous.current = new Set(retained.slice(0, Math.max(512, ids.length * 2)));
    if (!known || !connected) return;
    const fresh = signals.filter(signal => !known.has(signal.id));
    if (fresh.length) setPulses(current => {
      const next = new Map(current);
      fresh.forEach(signal => next.set(signal.agent.name, Date.now() + PULSE_MS));
      return next;
    });
  }, [signals, connected]);
  useEffect(() => {
    if (!pulses.size) return;
    const timer = window.setTimeout(() => {
      setPulses(current => new Map([...current].filter(([, until]) => until > Date.now())));
    }, Math.max(0, Math.min(...pulses.values()) - Date.now()) + 10);
    return () => window.clearTimeout(timer);
  }, [pulses]);
  return pulses;
}

function useRunHistory(data: DashboardData, scenario: boolean, enabled: boolean) {
  const [history, setHistory] = useState<{ id: string; signals: Signal[]; roles?: string[]; error?: boolean } | null>(null);
  const [last] = data.agents?.runs ?? [];
  const id = isStaticMode() ? "recorded-art-book" : last?.id;
  const steps = last?.step_count;
  useEffect(() => {
    if (!enabled || !id || scenario || hostedReplayBuild) return;
    let valid = true;
    dashboardApi.getAgentTrace(id).then(trace => {
      if (!valid) return;
      const signals = trace.steps.flatMap((step, i) => {
        const agent = findAgent(step.agent);
        if (!agent || step.tool === "recorded_run") return [];
        const label = (step.tool || "Model response").replace(/_/g, " ");
        return [{ id: id + ":" + i, agent, message: label + " · " + (step.reason || step.status),
          time: "Run · step " + (i + 1), at: 0, sources: step.citations }];
      }).reverse();
      const roles = trace.steps.filter(step => step.tool === "recorded_run").map(step => step.agent);
      setHistory({ id, signals, roles });
    }).catch(() => { if (valid) setHistory({ id, signals: [], error: true }); });
    return () => { valid = false; };
  }, [enabled, id, steps, last?.status, scenario]);
  return history?.id === id ? history : null;
}

function NetworkPlot({ agents, counts, selected, lit, onSelect }: {
  agents: Agent[]; counts: Map<string, number>; selected: string | null; lit: Set<string>; onSelect: (name: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < 525));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const hub = { x: 50, y: compact ? 10 : 50 };
  const points = agents.map((_, i) => {
    if (compact) return { x: i % 2 === 0 ? 25 : 75, y: 25 + Math.floor(i / 2) * 15 };
    const angle = -Math.PI / 2 + 2 * Math.PI * i / agents.length;
    return { x: 50 + 39 * Math.cos(angle), y: 49 + 36 * Math.sin(angle) };
  });
  return <div className={'net-plot' + (compact ? ' compact' : '')} ref={wrap}>
    <svg className="net-wires" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {!compact && <g className="net-orbits">
        <ellipse cx="50" cy="49" rx="39" ry="36"/><ellipse cx="50" cy="49" rx="30" ry="27"/><ellipse cx="50" cy="49" rx="18" ry="16.5"/>
      </g>}
      {agents.map((agent, i) => {
        const { x, y } = points[i];
        const litUp = lit.has(agent.name);
        const d = compact ? `M50 ${hub.y} V${y - 5} Q50 ${y} ${x > 50 ? 54 : 46} ${y} H${x}`
          : `M50 50 C${50 + (x - 50) * .45} 50 ${50 + (x - 50) * .5} ${y} ${x} ${y}`;
        return <g key={agent.name} data-tone={agent.tone} className={litUp ? "lit" : ""}>
          <path d={d} className="net-wire"/>
          {litUp && <path d={d} pathLength="1" className="net-traveler"/>}
        </g>;
      })}
    </svg>
    <div className="net-core" style={{left: hub.x + "%", top: hub.y + "%"}}><MantiLogo/></div>
    {agents.map((agent, i) => <button key={agent.name} type="button" data-tone={agent.tone}
      className={"net-node" + (lit.has(agent.name) ? " lit" : "") + (counts.has(agent.name) ? " has-data" : "")}
      style={{ left: points[i].x + "%", top: points[i].y + "%" }}
      onClick={() => onSelect(agent.name)} aria-pressed={selected === agent.name}
      aria-label={agent.name + ", " + eventCount(counts.get(agent.name) ?? 0)}>
      <span className="net-disc"><Glyph icon={agent.icon}/></span>
      <span className="net-node-label">{agent.name}</span>
    </button>)}
  </div>;
}

type TeamRowProps = {
  team: Team;
  events: Signal[];
  pulses: ReadonlyMap<string, number>;
  source: string;
  online: boolean;
  historyUnavailable?: boolean;
  reportedRoles?: string[];
  onEvidence: (source: Source) => void;
};

function TeamRow({ team, events, pulses, source, online, historyUnavailable, reportedRoles, onEvidence }: TeamRowProps) {
  const agents = teams[team];
  const [selected, setSelected] = useState<string | null>(null);
  const [replay, setReplay] = useState<{ events: Signal[]; index: number } | null>(null);
  const frame = replay?.events[replay.index];
  useEffect(() => {
    if (!replay) return;
    const timer = window.setTimeout(() => setReplay(replay.index + 1 < replay.events.length
      ? { ...replay, index: replay.index + 1 } : null), 1250);
    return () => window.clearTimeout(timer);
  }, [replay]);
  const lit = frame ? new Set([frame.agent.name]) : new Set(pulses.keys());
  const counts = new Map<string, number>();
  for (const { agent } of events) counts.set(agent.name, (counts.get(agent.name) ?? 0) + 1);
  const picked = agents.find(agent => agent.name === selected);
  const visible = replay ? replay.events.slice(0, replay.index + 1).reverse()
    : events.filter(event => !selected || event.agent.name === selected);
  const pick = (name: string) => { setReplay(null); setSelected(current => current === name ? null : name); };
  const reading = frame ?? visible[0];
  const readoutAgent = picked ?? reading?.agent;
  const toggleReplay = () => {
    if (replay) { setReplay(null); return; }
    setReplay({ events: visible.slice(0, MAX_REPLAY).reverse(), index: 0 });
  };

  return <div className="net-grid">
    <section className="card net-map" aria-label={team + " agent network"}>
      <header className="net-heading">
        <div className="net-title"><h2>{team}</h2>
          <span className="net-source" data-online={online && !frame}><i/>{frame ? "Replaying activity" : source}</span>
        </div>
        <button className="net-replay" onClick={toggleReplay} disabled={!replay && !visible.length}>
          <span aria-hidden="true">{replay ? "Ⅱ" : "▷"}</span>{replay ? "Stop replay" : "Replay activity"}</button></header>
      <NetworkPlot agents={agents} counts={counts} selected={selected} lit={lit} onSelect={pick}/>
      <div className="net-readout" data-tone={readoutAgent?.tone}>
        <small>{replay ? "Replay" : picked ? "Selected" : "Latest"}</small>
        <strong>{readoutAgent?.name ?? "Standing by"}</strong><span>{reading?.message ?? picked?.role ?? "Waiting for an agent event."}</span>
      </div>
      <footer className="net-key"><span><i className="signal"/>New event</span><span><i className="reported"/>Has history</span><span><i/>No events</span></footer>
    </section>
    <section className="card net-stream" aria-label={team + " event stream"}>
      <header className="net-heading"><h2>{picked ? picked.name : "Event stream"}</h2>
        {picked ? <button className="net-reset" onClick={() => {setSelected(null); setReplay(null);}} aria-label="Show all agents">×</button>
          : <span className="net-total">{eventCount(events.length)}</span>}</header>
      {picked && <p className="net-role">{picked.role}</p>}
      {replay && <div className="net-playhead" role="status">Replaying event {replay.index + 1} of {replay.events.length}</div>}
      {visible.length ? <ol className="net-event-list" aria-label={team + " activity"} key={team + (selected || "")}>
        {visible.map(event => <li key={event.id} data-tone={event.agent.tone} className={event.id === frame?.id ? "current" : ""}>
          <div className="net-event-line"><strong>{event.agent.name}</strong>{event.time && <small>{event.time}</small>}</div>
          <p>{event.message}</p>
          {event.sources?.map((source, i) => <button className="net-evidence" key={i} onClick={() => onEvidence(source)}>{(source.file ?? source.source_file)?.split("/").pop() ?? "Source evidence"}</button>)}
        </li>)}
      </ol> : <div className="net-empty"><Glyph icon={picked?.icon || "pulse"}/><strong>{historyUnavailable ? "Run history unavailable" : "No events in this feed"}</strong>
        {!!reportedRoles?.length && <p>Reported roles · {reportedRoles.join(", ")}.</p>}
      </div>}
    </section>
  </div>;
}

export function AgentGraph({ data, scenario, stale, onEvidence }: {
  data: DashboardData; scenario: boolean; stale: boolean; onEvidence: (source: Source) => void;
}) {
  const signals = useMemo(() => activitySignals(data.activity), [data.activity]);
  const operations = signals.filter(event => teams.Operations.includes(event.agent));
  const specialists = signals.filter(event => teams.Specialists.includes(event.agent));
  const needsHistory = !scenario && specialists.length === 0;
  const run = useRunHistory(data, scenario, needsHistory);
  const recording = data.recordedAgentRun;
  const history = useMemo(() => {
    if (!needsHistory) return [];
    if (!hostedReplayBuild) return (run?.signals ?? []).filter(event => teams.Specialists.includes(event.agent));
    return (recording?.events ?? []).flatMap(event => {
      const agent = findAgent(event.agent);
      if (!agent || !teams.Specialists.includes(agent)) return [];
      return [{ id: "recorded:" + event.sequence, agent, time: "Recording · step " + event.sequence,
        at: 0, sources: event.citations, message: event.summary || event.tool || event.status }];
    }).reverse();
  }, [needsHistory, run, recording]);
  const recorded = isStaticMode() || hostedReplayBuild;
  const online = !recorded && !scenario && !stale;
  const pulses = useRecentSignals(signals, online);
  const simulated = data.sync?.mode === "replay" || data.agents?.mode === "simulated";
  const scope = stale ? "Connection interrupted" : scenario ? "Import scenario" : recorded ? "Recorded workspace"
    : simulated ? "Simulation" : "Live workspace";
  const reportedRoles = recording?.coverage === "summary_only"
    ? recording.reported_summary.roles.map(role => role.role) : run?.roles;
  return <div className="net-view">
    <TeamRow team="Operations" events={operations} pulses={pulses} source={scope} online={online} onEvidence={onEvidence}/>
    <TeamRow team="Specialists" events={needsHistory ? history : specialists} pulses={pulses}
      source={history.length && !stale ? "Last recorded run" : scope} online={online && !history.length}
      historyUnavailable={needsHistory && run?.error} reportedRoles={needsHistory ? reportedRoles : undefined} onEvidence={onEvidence}/>
  </div>;
}
