import { useEffect, useMemo, useRef, useState } from "react";
import { dashboardApi, isStaticMode, hostedReplayBuild, type AgentRun, type AgentTraceData, type Source } from "../api";
import { roles } from "./types";
import "./agents.css";
import mockTrace from "./mock.json";

type Props = { onEvidence: (source: Source) => void; simulated?: boolean };

function money(value: number) {
  return value === 0 ? "—" : `$${value.toFixed(4)}`;
}

export function AgentTrace({ onEvidence, simulated }: Props) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [trace, setTrace] = useState<AgentTraceData>({ steps: [], approvals_pending: [] });
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [present, setPresent] = useState(false);
  const [replay, setReplay] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [visibleSteps, setVisibleSteps] = useState(0);
  const activeRoleRef = useRef<HTMLDivElement | null>(null);

  const recorded = hostedReplayBuild || isStaticMode();

  const load = async () => {
    try {
      const nextRuns = await dashboardApi.getAgentRuns();
      const run = nextRuns[0];
      setRuns(nextRuns);
      setSelected((current) => current || run?.id || "");
      if (run) {
        const nextTrace = await dashboardApi.getAgentTrace(run.id);
        setTrace(nextTrace.steps?.length ? nextTrace : mockTrace as AgentTraceData);
      } else setTrace(mockTrace as AgentTraceData);
      setError("");
    } catch (err) {
      setRuns([{ id: "recorded-art-book", event: "art_book_shortfall", status: "completed", cost: 0.057892, harness: { ok: true, violations: [] } }]);
      setTrace(mockTrace as AgentTraceData);
      setError(err instanceof Error ? err.message : "Agent trace unavailable; showing recorded run");
    }
  };

  useEffect(() => {
    void load();
    if (hostedReplayBuild || isStaticMode()) return;
    const timer = window.setInterval(() => void load(), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!replay) {
      setVisibleSteps(trace.steps.length);
      return;
    }
    setVisibleSteps(0);
  }, [replay, trace.steps.length, selected]);

  useEffect(() => {
    if (!replay || visibleSteps >= trace.steps.length) return;
    const latency = Math.max(650, trace.steps[visibleSteps]?.latency || 650);
    const timer = window.setTimeout(() => setVisibleSteps((count) => count + 1), latency / speed);
    return () => window.clearTimeout(timer);
  }, [replay, visibleSteps, speed, trace.steps]);

  useEffect(() => {
    if (present) activeRoleRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [present, trace.steps, visibleSteps]);

  const currentRun = runs.find((run) => run.id === selected) ?? runs[0];
  const statusLabel = hostedReplayBuild || isStaticMode() ? "replay" : simulated ? "simulation" : currentRun?.status === "running" ? "live" : "offline (deterministic mode)";
  const totalCost = useMemo(() => trace.steps.reduce((sum, step) => sum + (step.cost || 0), 0), [trace.steps]);

  const run = async () => {
    setBusy(true);
    try {
      const created = await dashboardApi.runAgent("data_drop");
      setSelected(created.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent run could not start");
    } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!currentRun) return;
    setBusy(true);
    try { await dashboardApi.stopAgent(currentRun.id); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Agent run could not stop"); }
    finally { setBusy(false); }
  };
  const decide = async (id: string, approve: boolean) => {
    setBusy(true);
    try {
      if (approve) await dashboardApi.approveDecision(id);
      else await dashboardApi.reviewDecision(id);
      setTrace((value) => ({ ...value, approvals_pending: value.approvals_pending.filter((item) => item.id !== id) }));
    } catch (err) { setError(err instanceof Error ? err.message : "Approval could not be updated"); }
    finally { setBusy(false); }
  };

  const shownSteps = replay ? trace.steps.slice(0, visibleSteps) : trace.steps;
  const inputTokens = currentRun?.input_tokens ?? trace.steps.reduce((sum, step) => sum + (step.input_tokens || 0), 0);
  const outputTokens = currentRun?.output_tokens ?? trace.steps.reduce((sum, step) => sum + (step.output_tokens || 0), 0);
  const elapsed = trace.steps.reduce((sum, step) => sum + (step.latency || 0), 0);
  const guardNames = ["Numeric grounding", "Citation check", "PP-07 policy", "Stop / oscillation", "Language"];
  const violations = currentRun?.harness?.violations ?? [];
  const guards = guardNames.map((name) => {
    const violation = violations.find((item) => `${item.rule} ${item.detail}`.toLowerCase().includes(name.toLowerCase().split(" ")[0]));
    return { name, ok: !violation, detail: violation?.detail };
  });
  const activeIndex = shownSteps.length ? Math.max(0, shownSteps.length - 1) : -1;
  const activeStep = activeIndex >= 0 ? shownSteps[activeIndex] : undefined;
  const activeRole = activeStep?.agent || "";
  const eventName = (event: unknown) => typeof event === "string" ? event : (event as { kind?: string } | undefined)?.kind ?? "";
  const triageDecision = (eventName(currentRun?.event) || "art_book_shortfall").replace(/_/g, " ");

  return <section className={`agent-trace-panel ${present ? "present" : ""}`} aria-labelledby="agent-team-title">
    <div className="agent-trace-heading">
      <div><p className="section-label">AGENT NETWORK</p><h2 id="agent-team-title">Agent team</h2></div>
      <div className="agent-trace-actions">
        <span className="agent-trace-status"><i aria-hidden="true"/>{`Agents: ${statusLabel}`}</span>
        <button className="agent-trace-button" onClick={() => setPresent((value) => !value)} aria-pressed={present}>{present ? "Exit Present" : "Present"}</button>
      </div>
    </div>
    {!present && <div className="agent-trace-controls">
      {!hostedReplayBuild && <button className="agent-trace-button primary" onClick={() => void run()} disabled={busy}>{busy ? "Working…" : "Run demo event"}</button>}
      {!hostedReplayBuild && currentRun?.status === "running" && <button className="agent-trace-button" onClick={() => void stop()} disabled={busy}>Stop run</button>}
      <button className={`agent-trace-button ${replay ? "primary" : ""}`} onClick={() => setReplay((value) => !value)} aria-pressed={replay}>Replay a recorded run</button>
      {replay && <label className="agent-speed">Speed
        <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select>
      </label>}
      {runs.length > 1 && <label className="agent-trace-button">Run <select value={selected} onChange={(event) => setSelected(event.target.value)}>{runs.map((item) => <option key={item.id} value={item.id}>{eventName(item.event) || item.id}</option>)}</select></label>}
    </div>}
    {(recorded || replay) && <p className="agent-trace-recorded">{replay ? "Recorded live agent run · redacted replay" : "Recorded live agent run"} · gpt-4.1-mini · {money(currentRun?.cost ?? totalCost)}</p>}
    {error && <p className="agent-trace-recorded" role="status">{error}</p>}

    <div className="agent-event-lane" aria-label="Event to decision lane">
      <div className="agent-event-step"><small>Incoming drop</small><strong>{triageDecision}</strong></div>
      <span className="agent-lane-arrow" aria-hidden="true">→</span>
      <div className="agent-event-step"><small>Triage decision</small><strong>ACT</strong><span>Launch component + deadline</span></div>
      <span className="agent-lane-arrow" aria-hidden="true">→</span>
      <div className="agent-event-step chain"><small>Agent chain</small><strong>Triage → Analyst → Verifier → Planner → Chaser</strong></div>
    </div>

    <div className="agent-counters" aria-label="Run counters">
      <div><strong>{(inputTokens + outputTokens).toLocaleString()}</strong><span>tokens</span></div>
      <div><strong>€{(totalCost * 0.92).toFixed(2)}</strong><span>cost</span></div>
      <div><strong>{currentRun?.step_count ?? shownSteps.length}</strong><span>steps</span></div>
      <div><strong>{elapsed < 1000 ? `${elapsed} ms` : `${(elapsed / 1000).toFixed(1)} s`}</strong><span>to decision</span></div>
    </div>

    <div className="agent-role-graph" aria-label="Agent hand-off graph">
      <div className="agent-world-node"><small>External world</small><strong>Portal / suppliers</strong></div>
      <span className="agent-role-arrow" aria-hidden="true">→</span>
      {roles.map((role, index) => <span key={role} style={{ display: "contents" }}>
        <div className={`agent-role ${activeRole.toLowerCase() === role.toLowerCase() ? "active" : shownSteps.some((step) => step.agent.toLowerCase() === role.toLowerCase()) ? "done" : ""}`}
          ref={activeRole.toLowerCase() === role.toLowerCase() ? activeRoleRef : undefined}>
          <small>{shownSteps.find((step) => step.agent.toLowerCase() === role.toLowerCase())?.status ?? "idle"}</small>
          <strong>{role}</strong>
          <span>{activeRole.toLowerCase() === role.toLowerCase()
            ? activeStep?.tool ? `calling ${activeStep.tool}` : "thinking"
            : shownSteps.find((step) => step.agent.toLowerCase() === role.toLowerCase())?.result_summary?.slice(0, 52) || "waiting"}</span>
        </div>
        {index < roles.length - 1 && <span className="agent-role-arrow" aria-hidden="true">→</span>}
      </span>)}
      <span className="agent-role-arrow" aria-hidden="true">→</span>
      <div className={`agent-role human-gate ${trace.approvals_pending.length ? "waiting" : "done"}`}><small>{trace.approvals_pending.length ? "waiting for approval" : "closed"}</small><strong>Human gate</strong><span>{trace.approvals_pending.length ? "decision required" : "no pending action"}</span></div>
    </div>

    <div className="agent-work-grid">
      <div>
        <div className="agent-stream-heading"><h3>Tool-call stream</h3><span>{shownSteps.length}/{trace.steps.length} steps</span></div>
        {shownSteps.length ? <div className="agent-timeline" aria-label="Agent trace timeline" aria-live="polite">
          {shownSteps.map((step, index) => <article className="agent-step" key={`${step.agent}-${step.tool}-${index}`}>
            <time>{String(index + 1).padStart(2, "0")}</time>
            <span className="agent-step-agent">{step.agent}</span>
            <span className="agent-step-tool">{step.tool}</span>
            <span className="agent-step-reason"><b>{step.args_summary || "—"}</b><br/>{step.result_summary || step.reason}</span>
            <div className="agent-citations">{(step.citations ?? []).map((citation, citationIndex) => <button className="agent-citation" key={`${citation.file}-${citationIndex}`} onClick={() => onEvidence(citation)} title={citation.quote}>{citation.file?.split("/").pop() ?? "Evidence"}</button>)}</div>
            <span className="agent-step-meta">{money(step.cost)} · {step.latency} ms</span>
          </article>)}
        </div> : <div className="agent-empty">No trace steps yet. Start an agent run or replay the recorded run.</div>}
      </div>

      <aside className="agent-side">
        <div className="agent-harness-panel" role="status">
          <h3>Harness</h3>
          {guards.map((guard) => <div className={`agent-guard ${guard.ok ? "ok" : "blocked"}`} key={guard.name}>
            <span aria-hidden="true">{guard.ok ? "✓" : "!"}</span>
            <div><strong>{guard.name}</strong>{guard.detail && <small>{guard.detail}</small>}</div>
          </div>)}
        </div>
        {trace.approvals_pending.length > 0 && <div className="agent-approvals">
          <h3>Human gate</h3>
          {trace.approvals_pending.map((approval) => <div className="agent-approval-row" key={approval.id}>
            <div><strong>{approval.title ?? approval.id}</strong><p>{approval.detail ?? "Human decision required before action."}</p></div>
            <div className="agent-approval-actions"><button className="agent-trace-button" onClick={() => void decide(approval.id, false)} disabled={busy}>Reject</button><button className="agent-trace-button primary" onClick={() => void decide(approval.id, true)} disabled={busy}>Approve</button></div>
          </div>)}
        </div>}
      </aside>
    </div>
  </section>;
}
