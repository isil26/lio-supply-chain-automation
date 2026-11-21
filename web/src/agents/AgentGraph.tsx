import { useEffect, useMemo, useState } from "react";
import { dashboardApi, hostedReplayBuild, isStaticMode, type AgentRun, type AgentTraceData, type AgentTraceStep, type Source } from "../api";
import type { RecordedAgentRun } from "./RecordedAgentTrace";
import mockTrace from "./mock.json";
import "./agentGraph.css";

// Live agent map: agents light up and hand-offs animate as trace steps arrive.
// Hosted/static builds replay the recorded art-book run step by step.

type NodeId = "file" | "triage" | "analyst" | "verifier" | "planner" | "chaser" | "you";
type Node = { id: NodeId; label: string; role: string; x: number; y: number; lx: number; ly: number; anchor: "start" | "middle" | "end" };

const R = 30;
const NODES: Node[] = [
  { id: "file", label: "New file", role: "from the portal", x: 56, y: 190, lx: 56, ly: 240, anchor: "middle" },
  { id: "triage", label: "Triage", role: "spots & hands out", x: 190, y: 190, lx: 190, ly: 242, anchor: "middle" },
  { id: "analyst", label: "Analyst", role: "finds the gap", x: 350, y: 76, lx: 390, ly: 72, anchor: "start" },
  { id: "verifier", label: "Verifier", role: "double-checks", x: 350, y: 190, lx: 390, ly: 222, anchor: "start" },
  { id: "planner", label: "Planner", role: "finds Plan B", x: 350, y: 304, lx: 350, ly: 356, anchor: "middle" },
  { id: "chaser", label: "Chaser", role: "writes suppliers", x: 520, y: 304, lx: 520, ly: 356, anchor: "middle" },
  { id: "you", label: "You", role: "final say", x: 640, y: 190, lx: 640, ly: 242, anchor: "middle" },
];
const BY_ID = Object.fromEntries(NODES.map((node) => [node.id, node])) as Record<NodeId, Node>;
const POSSIBLE: [NodeId, NodeId][] = [["file", "triage"], ["triage", "analyst"], ["triage", "planner"], ["analyst", "verifier"], ["planner", "verifier"], ["verifier", "you"], ["planner", "chaser"], ["chaser", "you"]];
const AGENTS: NodeId[] = ["triage", "analyst", "verifier", "planner", "chaser"];

const TOOL_TEXT: Record<string, string> = {
  get_readiness: "Checked how many copies can be packed by Sunday.",
  list_shortfalls: "Listed the parts that are running short.",
  compare_sources: "Compared SAP with the warehouse scans.",
  search_documents: "Searched the supplier documents for proof.",
  get_document: "Opened a document to read the exact line.",
  supplier_history: "Looked up how reliable this supplier has been.",
  whatif: "Tested what happens with a Plan B.",
  breakeven: "Worked out whether Plan B is worth its cost.",
  propose_option: "Proposed a Plan B. A person must approve it.",
  escalate_to_human: "Flagged this for a person to decide.",
  request_review: "Asked a person to review it.",
  draft_email: "Wrote a supplier email. It is not sent.",
  send_email: "Prepared the email. It goes out only after approval.",
  parse_reply: "Read the supplier's reply.",
};

// Plain story of the recorded live art-book run (facts from docs/agent_runs/art_book_live.json).
const RECORDED_TEXT: Record<string, string> = {
  triage: "A new file came in. The art book stock looks wrong, so I handed it to the team.",
  analyst: "The delivery note says 8,000 by hand, but SAP booked 80,000. Only 19,300 art books are usable for 25,200 Collector's editions.",
  verifier: "I checked the scan myself: 80,000 is crossed out. The 5,900 gap is real.",
  planner: "Plan B: ask the art book printer for an express quote. A person must approve it.",
  chaser: "I wrote the email to the printer in Polish. It is not sent.",
};

// What each role does, used when a recording only reports which roles ran.
const ROLE_TEXT: Partial<Record<NodeId, string>> = {
  triage: "Looked at the new file and handed the art book problem to the team.",
  analyst: "Looked for the gap in the art book stock.",
  verifier: "Double-checked the findings against the documents.",
  planner: "Worked out a Plan B for a person to approve.",
  chaser: "Prepared the supplier email.",
};

const nodeOf = (agent: string): NodeId | null => {
  const name = agent.toLowerCase();
  return AGENTS.find((id) => name.includes(id)) ?? null;
};

