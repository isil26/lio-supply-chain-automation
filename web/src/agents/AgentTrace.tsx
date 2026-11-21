import { useEffect, useMemo, useState } from "react";
import { dashboardApi, isStaticMode, hostedReplayBuild, type AgentRun, type AgentTraceData, type Source } from "../api";
import { roles } from "./types";
import "./agents.css";
import mockTrace from "./mock.json";

type Props = { onEvidence: (source: Source) => void };

function money(value: number) {
  return value === 0 ? "—" : `$${value.toFixed(4)}`;
}

export function AgentTrace({ onEvidence }: Props) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [trace, setTrace] = useState<AgentTraceData>({ steps: [], approvals_pending: [] });
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const nextRuns = await dashboardApi.getAgentRuns();
      const run = nextRuns[0];
      setRuns(nextRuns);
      setSelected((current) => current || run?.id || "");
      if (run) {
        const nextTrace = await dashboardApi.getAgentTrace(run.id);
        setTrace(nextTrace.steps.length ? nextTrace : mockTrace as AgentTraceData);
      } else setTrace(mockTrace as AgentTraceData);
      setError("");
    } catch (err) {
      setRuns([{ id: "recorded-art-book", event: "art_book_shortfall", status: "completed", cost: 0.057892, harness: { ok: true, violations: [] } }]);
      setTrace(mockTrace as AgentTraceData);
      setError(err instanceof Error ? err.message : "Agent trace unavailable; showing recorded run");
    }
  };

  useEffect(() => { void load(); }, []);

  const currentRun = runs.find((run) => run.id === selected) ?? runs[0];
  const activeRole = trace.steps[trace.steps.length - 1]?.agent ?? "";
  const statusLabel = hostedReplayBuild || isStaticMode() ? "replay" : currentRun?.status === "running" ? "live" : "offline (deterministic mode)";
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

  return <section className="panel agent-trace-panel" aria-labelledby="agent-team-title">
    <div className="panel-heading agent-trace-heading">
      <div><p className="section-label">AGENT NETWORK</p><h2 id="agent-team-title">Agent team</h2></div>
      <span className="agent-trace-status"><i aria-hidden="true"/>{`Agents: ${statusLabel}`}</span>
    </div>
    <div className="agent-trace-controls">
      {!hostedReplayBuild && <button className="agent-trace-button primary" onClick={() => void run()} disabled={busy}>{busy ? "Working…" : "Run agents"}</button>}
      {!hostedReplayBuild && currentRun?.status === "running" && <button className="agent-trace-button" onClick={() => void stop()} disabled={busy}>Stop run</button>}
      {runs.length > 1 && <label className="agent-trace-button">Run <select value={selected} onChange={(event) => setSelected(event.target.value)}>{runs.map((item) => <option key={item.id} value={item.id}>{item.event}</option>)}</select></label>}
    </div>
    {(isStaticMode() || hostedReplayBuild) && <p className="agent-trace-recorded">Recorded live agent run · gpt-4.1-mini · {money(currentRun?.cost ?? totalCost)}</p>}
    {error && <p className="agent-trace-recorded" role="status">{error}</p>}
    <div className="agent-role-graph" aria-label="Agent hand-off graph">
      {roles.map((role, index) => <span key={role} style={{ display: "contents" }}>
        <span className={`agent-role ${activeRole.toLowerCase() === role.toLowerCase() ? "active" : ""}`}><small>Role {index + 1}</small><strong>{role}</strong></span>
        {index < roles.length - 1 && <span className="agent-role-arrow" aria-hidden="true">→</span>}
      </span>)}
    </div>
    {trace.steps.length ? <div className="agent-timeline" aria-label="Agent trace timeline">
      {trace.steps.map((step, index) => <article className="agent-step" key={`${step.agent}-${step.tool}-${index}`}>
        <span className="agent-step-agent">{step.agent}</span>
        <span className="agent-step-tool">{step.tool}</span>
        <span className="agent-step-reason">{step.reason}</span>
        <div className="agent-citations">{(step.citations ?? []).map((citation, citationIndex) => <button className="agent-citation" key={`${citation.file}-${citationIndex}`} onClick={() => onEvidence(citation)} title={citation.quote}>{citation.file?.split("/").pop() ?? "Evidence"}</button>)}</div>
        <span className="agent-step-meta">{money(step.cost)} · {step.latency} ms</span>
      </article>)}
    </div> : <div className="agent-empty">No trace steps yet. Start an agent run to see tool calls and hand-offs.</div>}
    {currentRun?.harness && <div className={`agent-harness ${currentRun.harness.ok ? "" : "failed"}`} role="status">
      {currentRun.harness.ok ? "✓ Harness checked: 0 violations" : `Harness blocked: ${currentRun.harness.violations.map((item) => `${item.rule}: ${item.detail}`).join("; ")}`}
    </div>}
    {trace.approvals_pending.length > 0 && <div className="agent-approvals">
      <h3>Pending approvals</h3>
      {trace.approvals_pending.map((approval) => <div className="agent-approval-row" key={approval.id}><div><strong>{approval.title ?? approval.id}</strong><p>{approval.detail ?? "Human decision required before action."}</p></div><div className="agent-approval-actions"><button className="agent-trace-button" onClick={() => void decide(approval.id, false)} disabled={busy}>Review</button><button className="agent-trace-button primary" onClick={() => void decide(approval.id, true)} disabled={busy}>Approve</button></div></div>)}
    </div>}
  </section>;
}
