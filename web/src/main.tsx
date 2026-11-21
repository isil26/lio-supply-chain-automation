import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  dashboardApi,
  isStaticMode,
  type DashboardData,
  type Risk,
  type Source,
  type SupplierThread,
} from "./api";
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
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const diff = Math.max(0, new Date(deadline).getTime() - now);
  const values = [
    [Math.floor(diff / 86400000), "DAYS"],
    [Math.floor(diff / 3600000) % 24, "HRS"],
    [Math.floor(diff / 60000) % 60, "MIN"],
    [Math.floor(diff / 1000) % 60, "SEC"],
  ];
  return <div className="countdown" aria-label="Countdown to launch">
    {values.map(([value, label], index) => <React.Fragment key={String(label)}>
      {index > 0 && <span className="countdown-separator">:</span>}
      <div><strong>{String(value).padStart(2, "0")}</strong><small>{label}</small></div>
    </React.Fragment>)}
  </div>;
}

function formatNumber(value: number | undefined) {
  return typeof value === "number" ? value.toLocaleString("en-US") : "—";
}

function EvidenceModal({ source, onClose }: { source: Source; onClose: () => void }) {
  const file = source.source_file ?? source.file ?? "";
  const [raw, setRaw] = useState("");
  useEffect(() => {
    if (!file || isStaticMode()) return;
    dashboardApi.getSource(file).then(setRaw).catch(() => setRaw(""));
  }, [file]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="evidence-modal" role="dialog" aria-modal="true" aria-label="Source evidence" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><p className="section-label">SOURCE EVIDENCE</p><h2>{file}</h2></div><button onClick={onClose} aria-label="Close">×</button></header>
      <div className="evidence-location">{source.page ? `Page ${source.page}` : source.row ? `Row ${source.row}` : "Source location"}{source.confidence != null ? ` · ${Math.round(source.confidence * 100)}% confidence` : ""}</div>
      {source.quote && <blockquote>{source.quote}</blockquote>}
      {!isStaticMode() && raw ? <a className="source-link" href={`/api/source/${file.split("/").map(encodeURIComponent).join("/")}`} target="_blank" rel="noreferrer">Open original source <Icon name="arrow"/></a> : null}
    </section>
  </div>;
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(true);
  const [threadId, setThreadId] = useState("");
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
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const selectedThread = useMemo<SupplierThread | undefined>(() => {
    if (!data) return undefined;
    return data.threads.find((thread) => thread.id === threadId) ?? data.threads[0];
  }, [data, threadId]);

  if (!data) return <main className="loading-screen"><div className="loader"/><strong>{error || "Loading launch state…"}</strong>{error && <button onClick={() => void refresh()}>Retry</button>}</main>;

  const approval = data.approval;
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

  const demoReply = async () => {
    if (!selectedThread) return;
    setReplyBusy(true);
    try {
      await dashboardApi.replyThread(
        selectedThread.id,
        "Confirmed: we can prepare the requested allocation and follow the documented approval route.",
      );
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

  const runSync = async () => {
    setSyncBusy(true);
    try {
      await dashboardApi.sync();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync could not start");
    } finally {
      setSyncBusy(false);
    }
  };

  return <main className={dark ? "theme-dark" : "theme-light"}>
    <aside className="rail">
      <div className="brand-mark">S<span>O</span></div>
      <nav>
        <button className="nav-button active" title="Control room"><Icon name="grid"/></button>
        <button className="nav-button" title="Risks" onClick={() => document.querySelector(".risks-panel")?.scrollIntoView({ behavior: "smooth" })}><Icon name="risk"/></button>
        <button className="nav-button" title="Supplier threads" onClick={() => document.querySelector(".threads-panel")?.scrollIntoView({ behavior: "smooth" })}><Icon name="thread"/></button>
        <button className="nav-button" title="Approvals" onClick={() => document.querySelector(".approval-panel")?.scrollIntoView({ behavior: "smooth" })}><Icon name="approval"/></button>
      </nav>
      <button className="theme-button" onClick={() => setDark((value) => !value)} title="Toggle theme"><Icon name={dark ? "sun" : "moon"}/></button>
    </aside>

    <section className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">SOONY OPERATIONS / GLOBAL LAUNCH</p><h1>Launch Control Room</h1></div>
        {isStaticMode() && <button className="static-badge" onClick={() => void resetDemo()} title="Reset demo">
          Static replay snapshot · {meta.exported ?? "frozen"}
        </button>}
        {isStaticMode() && <button className="reset-demo" onClick={() => void resetDemo()}>Reset demo</button>}
        <div className="launch-status"><span className="live-dot"/><div><strong>{data.launch.name}</strong><small>{data.launch.location} · 22 NOV · 20:00 CET</small></div></div>
      </header>

      {error && <div className="error-banner">{error}<button onClick={() => setError("")}>×</button></div>}
      {dropVisible && data.drop && <div className="drop-banner">
        <div className="drop-icon"><Icon name="arrow"/></div>
        <div><strong>{data.drop.title}</strong><span>{data.drop.detail}</span></div>
        <button className="sync-button" onClick={() => void runSync()} disabled={syncBusy}>{syncBusy ? "Syncing…" : isStaticMode() ? "Release data drop" : "Process drop"}</button>
        <button onClick={() => { setDropVisible(false); void dashboardApi.dismissDrop(); }} aria-label="Dismiss data drop">×</button>
      </div>}

      <div className="clock-strip">
        <div><p className="section-label">TIME TO SHIP</p><Countdown deadline={data.launch.deadline}/></div>
        <div className="readiness-cards">
          {data.readiness.map((item) => {
            const p10 = item.p10 ?? item.packed;
            const p50 = item.p50 ?? item.packed;
            const p90 = item.p90 ?? item.packed;
            const scaleMax = Math.max(item.target, p90);
            const left = (p10 / scaleMax) * 100;
            const width = Math.max(2, ((p90 - p10) / scaleMax) * 100);
            const median = (p50 / scaleMax) * 100;
            return <article className="readiness-card" key={item.edition}>
              <div className="edition-head"><span>{item.edition}</span><em className={item.tone}>{item.status}</em></div>
              <div className="percent-row"><strong>{Math.round((item.probability ?? 0) * 100)}<small>%</small></strong><span>P(on time)</span></div>
              <div className="range-meta"><span>{formatNumber(p10)}</span><b>p10 / p50 / p90</b><span>{formatNumber(p90)}</span></div>
              <div className="range-bar"><i style={{ left: `${left}%`, width: `${width}%` }}/><b style={{ left: `${median}%` }}/></div>
              <div className="packed-meta"><span>{formatNumber(item.packed)} packed</span><span>{formatNumber(item.target)} target</span></div>
            </article>;
          })}
        </div>
      </div>

      <div className="content-grid">
        <section className="panel risks-panel">
          <div className="panel-heading"><div><p className="section-label">WHAT BREAKS FIRST</p><h2>Top risks</h2></div><span className="panel-count">{data.risks.length} exceptions</span></div>
          <div className="risk-list">
            {data.risks.slice(0, 5).map((risk) => {
              const evidence = riskEvidence(risk);
              return <article className="risk-row" key={`${risk.rank}-${risk.id ?? risk.component}`}>
                <span className={`rank rank-${risk.severity.toLowerCase()}`}>{String(risk.rank).padStart(2, "0")}</span>
                <div className="risk-main"><strong>{risk.component}</strong><span>{risk.supplier}</span></div>
                <div className="truth-compare">
                  <div><small>SAP says</small><strong>{risk.onHand != null ? `${formatNumber(risk.onHand)} usable` : "No gap"}</strong></div>
                  <div><small>Reality</small><strong className={risk.severity === "Critical" ? "critical-text" : ""}>{risk.shortfall === "—" ? "No verified gap" : `${risk.shortfall} short`}</strong></div>
                </div>
                <button className="evidence" disabled={!evidence} onClick={() => evidence && setSource(evidence)}>Evidence <b>{risk.sources?.length ?? risk.evidence.length}</b></button>
              </article>;
            })}
          </div>
        </section>

        <section className="panel activity-panel">
          <div className="panel-heading"><div><p className="section-label">AGENT NETWORK</p><h2>Live activity</h2></div><span className="running"><i/> Running</span></div>
          <div className="activity-list">
            {data.activity.slice(0, 8).map((item) => <article className="activity-row" key={item.id}>
              <span className={`activity-mark ${item.type}`}>{item.type === "sent" ? "→" : item.type === "warning" ? "!" : "◆"}</span>
              <div><strong>{item.agent}</strong><p>{item.action}</p></div><time>{item.time}</time>
            </article>)}
          </div>
        </section>

        <section className="panel threads-panel">
          <div className="panel-heading"><div><p className="section-label">SUPPLIER OPS</p><h2>Threads</h2></div><span className="panel-count">{data.threads.length} open</span></div>
          <div className="thread-layout">
            <div className="thread-list">
              {data.threads.map((thread) => <button key={thread.id} className={thread.id === selectedThread?.id ? "thread-item selected" : "thread-item"} onClick={() => setThreadId(thread.id)}>
                <span className="avatar">{thread.initials}</span><div><strong>{thread.supplier}</strong><p>{thread.subject}</p></div><em>{thread.status}</em>
              </button>)}
            </div>
            {selectedThread && <div className="thread-detail">
              <div className="thread-detail-head"><div><strong>{selectedThread.supplier}</strong><span>{selectedThread.subject}</span></div><em>{selectedThread.status}</em></div>
              <div className="messages">
                {selectedThread.messages.map((message, index) => <div className={`message ${message.side}`} key={index}>
                  <span>{message.sender}</span><p>{message.text}</p>{message.time && <time>{message.time}</time>}
                </div>)}
              </div>
              <div className="thread-actions">
                <span className={`workflow-state ${selectedThread.status.split(" ").join("-")}`}>{selectedThread.status === "draft" ? "Draft" : selectedThread.status === "awaiting reply" ? "Sent" : selectedThread.status}</span>
                {selectedThread.status === "draft" && <button className="approve-button" onClick={() => void send()} disabled={sendBusy}>{sendBusy ? "Sending…" : "Approve & send"}<Icon name="arrow"/></button>}
                {(selectedThread.status === "awaiting reply" || selectedThread.status === "sent") && <button className="review-button" onClick={() => void demoReply()} disabled={replyBusy}>{replyBusy ? "Replying…" : "Demo reply"}</button>}
              </div>
            </div>}
          </div>
        </section>

        <section className="approval-panel">
          <div className="approval-head"><div><p className="section-label">HUMAN DECISION</p><h2>{approval?.title ?? "No action awaiting approval"}</h2></div>{approval && <span>{approval.owner}</span>}</div>
          {approval ? <>
            <div className="recommendation">
              <div className="recommendation-copy"><span className="recommended">Recommended</span><p>{approval.recommendation}</p></div>
              <div className="approval-price"><small>Estimated cost</small>{approval.price == null ? <strong>Pending</strong> : <strong>€{approval.price.toLocaleString("en-US")}</strong>}</div>
            </div>
            <div className="decision-meta"><div><span>Impact</span><strong>{approval.impact}</strong></div><div><span>Residual risk</span><strong>{approval.risk}</strong></div><div><span>Authorization</span><strong>{approval.threshold}</strong></div></div>
            <div className="decision-actions">
              <span>{approval.status ? `Status: ${approval.status}` : "Buyer approval required"}</span>
              <button className="review-button" onClick={() => void approve(true)} disabled={decisionBusy}>Request review</button>
              <button className="approve-button" onClick={() => void approve(false)} disabled={decisionBusy || approval.status === "approved"}>{approval.status === "approved" ? <><Icon name="check"/> Approved</> : <>Approve <Icon name="arrow"/></>}</button>
            </div>
          </> : <div className="empty-approval">Live options will appear after the next readiness evaluation.</div>}
        </section>
      </div>
    </section>
    {source && <EvidenceModal source={source} onClose={() => setSource(null)}/>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
