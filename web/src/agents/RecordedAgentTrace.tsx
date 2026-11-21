import type { Source } from "../api";
import "./agents.css";

export type RecordedEvent = {
  sequence: number;
  kind: "tool" | "handoff";
  agent: string;
  tool: string | null;
  target: string | null;
  status: string;
  summary: string | null;
  recorded_at: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  citations: Source[];
};

type Usage = { cost_usd: number | null; input_tokens: number | null; output_tokens: number | null };

export type RecordedAgentRun = {
  coverage: "summary_only" | "verified_events";
  scenario: "art_book";
  run_id: string | null;
  timing: { started_at: string | null; finished_at: string | null; duration_ms: number | null };
  reported_summary: {
    model: string | null;
    aggregate_usage: Usage;
    roles: { role: string; reported_status: string }[];
    delegation_targets: string[];
    pending_approvals_reported: boolean | null;
    supplier_email_sent_reported: boolean | null;
  };
  verified_usage: Usage | null;
  events: RecordedEvent[];
  approvals_pending: { id: string; title: string; detail: string | null }[] | null;
  sources: { path: string; revision: string; sha256: string }[];
};

const usd = (amount: number | null | undefined) => amount == null ? "Unknown" : `$${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
const count = (amount: number | null | undefined) => amount == null ? "Unknown" : amount.toLocaleString("en-US");
const duration = (ms: number | null) => ms == null ? "Unknown" : `${ms.toLocaleString("en-US")} ms`;
const flag = (value: boolean | null) => value == null ? "Unknown" : value ? "Yes" : "No";

export function RecordedAgentTrace({ recording, onEvidence }: { recording?: RecordedAgentRun | null; onEvidence: (source: Source) => void }) {
  const verified = recording?.coverage === "verified_events";
  const summary = recording?.reported_summary;
  const usage = verified ? recording?.verified_usage : summary?.aggregate_usage;
  return <section className="agent-trace-panel" aria-labelledby="recorded-agent-title">
    <div className="agent-trace-heading">
      <div><p className="section-label">ART-BOOK SHORTFALL</p><h2 id="recorded-agent-title">{verified ? "Recorded live agent run" : recording ? "Reported live-run summary" : "Art-book recording"}</h2></div>
      {recording && <span className="agent-trace-status">{verified ? "Read-only replay" : "Detailed trace unavailable"}</span>}
    </div>
    {!recording || !summary ? <p className="agent-empty" role="status">No art-book recording is available for this replay.</p> : <>
      <p className="agent-trace-recorded">Model {summary.model ?? "unknown"}{recording.run_id ? ` · Run ${recording.run_id}` : ""}{recording.timing.started_at ? ` · Started ${recording.timing.started_at}` : ""}</p>
      <div className="agent-counters" aria-label={verified ? "Verified run metrics" : "Reported aggregate metrics"}>
        <div><strong>{usd(usage?.cost_usd)}</strong><span>{verified ? "Run cost (USD)" : "Reported cost (USD)"}</span></div>
        <div><strong>{count(usage?.input_tokens)}</strong><span>{verified ? "Input tokens" : "Reported input tokens"}</span></div>
        <div><strong>{count(usage?.output_tokens)}</strong><span>{verified ? "Output tokens" : "Reported output tokens"}</span></div>
        <div><strong>{duration(recording.timing.duration_ms)}</strong><span>Run duration</span></div>
      </div>
      {!verified && <p className="agent-trace-recorded">The source reports aggregate usage. Run boundaries, event order, and per-event timing and cost could not be verified.</p>}
      <div className="agent-work-grid">
        <div>
          {verified ? <>
            <div className="agent-stream-heading"><h3>Recorded events</h3><span>{recording.events.length} events</span></div>
            <div className="agent-timeline recorded-agent-timeline" aria-label="Recorded operational timeline">
              {recording.events.map((event) => <article className="agent-step" key={event.sequence}>
                <time dateTime={event.recorded_at ?? undefined} title={event.recorded_at ?? "Event timestamp unknown"}>{event.sequence}</time>
                <span className="agent-step-agent">{event.agent}</span>
                <span className="agent-step-tool">{event.kind === "handoff" ? `Hand-off to ${event.target}` : event.tool}</span>
                <span className="agent-step-reason"><b>{event.status}</b>
                  {event.summary && <><br/>{event.summary}</>}
                  <br/>{event.recorded_at ?? "Event time unknown"}
                </span>
                <div className="agent-citations">{event.citations.map((citation, index) =>
                  <button className="agent-citation" key={`${citation.file}-${index}`} onClick={() => onEvidence(citation)} title={citation.quote}>{citation.file?.split("/").pop() ?? "Evidence"}</button>)}</div>
                <span className="agent-step-meta" title={`Latency ${duration(event.latency_ms)} · Cost ${usd(event.cost_usd)}`}>{duration(event.latency_ms)} · {usd(event.cost_usd)}</span>
              </article>)}
            </div>
          </> : <>
            <div className="agent-stream-heading"><h3>Reported roles</h3></div>
            <ul className="recorded-agent-notes">{summary.roles.map(({ role, reported_status }) => <li key={role}><strong>{role}</strong> · {reported_status}</li>)}</ul>
            {summary.delegation_targets.length > 0 && <p className="recorded-agent-notes">Reported delegation targets {summary.delegation_targets.join(", ")}.</p>}
          </>}
        </div>
        <aside className="agent-side">
          <div className="agent-approvals">
            <h3>Human approval</h3>
            {recording.approvals_pending === null ? <div className="agent-approval-row"><div><strong>Verified approval details unavailable</strong><p>Pending approval reported {flag(summary.pending_approvals_reported).toLowerCase()}.</p></div></div>
              : recording.approvals_pending.length ? recording.approvals_pending.map((item) => <div className="agent-approval-row" key={item.id}><div><strong>{item.title}</strong><p>{item.detail ?? "Pending in the recording."}</p></div></div>)
              : <div className="agent-approval-row">No approval was pending in the recording.</div>}
            <p className="recorded-agent-notes">Supplier send reported {flag(summary.supplier_email_sent_reported).toLowerCase()}.</p>
          </div>
          <div className="agent-harness-panel recorded-agent-provenance">
            <h3>Provenance</h3>
            {recording.sources.map((source) => <p key={`${source.path}-${source.revision}`} title={`SHA-256 ${source.sha256}`}><code>{source.path}</code> · {source.revision.slice(0, 7)}</p>)}
          </div>
        </aside>
      </div>
    </>}
  </section>;
}
