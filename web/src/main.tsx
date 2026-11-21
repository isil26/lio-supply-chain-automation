import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  dashboardApi,
  isStaticMode,
  hostedReplayBuild,
  resetHostedReplay,
  type DashboardData,
  type Risk,
  type Source,
  type SupplierThread,
  type SupplierMessage,
  type SupplierAction,
} from "./api";
import { AgentTrace } from "./agents/AgentTrace";
import { AgentGraph } from "./agents/AgentGraph";
import { BestSupplier } from "./suppliers/BestSupplier";
import { MantiLogo, SupplyMap } from "./SupplyMap";
import { BehindScenes } from "./BehindScenes";
import "./styles.css";

const Icon = ({ name }: { name: "grid" | "risk" | "thread" | "approval" | "moon" | "sun" | "check" | "arrow" }) => {
  const paths: Record<typeof name, React.ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    risk: <><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5"/><path d="M12 17.5v.5"/></>,
    thread: <><path d="M4 5h16v12H8l-4 3V5Z"/><path d="M8 9h8M8 13h5"/></>,
    approval: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="m8 12 3 3 5-6"/></>,
    moon: <path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
    check: <path d="m5 12 4 4L19 7"/>,
    arrow: <><path d="M5 12h14"/><path d="m14 7 5 5-5 5"/></>,
  };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
};