type GraphStep = Pick<AgentTraceStep, "agent" | "tool" | "args_summary" | "result_summary" | "status" | "citations"> & { recordedTarget?: string };

function sentence(step: GraphStep): string {
  const node = nodeOf(step.agent);
  if (!hostedReplayBuild && step.tool === "recorded_run" && node) return RECORDED_TEXT[node];
  if (step.tool === "delegate") {
    const target = /"(?:agent|role|to|specialist)"\s*:\s*"([^"]+)"/.exec(step.args_summary ?? "")?.[1];
    return target ? `Handed the work to ${target[0].toUpperCase()}${target.slice(1)}.` : "Handed the work to a specialist.";
  }
  const summary = (step.result_summary ?? "").trim();
  if (summary && !/^[[{]/.test(summary) && summary.length < 160 && !/^(completed|ok)$/i.test(summary)) return summary;
  return TOOL_TEXT[step.tool] ?? (step.tool ? `Used ${step.tool.replace(/_/g, " ")}.` : "Thinking…");
}

function curve(from: Node, to: Node) {
  const dx = to.x - from.x, dy = to.y - from.y, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const pad = (node: Node) => node.id === "file" ? 40 : R + 6;
  const sx = from.x + ux * pad(from), sy = from.y + uy * pad(from);
  const ex = to.x - ux * pad(to), ey = to.y - uy * pad(to);
  const bend = 14; // gentle bend keeps the two directions of a pair apart
  const cx = (sx + ex) / 2 - uy * bend, cy = (sy + ey) / 2 + ux * bend;
  return `M${sx.toFixed(1)},${sy.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}`;
}

const reducedMotion = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const STEP_MS = 1100;

export function AgentGraph({ recording, onEvidence, autoSend }: { recording?: RecordedAgentRun | null; onEvidence: (source: Source) => void; autoSend?: boolean }) {
  const recorded = hostedReplayBuild || isStaticMode();
  const [run, setRun] = useState<AgentRun | null>(null);
  const [liveTrace, setTrace] = useState<AgentTraceData>({ steps: [], approvals_pending: [] });
  const [shown, setShown] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const trace = useMemo((): { steps: GraphStep[]; approvals_pending: AgentTraceData["approvals_pending"] } => {
    if (!hostedReplayBuild) return liveTrace;
    if (recording && !recording.events?.length) {
      // Summary-only recording: no step events, so play the reported roles in hand-off order.
      const summary = recording.reported_summary;
      const order = ["triage", ...(summary?.delegation_targets ?? []).map((name) => name.toLowerCase())]
        .filter((name, index, all) => AGENTS.includes(name as NodeId) && all.indexOf(name) === index);
      const status = (name: string) => summary?.roles.find((item) => item.role.toLowerCase().includes(name))?.reported_status ?? "reported";
      return {
        steps: order.map((name, index) => ({
          agent: name[0].toUpperCase() + name.slice(1),
          tool: "reported_role",
          result_summary: `${ROLE_TEXT[name as NodeId] ?? "Did its part."} ${/^(completed|done|ok)$/i.test(status(name)) ? "Done in the recorded run." : `Recorded status: ${status(name)}.`}`,
          status: status(name),
          citations: [],
          recordedTarget: order[index + 1],
        })),
        approvals_pending: summary?.pending_approvals_reported ? [{ id: "reported-approval", title: "An approval" }] : [],
      };
    }
    return {
      steps: recording?.events.map((event) => ({
        agent: event.agent,
        tool: event.tool ?? "handoff",
        result_summary: event.summary ?? (event.target ? `Hand-off to ${event.target}` : undefined),
        status: event.status,
        citations: event.citations,
        recordedTarget: event.target ?? undefined,
      })) ?? [],
      approvals_pending: recording?.approvals_pending?.map((item) => ({ ...item, detail: item.detail ?? undefined })) ?? [],
    };
  }, [liveTrace, recording]);

  useEffect(() => {
    if (hostedReplayBuild) return;
    let alive = true;
    const load = async () => {
      try {
        const runs = await dashboardApi.getAgentRuns();
        const latest = runs[0] ?? null;
        const next = latest ? await dashboardApi.getAgentTrace(latest.id) : { steps: [], approvals_pending: [] };
        if (!alive) return;
        setRun((current) => {
          if (current && latest && current.id !== latest.id) { setShown(0); setPicked(null); } // a new run plays from its first step
          return latest;
        });
        setTrace(next.steps?.length ? next : mockTrace as AgentTraceData);
      } catch {
        if (alive) setTrace((current) => current.steps.length ? current : mockTrace as AgentTraceData);
      }
    };
    void load();
    if (recorded) return () => { alive = false; };
    const timer = window.setInterval(() => void load(), 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [recorded]);

  // Reveal one step at a time, so both replays and newly arriving live steps play in order.
  useEffect(() => {
    if (shown >= trace.steps.length) return;
    const timer = window.setTimeout(() => setShown((count) => count + 1), reducedMotion ? 0 : STEP_MS);
    return () => window.clearTimeout(timer);
  }, [shown, trace.steps.length]);

  const steps = trace.steps.slice(0, shown);
  const playing = shown < trace.steps.length;
  const running = !recorded && run?.status === "running";
  const finished = !playing && !running && steps.length > 0;

  const { done, path, active } = useMemo(() => {
    const visited = new Set<NodeId>();
    const hops: [NodeId, NodeId][] = [];
    let previous: NodeId = "file";
    for (const step of steps) {
      const node = nodeOf(step.agent);
      if (!node) continue;
      visited.add(node);
      const target = step.recordedTarget && nodeOf(step.recordedTarget);
      if (hostedReplayBuild) {
        if (previous === "file") hops.push(["file", node]);
        if (target && target !== node) hops.push([node, target]);
      } else if (node !== previous) hops.push([previous, node]);
      previous = node;
    }
    return { done: visited, path: hops, active: steps.length ? previous : null };
  }, [steps]);

  const waitingForYou = finished && (trace.approvals_pending.length > 0 || (!hostedReplayBuild && done.has("chaser")));
  const lastHop = path[path.length - 1];
  const hopKey = (a: NodeId, b: NodeId) => `${a}>${b}`;
  const litKeys = new Set(path.map(([a, b]) => hopKey(a, b)));
  const pairLit = (a: NodeId, b: NodeId) => litKeys.has(hopKey(a, b)) || litKeys.has(hopKey(b, a));
  const uniqueHops = [...new Map(path.map((hop) => [hopKey(...hop), hop])).values()];
  const finalHop: [NodeId, NodeId] | null = waitingForYou && active ? [active === "verifier" || active === "chaser" ? active : "chaser", "you"] : null;

  const focusIndex = picked ?? steps.length - 1;
  const focus = focusIndex >= 0 ? steps[focusIndex] : undefined;
  const status = running ? "Live" : playing ? (recorded ? "Replaying a recorded run" : "Playing the last run")
    : steps.length ? (hostedReplayBuild ? "Recording replayed" : "Run finished")
    : hostedReplayBuild ? (recording ? "Reported run summary" : "Recording unavailable") : "Waiting for a new file";
  const replay = () => { setPicked(null); setShown(0); };
  const pickNode = (id: NodeId) => {
    for (let i = steps.length - 1; i >= 0; i -= 1) if (nodeOf(steps[i].agent) === id) { setPicked(i); return; }
  };

  const nodeState = (id: NodeId) => {
    if (id === "file") return steps.length ? "done" : "idle";
    if (id === "you") return waitingForYou ? "active" : "idle";
    if (id === active && !finished) return "active";
    return done.has(id) ? "done" : "idle";
  };

  return <section className="card agent-graph" aria-labelledby="agent-graph-title">
    <div className="ag-head">
      <h3 id="agent-graph-title">Agents at work</h3>
      <span className={`ag-status ${running || playing ? "on" : ""}`}><i aria-hidden="true"/>{status}</span>
    </div>
    <div className="ag-body">
      <svg className="ag-svg" viewBox="0 0 700 380" role="img" aria-label="Map of the agents and how work passes between them">
        <defs>
          {["done", "now", "idle"].map((kind) => <marker key={kind} id={`ag-arrow-${kind}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0L10,5L0,10z" className={`ag-arrowhead ${kind}`}/>
          </marker>)}
        </defs>
        {POSSIBLE.filter(([a, b]) => !pairLit(a, b) && !(finalHop && finalHop[0] === a && finalHop[1] === b)).map(([a, b]) =>
          <path key={hopKey(a, b)} d={curve(BY_ID[a], BY_ID[b])} className="ag-edge idle" markerEnd="url(#ag-arrow-idle)"/>)}
        {uniqueHops.map(([a, b]) => {
          const now = !finished && lastHop && lastHop[0] === a && lastHop[1] === b;
          const d = curve(BY_ID[a], BY_ID[b]);
          return <g key={hopKey(a, b)}>
            <path d={d} className={`ag-edge ${now ? "now" : "done"}`} markerEnd={`url(#ag-arrow-${now ? "now" : "done"})`}/>
            {now && !reducedMotion && <circle r="5" className="ag-packet"><animateMotion dur="1.1s" repeatCount="indefinite" path={d}/></circle>}
          </g>;
        })}
        {finalHop && <g>
          <path d={curve(BY_ID[finalHop[0]], BY_ID[finalHop[1]])} className="ag-edge now" markerEnd="url(#ag-arrow-now)"/>
          {!reducedMotion && <circle r="5" className="ag-packet"><animateMotion dur="1.4s" repeatCount="indefinite" path={curve(BY_ID[finalHop[0]], BY_ID[finalHop[1]])}/></circle>}
        </g>}
        {NODES.map((node) => {
          const state = nodeState(node.id);
          const clickable = AGENTS.includes(node.id) && done.has(node.id);
          return <g key={node.id} className={`ag-node ${state} ${node.id} ${clickable ? "clickable" : ""}`}
            onClick={clickable ? () => pickNode(node.id) : undefined}
            role={clickable ? "button" : undefined} tabIndex={clickable ? 0 : undefined}
            onKeyDown={clickable ? (event) => { if (event.key === "Enter" || event.key === " ") pickNode(node.id); } : undefined}
            aria-label={clickable ? `Show what ${node.label} did` : undefined}>
            {node.id === "file"
              ? <rect x={node.x - 38} y={node.y - 24} width="76" height="48" rx="10" className="ag-shape"/>
              : <>{state === "active" && <circle cx={node.x} cy={node.y} r={R + 8} className="ag-halo"/>}<circle cx={node.x} cy={node.y} r={R} className="ag-shape"/></>}
            <text x={node.x} y={node.y + 5} textAnchor="middle" className="ag-letter">{node.id === "file" ? "📄" : node.id === "you" ? "You" : node.label[0]}</text>
            <text x={node.lx} y={node.ly} textAnchor={node.anchor} className="ag-label">{node.label}</text>
            <text x={node.lx} y={node.ly + 16} textAnchor={node.anchor} className="ag-role">{node.role}</text>
          </g>;
        })}
      </svg>

      <aside className="ag-side" aria-live="polite">
        {focus ? <>
          <span className="ag-kicker">{focus.agent} · step {focusIndex + 1} of {trace.steps.length}</span>
          <p className="ag-text">{sentence(focus)}</p>
          {(focus.citations ?? []).length > 0 && <div className="ag-chips">
            {(focus.citations ?? []).slice(0, 2).map((citation, index) => <button key={`${citation.file}-${index}`} className="ag-chip" onClick={() => onEvidence(citation)} title={citation.quote}>📄 {citation.file?.split("/").pop() ?? "Evidence"}</button>)}
          </div>}
        </> : <p className="ag-text muted">{hostedReplayBuild
          ? recording ? "See AI reasoning for reported roles and evidence coverage." : "No agent recording is available."
          : "When a new supplier file arrives, the agents start here."}</p>}
        {waitingForYou && picked === null && <div className="ag-you">
          <strong>Your turn</strong>
          {hostedReplayBuild ? <span>{trace.approvals_pending[0]?.title} was pending in the recording.</span>
            : <span>{done.has("chaser") ? "The supplier email is waiting for your OK." : `${trace.approvals_pending[0]?.title ?? "A Plan B is waiting for your OK"}.`} {autoSend ? "Routine supplier emails go out on their own. Anything that costs money waits for you." : "Nothing is sent without you."}</span>}
        </div>}
        <div className="ag-actions">
          {picked !== null && <button className="ag-btn" onClick={() => setPicked(null)}>Back to latest</button>}
          {finished && <button className="ag-btn" onClick={replay}>▶ Replay</button>}
        </div>
      </aside>
    </div>
    <p className="ag-legend"><span><i className="done"/>done</span><span><i className="now"/>happening now</span><span><i className="idle"/>possible path</span>
      {!hostedReplayBuild && finished && run?.harness?.ok !== false && <span className="ag-check">✓ Every number checked against a document</span>}</p>
  </section>;
}
