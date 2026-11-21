import React, { useEffect, useMemo, useState } from "react";
import { hostedReplayBuild, type Activity, type Source } from "./api";
import { AgentTrace } from "./agents/AgentTrace";
import { RecordedAgentTrace, type RecordedAgentRun } from "./agents/RecordedAgentTrace";

type Agent = { name: string; title: string; does: string; icon: keyof typeof ICONS };

// Plain-language roles for the agents that report into the activity feed, in hand-off order.
const CATALOG: Agent[] = [
  { name: "Data Bridge", title: "Watcher", does: "Watches the customer portal and picks up every new or changed file.", icon: "inbox" },
  { name: "Document Agent", title: "Reader", does: "Reads PDFs, scans and handwriting in Korean, Chinese, Polish and English, and cites the exact line.", icon: "doc" },
  { name: "Readiness Engine", title: "Counter", does: "Counts the real usable stock and simulates the packing lines up to Sunday 20:00.", icon: "gauge" },
  { name: "Decision Copilot", title: "Planner", does: "Lists the fixes, puts a price on each and checks who has to sign.", icon: "scale" },
  { name: "Supplier Chaser", title: "Messenger", does: "Writes to each supplier in their own language and reads the replies.", icon: "mail" },
];
const YOU: Agent = { name: "You", title: "Approver", does: "Nothing is sent or bought until a person approves it.", icon: "person" };

const ICONS = {
  inbox: <><path d="M4 13h4l1.5 3h5L16 13h4"/><path d="M5 13 7 5h10l2 8v6H5z"/></>,
  doc: <><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/></>,
  gauge: <><path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 17 4-5"/></>,
  scale: <><path d="M12 4v16M6 20h12M5 8h14"/><path d="m5 8-2 6a3 3 0 0 0 4 0L5 8Zm14 0-2 6a3 3 0 0 0 4 0l-2-6Z"/></>,
  mail: <><rect x="3" y="6" width="18" height="12" rx="2"/><path d="m4 7 8 6 8-6"/></>,
  person: <><circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6"/></>,
  agent: <><rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01"/></>,
};

function Glyph({ name }: { name: keyof typeof ICONS }) {
  return <svg viewBox="0 0 24 24" className="bs-glyph" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name]}</svg>;
}

