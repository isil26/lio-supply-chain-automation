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

const allAgents = [...teams.Operations, ...teams.Specialists];
const groups = { "All agents": allAgents, ...teams };
type Group = Team | "All agents";
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
  const all = agents === allAgents;
  const wrap = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < (all ? 760 : 525)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [all]);
  const hub = { x: 50, y: compact ? (all ? 5 : 10) : 50 };
  const junction = (agent: Agent) => teams.Operations.includes(agent) ? 25 : 75;
  const points = agents.map((agent, i) => {
    if (all) {
      const team = teams.Operations.includes(agent) ? teams.Operations : teams.Specialists;
      const index = team.indexOf(agent);
      const center = junction(agent);
      if (compact) return { x: center, y: 18 + index * 9 };
      const angle = -Math.PI / 2 + 2 * Math.PI * index / team.length;
      return { x: center + 17.5 * Math.cos(angle), y: 47 + 33 * Math.sin(angle) };
    }
    if (compact) return { x: i % 2 === 0 ? 25 : 75, y: 25 + Math.floor(i / 2) * 15 };
    const angle = -Math.PI / 2 + 2 * Math.PI * i / agents.length;
    return { x: 50 + 39 * Math.cos(angle), y: 49 + 36 * Math.sin(angle) };
  });
  return <div className={'net-plot' + (compact ? ' compact' : '') + (all ? ' net-all' : '')} ref={wrap}>
    <svg className="net-wires" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {all && !compact && <g className="net-orbits">
        {[25, 75].map(x => <g key={x}>
          <ellipse cx={x} cy="47" rx="17.5" ry="33"/><ellipse cx={x} cy="47" rx="12.3" ry="23.3"/>
          <path className="net-backbone" d={`M50 50 L${x} 47`}/>
        </g>)}
      </g>}
      {!all && !compact && <g className="net-orbits">
        <ellipse cx="50" cy="49" rx="39" ry="36"/><ellipse cx="50" cy="49" rx="30" ry="27"/><ellipse cx="50" cy="49" rx="18" ry="16.5"/>
      </g>}
      {agents.map((agent, i) => {
        const { x, y } = points[i];
        const litUp = lit.has(agent.name);
        const origin = all ? junction(agent) : 50;
        const d = all && !compact ? `M${origin} 47 C${origin} ${47 + (y-47)*.55} ${x} ${47 + (y-47)*.55} ${x} ${y}`
          : compact ? `M50 ${hub.y} V${y - 5} Q50 ${y} ${x > 50 ? 54 : 46} ${y} H${x}`
          : `M50 50 C${50 + (x - 50) * .45} 50 ${50 + (x - 50) * .5} ${y} ${x} ${y}`;
        return <g key={agent.name} data-tone={agent.tone} className={litUp ? "lit" : ""}>
          <path d={d} className="net-wire"/>
          {litUp && <path d={d} pathLength="1" className="net-traveler"/>}
        </g>;
      })}
    </svg>
    {all && (["Operations", "Specialists"] as const).map(name => <span key={name} className="net-junction"
      style={{left: name === "Operations" ? "25%" : "75%", top: compact ? "9%" : "47%"}}>{name}</span>)}
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