function Countdown({ deadline }: { deadline: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const diff = Math.max(0, new Date(deadline).getTime() - now);
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor(diff / 60000) % 60;
  return <div className="countdown" aria-label="Time to launch"><strong>{hours}h {String(minutes).padStart(2, "0")}m</strong><span>left</span></div>;
}

function formatNumber(value: number | undefined) {
  return typeof value === "number" ? value.toLocaleString("en-US") : "—";
}

const etaDate = new Intl.DateTimeFormat("en-GB", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Berlin" });

function SupplierActions({ actions, select, mailView, onEvidence }: {
  actions: SupplierAction[]; select: (id: string) => void; mailView: boolean; onEvidence: (source: Source) => void;
}) {
  return <section aria-label="Supplier decisions and actions">
    {actions.map((action) => <div className="decision-analysis" id={`action-${action.id}`} key={action.id}>
      <strong>{action.title}</strong>
      <p>{action.scope === "demo" ? "Simulation" : action.scope === "verified" ? "Verified mailbox" : "Live workflow"} · {{
        escalated: "Escalated", approval_required: "Approval queued", queued: "Ready for review", awaiting_reply: "Awaiting reply",
      }[action.status]}{action.owner && <> · {action.owner}</>}</p>
      <p>{action.detail}</p>
      {action.facts.length > 0 && <blockquote>{action.facts.join(" · ")}</blockquote>}
      {action.eta && <p>Reported ETA · {etaDate.format(new Date(action.eta))} CET</p>}
      {action.impact?.map((row) => <p key={row.edition}>{row.edition} median packs · {formatNumber(row.before)} → {formatNumber(row.after)}
        <br/>With modeled faster dock handling · {formatNumber(row.withDock)}
        <br/>On-time probability · {row.pBefore.toLocaleString("en-US", { style: "percent", maximumFractionDigits: 1 })} → {row.pAfter.toLocaleString("en-US", { style: "percent", maximumFractionDigits: 1 })}</p>)}
      {action.reportedUnits != null && <p>{formatNumber(action.reportedUnits)} units reported · {formatNumber(action.unitsUncovered)} of {formatNumber(action.unitsNeeded)} uncovered if the offer arrives in time</p>}
      {action.transport && <p>{({
        dry_run: "Dry-run dispatch", smtp_accepted: "Accepted by SMTP", gmail_sent: "Verified in Gmail Sent",
        attempting: "Transport attempt requires reconciliation", delivery_uncertain: "Delivery uncertain", failed: "Dispatch failed",
      } as Record<string, string>)[action.transport.status] ?? "Transport unverified"} · {action.transport.messageId}</p>}
      {action.dueAt && <p>Reply check · {etaDate.format(new Date(action.dueAt))} CET</p>}
      {action.threadId && (action.replyId != null ?
        <a className="ghost-button" href={`?${mailView ? "mail=1&" : ""}thread=${encodeURIComponent(action.threadId)}#message-${action.replyId}`}>Matched reply</a> :
        <button className="ghost-button" onClick={() => select(action.threadId!)}>Open supplier thread</button>)}
      {action.policy && <button className="ghost-button" onClick={() => onEvidence({ file: action.policy })}>PP-07</button>}
    </div>)}
  </section>;
}

function EvidenceModal({ source, onClose }: { source: Source; onClose: () => void }) {
  const file = source.source_file ?? source.file ?? "";
  const [raw, setRaw] = useState("");
  useEffect(() => {
    if (!file || hostedReplayBuild || isStaticMode()) return;
    dashboardApi.getSource(file).then(setRaw).catch(() => setRaw(""));
  }, [file]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="evidence-modal" role="dialog" aria-modal="true" aria-label="Source evidence" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><p className="section-label">SOURCE EVIDENCE</p><h2>{file}</h2></div><button onClick={onClose} aria-label="Close">×</button></header>
      <div className="evidence-location">{source.page ? `Page ${source.page}` : source.row ? `Row ${source.row}` : "Source location"}{source.confidence != null ? ` · ${Math.round(source.confidence * 100)}% confidence` : ""}</div>
      {source.quote && <blockquote>{source.quote}</blockquote>}
      {!hostedReplayBuild && !isStaticMode() && raw ? <a className="source-link" href={`/api/source/${file.split("/").map(encodeURIComponent).join("/")}`} target="_blank" rel="noreferrer">Open original source <Icon name="arrow"/></a> : null}
    </section>
  </div>;
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(true);
  const [behind, setBehind] = useState(false);
  const [threadId, setThreadId] = useState(() => new URLSearchParams(window.location.search).get("thread") || "");
  const [mailView, setMailView] = useState(() => new URLSearchParams(window.location.search).get("mail") === "1");
  const [threadsOpen, setThreadsOpen] = useState(() => Boolean(threadId) || mailView);
  const [dropVisible, setDropVisible] = useState(true);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [replyBusy, setReplyBusy] = useState(false);
  const [meta, setMeta] = useState<{ exported?: string; mode?: string }>({});

  const refresh = async () => {
    try {
      const next = await dashboardApi.getDashboard();
      setData(next);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Launch snapshot unavailable");
    }
  };

  useEffect(() => {
    void refresh();
    void dashboardApi.getMeta().then(setMeta).catch(() => setMeta({}));
    if (hostedReplayBuild) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const visibleThreads = mailView ? data?.mailHistory?.threads : data?.threads;
  const selectedThread = useMemo<SupplierThread | undefined>(() => (
    visibleThreads?.find((thread) => thread.id === threadId) ?? visibleThreads?.[0]
  ), [visibleThreads, threadId]);
  const supplierActions = mailView ? data?.mailHistory?.actions : data?.supplierActions;

  if (!data) return <main className="loading-screen"><div className="loader"/><strong>{error || "Loading launch state…"}</strong>{error && <button onClick={() => void refresh()}>Retry</button>}</main>;

  const approval = data.approval;
  const timing = approval?.supplier_timing;
  const expedite = approval?.expedite;
  const grid = expedite?.sensitivity[0];
  const health = data.dataHealth;
  const age = health?.lastSyncAgeSeconds;
  const euros = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
  const sourceReviews = [...(data.sync?.warnings ?? []), ...(data.documentReviews ?? [])];
  const pendingDrop = (data.sync?.pendingDrop ?? 0) > 0;
  const riskEvidence = (risk: Risk) => risk.sources?.[0] ?? (risk.evidence[0] ? { quote: risk.evidence[0] } : null);

  const approve = async (review = false) => {
    if (!approval?.id) return;
    setDecisionBusy(true);
    try {
      if (review) await dashboardApi.reviewDecision(approval.id);
      else await dashboardApi.approveDecision(approval.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision could not be updated");
    } finally {
      setDecisionBusy(false);
    }
  };

  const send = async () => {
    if (!selectedThread) return;
    setSendBusy(true);
    try {
      await dashboardApi.sendThread(selectedThread.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Supplier draft could not be sent");
    } finally {
      setSendBusy(false);
    }
  };

  const openMail = (real: boolean) => {
    setMailView(real);
    setThreadId("");
    const url = new URL(window.location.href);
    if (real) url.searchParams.set("mail", "1");
    else url.searchParams.delete("mail");
    url.searchParams.delete("thread");
    url.hash = "";
    window.history.replaceState(null, "", url);
  };

  const selectThread = (id: string) => {
    setThreadId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("thread", id);
    url.hash = "";
    window.history.replaceState(null, "", url);
  };

  const approveReply = async (message: SupplierMessage) => {
    if (!message.id) return;
    setDecisionBusy(true);
    try {
      await dashboardApi.approveReply(message.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reply decision could not be approved");
    } finally { setDecisionBusy(false); }
  };

  const demoReply = async (scenario?: "on-time" | "delayed") => {
    if (!selectedThread) return;
    setReplyBusy(true);
    try {
      await dashboardApi.replyThread(selectedThread.id, undefined, scenario);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo reply could not be added");
    } finally {
      setReplyBusy(false);
    }
  };

  const resetDemo = async () => {
    try {
      await dashboardApi.resetDemo();
      setDropVisible(true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo could not be reset");
    }
  };

  const runSync = async (reset = false) => {
    setSyncBusy(true);
    try {
      if (reset) await resetHostedReplay();
      else await dashboardApi.sync();
      setDropVisible(true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync could not start");
    } finally {
      setSyncBusy(false);
    }
  };

  const editionName = (edition: string) => edition === "CE" ? "Collector's Edition" : "Standard Edition";
  const editions = data.readiness.map((item) => {
    const expected = item.p50 ?? item.packed;
    return { ...item, expected, short: Math.max(0, item.target - expected) };
  });
  const totalShort = editions.reduce((sum, item) => sum + item.short, 0);
  const onTrack = editions.every((item) => (item.probability ?? 0) >= 0.9);
  const gapOf = (risk: Risk) => risk.gap ?? (Number(String(risk.shortfall).replace(/[^\d.]/g, "")) * (/k/i.test(risk.shortfall) ? 1000 : 1) || 0);
  const missing = data.risks.filter((risk) => gapOf(risk) > 0).slice(0, 3);
  const shortName = (name: string) => name.replace(/\s*[–-]\s*Grand Heist 6/i, "").replace(/Grand Heist 6\s*/i, "").replace(/\s*\(.*\)\s*/, "").replace(/"/g, "").trim();
  const reason = (risk: Risk) => (risk.detail?.[0] ?? risk.evidence[0] ?? "").replace(/^[A-Z0-9-]+(?:\s[A-Z0-9-]+)?:\s*/, "").replace(/^\d{3}-\d{6,}\s+/, "Shipment ");
  const drafts = data.threads.filter((thread) => ["draft", "loop draft"].includes(thread.status)).length;
  const reviews = health?.needsReview ?? sourceReviews.length;
  const deadline = new Date(data.launch.deadline);

  return <main className={dark ? "theme-dark" : "theme-light"}>
    <section className="page">
      <header className="topbar">
        <div className="topbar-left"><MantiLogo/><span className="divider"/><h1>{data.launch.name}</h1></div>
        <div className="top-actions">
          <button className="behind-button" onClick={() => setBehind(true)}><i className="live"/>See what the agents do</button>
          <Countdown deadline={data.launch.deadline}/>
          {isStaticMode() && <button className="ghost-button" onClick={() => void resetDemo()}>Reset</button>}
          {hostedReplayBuild && <form method="post" action="/logout"><button className="ghost-button" type="submit">Sign out</button></form>}
          <button className="icon-button" onClick={() => setDark((value) => !value)} title="Toggle theme" aria-label="Toggle theme"><Icon name={dark ? "sun" : "moon"}/></button>
        </div>
      </header>

      {data.sync?.error && <div className="notice alert" role="alert">{data.sync.error}</div>}
      {error && <div className="notice alert">{error}<button className="link-button" onClick={() => setError("")}>Dismiss</button></div>}
      {dropVisible && data.drop && (pendingDrop || isStaticMode() || hostedReplayBuild) && <div className="notice">
        <span>New supplier files</span>
        <button className="primary-button small" onClick={() => void runSync(hostedReplayBuild && !pendingDrop)} disabled={syncBusy}>{syncBusy ? "Updating…" : hostedReplayBuild && !pendingDrop ? "Reset" : "Update"}</button>
      </div>}

      <section className="hero">
        <h2>{onTrack ? "On track for Sunday" : <><span className="big-number">{formatNumber(totalShort)}</span> copies short on Sunday</>}</h2>
        <div className="editions">
          {editions.map((item) => <div className="edition" key={item.edition}>
            <div className="edition-row"><span>{item.edition === "CE" ? "Collector's" : "Standard"}</span><strong>{item.short ? `−${formatNumber(item.short)}` : "✓"}</strong></div>
            <div className="bar" aria-label={`${formatNumber(item.expected)} of ${formatNumber(item.target)}`}>
              <i className="packed" style={{ width: `${(item.packed / item.target) * 100}%` }}/>
              <i className="expected" style={{ width: `${(Math.min(item.expected, item.target) / item.target) * 100}%` }}/>
            </div>
          </div>)}
        </div>
        <p className="legend"><i className="dot packed"/>packed <i className="dot expected"/>expected by Sunday <i className="dot track"/>missing</p>
      </section>

      <div className="columns">
        <section className="card">
          <h3>Missing parts</h3>
          {missing.length ? <ol className="missing">
            {missing.map((risk) => {
              const evidence = riskEvidence(risk);
              return <li key={`${risk.rank}-${risk.id ?? risk.component}`}>
                <strong>{shortName(risk.component)}</strong>
                <span className="missing-right"><b>{formatNumber(gapOf(risk))}</b>{evidence && <button className="link-button" onClick={() => setSource(evidence)}>Why?</button>}</span>
              </li>;
            })}
          </ol> : <p className="empty">None</p>}
        </section>

        <section className="card decision">
          <h3>Next step</h3>
          {approval ? <>
            <p className="decision-title">{approval.title}</p>
            {approval.price != null && <p className="price">€{Math.round(approval.price).toLocaleString("en-US")}</p>}
            {!hostedReplayBuild && <div className="actions">
              <button className="primary-button" onClick={() => void approve(false)} disabled={decisionBusy || approval.status === "approved"}>{approval.status === "approved" ? <><Icon name="check"/> Approved</> : "Approve"}</button>
              <button className="ghost-button" onClick={() => void approve(true)} disabled={decisionBusy}>Review</button>
            </div>}
            <details className="more">
              <summary>Details</summary>
              <p>{approval.recommendation}</p>
              <p>Approver: {approval.owner}</p>
              {timing && <p>{Math.round(timing.p_on_time * 100)}% chance it arrives in time, based on {timing.sample_count} past orders.</p>}
            </details>
          </> : <p className="empty">Nothing to decide</p>}
        </section>
      </div>

      <AgentGraph recording={data.recordedAgentRun} onEvidence={setSource}/>

      {!hostedReplayBuild && <BestSupplier/>}

      {data.network && data.network.suppliers.length > 0 && <section className="card map-card">
        <h3>Supply network</h3>
        <SupplyMap network={data.network}/>
      </section>}

      <details className="card agents" open={threadsOpen} onToggle={(event) => setThreadsOpen(event.currentTarget.open)}>
        <summary><h3>Agents</h3><span className="muted">{drafts} emails ready · {reviews} files to check</span></summary>
        {hostedReplayBuild && <div className="actions">
          <a href="https://soony-manti-live.vercel.app/?mail=1" className="ghost-button">Open verified supplier mailbox</a>
        </div>}
        {data.mailHistory && <div className="actions">
          <button className="ghost-button" aria-pressed={!mailView} onClick={() => openMail(false)}>Demo threads</button>
          <button className="ghost-button" aria-pressed={mailView} onClick={() => openMail(true)}>Verified team mailbox</button>
        </div>}
        {mailView && <p className="muted">{data.mailHistory?.status === "ready"
          ? (visibleThreads?.length ? "Read-only history reconciled from team Gmail." : "No verified chaser email found in the team mailbox.")
          : data.mailHistory?.status === "unavailable" ? "Mailbox check unavailable. Previously verified messages remain visible."
          : "Waiting for a read-only mailbox check."}{data.mailHistory?.checkedAt && <> · Checked {etaDate.format(new Date(data.mailHistory.checkedAt))} CET</>}</p>}
        {supplierActions && supplierActions.length > 0 && <SupplierActions actions={supplierActions} select={selectThread} mailView={mailView} onEvidence={setSource}/>}
        <div className="agents-body">
          <div className="thread-list">
            {visibleThreads?.map((thread) => <button key={thread.id} className={thread.id === selectedThread?.id ? "thread selected" : "thread"} onClick={() => selectThread(thread.id)}>
              <strong>{thread.supplier}</strong><span>{thread.status}</span>
            </button>)}
          </div>
          {selectedThread && <div className="thread-detail">
            {selectedThread.messages.map((message, index) => {
              const envelope = message.transport;
              const plan = message.parsed?.reply_plan;
              const status = envelope ? ({
                draft: "Draft",
                attempting: "Sending attempt",
                smtp_accepted: "Accepted by SMTP",
                gmail_sent: "Verified in Gmail Sent",
                dry_run: "Dry-run email",
                failed: "Send failed",
                delivery_uncertain: "Delivery uncertain",
                received: envelope.mode === "simulated" ? "Simulated supplier reply" : "Received in inbox",
              }[envelope.status]) : "Historical message · Transport unverified";
              return <div className={`message ${message.side}`} id={message.id == null ? undefined : `message-${message.id}`} key={message.id ?? index}>
                <span>{status}{message.timestamp && <> · <time dateTime={message.timestamp}>{etaDate.format(new Date(message.timestamp))} CET</time></>}</span>
                <div><strong>{envelope?.from ?? message.sender}</strong>{envelope?.to && <> → {envelope.to}</>}</div>
                {envelope?.subject && <p><strong>{envelope.subject}</strong></p>}
                <p style={{ whiteSpace: "pre-wrap" }}>{message.text}</p>
                {envelope?.messageId && envelope.status !== "draft" && <details>
                  <summary>Message evidence</summary>
                  <p>Message-ID {envelope.messageId}</p>
                  {envelope.inReplyTo && <p>In reply to {envelope.inReplyTo}</p>}
                </details>}
                {plan && <section className="decision-analysis" id={`reply-${plan.id}`} aria-label="Supplier reply decision">
                  <strong>{plan.simulated ? "Simulated decision" : "Reply decision"} · {{
                    proposed: "Proposed", pending: "Pending details", approved: "Approved for follow-up", review: "Under review",
                  }[plan.status]}</strong>
                  <p><a style={{ color: "var(--text)" }} href={`?${mailView ? "mail=1&" : ""}thread=${encodeURIComponent(selectedThread.id)}#reply-${plan.id}`}>Decision {plan.id}</a></p>
                  {plan.shipmentId && plan.reportedEta && <p>{plan.shipmentId} · Reported ETA {etaDate.format(new Date(plan.reportedEta))} CET</p>}
                  {plan.editions?.map((edition) => <p key={edition.title}>
                    {edition.title} median packed · {formatNumber(edition.before)} → {formatNumber(edition.after)}
                    <br/>Upper forecast (p90) · {formatNumber(edition.upperBefore)} → {formatNumber(edition.upperAfter)}
                  </p>)}
                  {plan.offerId && <p>Related recovery option {plan.offerId}</p>}
                  {plan.beforeState && <p>Before · {plan.beforeState}</p>}
                  {plan.afterState && <p>After · {plan.afterState}</p>}
                  {plan.materialEstimate != null && <p>Materials estimate · {euros.format(plan.materialEstimate)}</p>}
                  {plan.evidence && <blockquote>{plan.evidence.join(" · ")}</blockquote>}
                  <p>{plan.nextAction}</p>
                  {plan.editions && <small>Supplier scenario for review. This decision has no purchasing or stock execution.</small>}
                  {message.id && plan.status === "proposed" && !hostedReplayBuild && !mailView && <div className="actions">
                    <button className="ghost-button" disabled={decisionBusy} onClick={() => void approveReply(message)}>Approve follow-up</button>
                  </div>}
                </section>}
              </div>;
            })}
            <div className="actions">
              {!hostedReplayBuild && !mailView && (selectedThread.status === "draft" || selectedThread.status === "loop draft") && <button className="primary-button" onClick={() => void send()} disabled={sendBusy}>{sendBusy ? "Sending…" : data.sync?.mode === "replay" ? "Approve dry-run email" : "Approve & send"}</button>}
              {!hostedReplayBuild && !mailView && data.sync?.mode === "replay" && ["awaiting reply", "reply to verify"].includes(selectedThread.status) &&
                (data.supplierActions?.some((action) => action.case === "game_card" && action.threadId === selectedThread.id) ? <>
                  <button className="ghost-button" onClick={() => void demoReply("on-time")} disabled={replyBusy}>Simulate on-time ETA</button>
                  <button className="ghost-button" onClick={() => void demoReply("delayed")} disabled={replyBusy}>Simulate delayed ETA</button>
                </> : selectedThread.status === "awaiting reply" && <button className="ghost-button" onClick={() => void demoReply()} disabled={replyBusy}>Simulate reply</button>)}
            </div>
          </div>}
        </div>
        <ul className="activity">
          {data.activity.slice(0, 5).map((item) => <li key={item.id}><strong>{item.agent}</strong> {item.action}</li>)}
        </ul>
        <AgentTrace onEvidence={setSource} simulated={data.agents?.mode === "simulated"}/>
      </details>
    </section>
    {behind && <BehindScenes activity={data.activity} recording={data.recordedAgentRun} onClose={() => setBehind(false)} onEvidence={setSource}/>}
    {source && <EvidenceModal source={source} onClose={() => setSource(null)}/>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