const short = (text: string) => { const first = text.split(/(?<=\.)\s|\s·\s/)[0]; return first.length > 120 ? `${first.slice(0, 117)}…` : first; };
const tidy = (text: string) => text.replace(/soony\/|suppliers\/SUP-\d+_[^/]+\//g, "").replace(/_/g, " ");

export function BehindScenes({ activity, recording, onClose, onEvidence }: {
  activity: Activity[]; recording?: RecordedAgentRun | null; onClose: () => void; onEvidence: (s: Source) => void;
}) {
  const agents = useMemo(() => {
    const seen = new Set(CATALOG.map((a) => a.name));
    const extra = [...new Set(activity.map((a) => a.agent))].filter((n) => !seen.has(n))
      .map((name): Agent => ({ name, title: "Agent", does: "Reports its work to the activity log.", icon: "agent" }));
    return [...CATALOG.filter((a) => activity.some((x) => x.agent === a.name)), ...extra, YOU];
  }, [activity]);

  const byAgent = useMemo(() => {
    const map = new Map<string, Activity[]>();
    for (const item of activity) map.set(item.agent, [...(map.get(item.agent) ?? []), item]);
    return map;
  }, [activity]);

  // One hand-off per agent: its most recent action, passed to the next agent in line.
  const handoffs = agents.slice(0, -1).map((agent, i) => ({
    from: agent, to: agents[i + 1], text: short(tidy(((byAgent.get(agent.name) ?? []).find((x) => x.type !== "warning") ?? byAgent.get(agent.name)?.[0])?.action ?? "Standing by")),
  }));

  const [selected, setSelected] = useState(agents[0]?.name ?? "");
  const [step, setStep] = useState(handoffs.length);
  const [tab, setTab] = useState<"flow" | "reasoning">("flow");
  const playing = step < handoffs.length;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => setStep((s) => s + 1), 1300);
    return () => window.clearTimeout(timer);
  }, [step, playing]);
  useEffect(() => { if (playing) setSelected(handoffs[step]?.from.name ?? selected); }, [step]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const current = agents.find((a) => a.name === selected) ?? agents[0];
  const log = byAgent.get(current?.name ?? "") ?? [];
  const active = playing ? handoffs[step]?.from.name : "";

  return <div className="bs-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="bs-panel" role="dialog" aria-modal="true" aria-label="Behind the scenes" onMouseDown={(e) => e.stopPropagation()}>
      <header className="bs-head">
        <div><h2>Behind the scenes</h2><p>{agents.length - 1} agents working for you</p></div>
        <div className="bs-head-actions">
          <div className="bs-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "flow"} className={tab === "flow" ? "on" : ""} onClick={() => setTab("flow")}>Agents</button>
            <button role="tab" aria-selected={tab === "reasoning"} className={tab === "reasoning" ? "on" : ""} onClick={() => setTab("reasoning")}>AI reasoning</button>
          </div>
          {tab === "flow" && <button className="primary-button small" onClick={() => setStep(0)} disabled={playing}>{playing ? "Playing…" : "▶ Replay"}</button>}
          <button className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
      </header>

      {tab === "reasoning" ? <div className="bs-body">
        {hostedReplayBuild ? <RecordedAgentTrace recording={recording} onEvidence={onEvidence}/> : <AgentTrace onEvidence={onEvidence}/>}
      </div> : <div className="bs-body">
        <div className="bs-flow" aria-label="Agent hand-offs">
          {agents.map((agent, i) => <React.Fragment key={agent.name}>
            <button className={`bs-node ${selected === agent.name ? "selected" : ""} ${active === agent.name ? "active" : ""} ${agent === YOU ? "you" : ""}`}
              onClick={() => { setStep(handoffs.length); setSelected(agent.name); }}>
              <span className="bs-icon"><Glyph name={agent.icon}/></span>
              <strong>{agent.name}</strong>
              <small>{agent === YOU ? "approves" : `${byAgent.get(agent.name)?.length ?? 0} actions`}</small>
            </button>
            {i < agents.length - 1 && <span className={`bs-link ${playing && step === i ? "sending" : ""} ${step > i ? "done" : ""}`} aria-hidden="true"><i/></span>}
          </React.Fragment>)}
        </div>

        <div className="bs-columns">
          <section className="bs-chat" aria-label="How the agents talk to each other">
            <h3>How they talk</h3>
            {handoffs.slice(0, playing ? step + 1 : handoffs.length).map((h, i) => <div key={i} className={`bs-msg ${playing && i === step ? "typing" : ""}`}>
              <div className="bs-msg-head"><span className="bs-mini"><Glyph name={h.from.icon}/></span><b>{h.from.name}</b><span className="muted">→ {h.to.name}</span></div>
              <p>{playing && i === step ? <span className="bs-dots"><i/><i/><i/></span> : h.text}</p>
            </div>)}
          </section>

          {current && <section className="bs-detail" aria-label={`${current.name} details`}>
            <div className="bs-detail-head"><span className="bs-icon big"><Glyph name={current.icon}/></span><div><h3>{current.name}</h3><span className="muted">{current.title}</span></div></div>
            <p className="bs-does">{current.does}</p>
            {current === YOU ? <p className="muted">Approvals happen on the main screen and in each supplier thread.</p> : <>
              <h4>Latest work</h4>
              <ul className="bs-log">{log.slice(0, 8).map((item) => <li key={item.id}><span className={`bs-dot ${item.type}`}/><span>{tidy(item.action)}</span>{item.time && <time>{item.time}</time>}</li>)}</ul>
              {log.length > 8 && <p className="muted small-text">+ {log.length - 8} earlier actions</p>}
            </>}
          </section>}
        </div>
      </div>}
    </section>
  </div>;
}