export function AgentGraph({ data, scenario, stale, onEvidence }: {
  data: DashboardData; scenario: boolean; stale: boolean; onEvidence: (source: Source) => void;
}) {
  const [team, setTeam] = useState<Group>("All agents");
  const [selected, setSelected] = useState<string | null>(null);
  const [replay, setReplay] = useState<{ events: Signal[]; index: number } | null>(null);
  const recorded = isStaticMode() || hostedReplayBuild;
  const connected = !recorded && !scenario;
  const signals = useMemo(() => activitySignals(data.activity), [data.activity]);
  const agents = groups[team];
  const teamSignals = useMemo(() => signals.filter(signal => agents.includes(signal.agent)), [signals, agents]);
  const needsRun = team !== "Operations" && !signals.some(signal => teams.Specialists.includes(signal.agent));
  const run = useRunHistory(data, scenario, needsRun);
  const recording = data.recordedAgentRun;
  const recordedSignals = useMemo(() => (recording?.events ?? []).flatMap(event => {
    const agent = findAgent(event.agent);
    return agent ? [{ id: "recorded:" + event.sequence, agent, time: "Recording · step " + event.sequence,
      at: 0, sources: event.citations, message: event.summary || event.tool || event.status }] : [];
  }).reverse(), [recording]);
  const history = needsRun ? (hostedReplayBuild ? recordedSignals : run?.signals ?? []) : [];
  const events = [...teamSignals, ...history];
  const pulses = useRecentSignals(signals, connected && !stale);
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
  const max = Math.max(1, ...counts.values());
  const picked = agents.find(agent => agent.name === selected);
  const visible = replay ? replay.events.slice(0, replay.index + 1).reverse()
    : events.filter(event => !selected || event.agent.name === selected);
  const reportedRoles = recording?.coverage === "summary_only"
    ? recording.reported_summary.roles.map(role => role.role) : run?.roles ?? [];
  const scope = scenario ? "Import scenario" : recorded ? "Recorded workspace" : data.sync?.mode === "replay" || data.agents?.mode === "simulated" ? "Simulation" : "Live workspace";
  const source = stale ? "Connection interrupted" : frame ? "Replaying activity" : team === "Specialists" && history.length ? "Last recorded run" : scope;
  const pick = (name: string) => { setReplay(null); setSelected(current => current === name ? null : name); };
  const reading = frame ?? visible[0];
  const readoutAgent = picked ?? reading?.agent;
  const toggleReplay = () => {
    if (replay) { setReplay(null); return; }
    setReplay({ events: visible.slice(0, MAX_REPLAY).reverse(), index: 0 });
  };

  return <div className={"net-view" + (team === "All agents" ? " overview" : "")}>
    <div className="net-toolbar">
      <div className="net-switch" role="group" aria-label="Agent group">
        {(Object.keys(groups) as Group[]).map(name => <button key={name} aria-pressed={team === name}
          onClick={() => { setTeam(name); setSelected(null); setReplay(null); }}>{name}<span>{groups[name].length}</span></button>)}
      </div>
      <span className="net-source" data-online={connected && !stale && !frame && !(team === "Specialists" && history.length)}><i/>{source}</span>
    </div>
    <div className="net-grid">
      <section className="card net-map" aria-label="Agent network">
        <header className="net-heading"><h2>Agent network</h2>
          <button className="net-replay" onClick={toggleReplay} disabled={!replay && !visible.length}>
            <span aria-hidden="true">{replay ? "Ⅱ" : "▷"}</span>{replay ? "Stop replay" : "Replay activity"}</button></header>
        <NetworkPlot agents={agents} counts={counts} selected={selected} lit={lit} onSelect={pick}/>
        <div className="net-readout" data-tone={readoutAgent?.tone}>
          <small>{replay ? "Replay" : picked ? "Selected" : "Latest"}</small>
          <strong>{readoutAgent?.name ?? "Standing by"}</strong><span>{reading?.message ?? picked?.role ?? "Waiting for an agent event."}</span>
        </div>
        <footer className="net-key"><span><i className="signal"/>New event</span><span><i className="reported"/>Has history</span><span><i/>No events</span></footer>
      </section>
      <section className="card net-stream">
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
        </ol> : <div className="net-empty"><Glyph icon={picked?.icon || "pulse"}/><strong>{run?.error && needsRun ? "Run history unavailable" : "No events in this feed"}</strong>
          {needsRun && reportedRoles.length > 0 && <p>Reported roles · {reportedRoles.join(", ")}.</p>}
        </div>}
      </section>
    <section className="card net-volume"><header className="net-heading"><h2>Activity by agent</h2><span className="net-total">Events in this feed</span></header>
      <div className="net-bars">{agents.map(agent => {
        const count = counts.get(agent.name) ?? 0;
        return <button key={agent.name} data-tone={agent.tone} aria-pressed={selected === agent.name}
          onClick={() => pick(agent.name)}><span>{agent.name}</span>
          <span className="net-bar"><i style={{width: (100 * count / max) + "%"}}/></span><b>{count}</b></button>;
      })}</div>
    </section>
    </div>
  </div>;
}
