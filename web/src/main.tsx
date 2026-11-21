import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { dashboardApi, type DashboardData } from "./api";
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
    arrow: <><path d="M5 12h14"/><path d="m14 7 5 5-5 5"/></>
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
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff / 3600000) % 24);
  const minutes = Math.floor((diff / 60000) % 60);
  const seconds = Math.floor((diff / 1000) % 60);
  return <div className="countdown" aria-label="Countdown to launch">
    {[
      [days, "DAYS"], [hours, "HRS"], [minutes, "MIN"], [seconds, "SEC"]
    ].map(([value, label], i) => <React.Fragment key={label as string}>
      {i > 0 && <span className="countdown-separator">:</span>}
      <div><strong>{String(value).padStart(2, "0")}</strong><small>{label}</small></div>
    </React.Fragment>)}
  </div>;
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [dark, setDark] = useState(true);
  const [threadId, setThreadId] = useState("supplier-a");
  const [dropVisible, setDropVisible] = useState(true);
  const [approved, setApproved] = useState(false);

  useEffect(() => {
    dashboardApi.getDashboard().then(setData);
  }, []);

  if (!data) return <div className="loading">Loading launch state…</div>;
  const selectedThread = data.threads.find((thread) => thread.id === threadId) ?? data.threads[0];

  return <main className={dark ? "theme-dark" : "theme-light"}>
    <aside className="rail">
      <div className="brand-mark">S<span>O</span></div>
      <nav>
        <button className="nav-button active" title="Control room"><Icon name="grid"/></button>
        <button className="nav-button" title="Risks"><Icon name="risk"/></button>
        <button className="nav-button" title="Supplier threads"><Icon name="thread"/></button>
        <button className="nav-button" title="Approvals"><Icon name="approval"/></button>
      </nav>
      <button className="theme-button" onClick={() => setDark((value) => !value)} title="Toggle theme">
        <Icon name={dark ? "sun" : "moon"}/>
      </button>
    </aside>

    <section className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">SOONY OPERATIONS / GLOBAL LAUNCH</p>
          <h1>Launch Control Room</h1>
        </div>
        <div className="launch-status">
          <span className="live-dot"></span>
          <div><strong>Grand Heist 6</strong><small>22 NOV · 20:00 CET · DC-HAM</small></div>
        </div>
      </header>

      {dropVisible && <div className="drop-banner">
        <div className="drop-icon"><Icon name="arrow"/></div>
        <div><strong>{data.drop.title}</strong><span>{data.drop.detail}</span></div>
        <time>{data.drop.time}</time>
        <button onClick={() => { setDropVisible(false); void dashboardApi.dismissDrop(); }} aria-label="Dismiss data drop">×</button>
      </div>}

      <div className="clock-strip">
        <div>
          <p className="section-label">TIME TO SHIP</p>
          <Countdown deadline={data.launch.deadline}/>
        </div>
        <div className="readiness-cards">
          {data.readiness.map((item) => <article className="readiness-card" key={item.edition}>
            <div className="edition-head"><span>{item.edition}</span><em className={item.tone}>{item.status}</em></div>
            <div className="percent-row"><strong>{item.percent}<small>%</small></strong><span>{item.packed.toLocaleString("en-US")} / {item.target.toLocaleString("en-US")}</span></div>
            <div className="progress"><i className={item.tone} style={{ width: `${item.percent}%` }}/></div>
          </article>)}
        </div>
      </div>

      <div className="content-grid">
        <section className="panel risks-panel">
          <div className="panel-heading"><div><p className="section-label">WHAT BREAKS FIRST</p><h2>Top risks</h2></div><button className="text-button">View all <Icon name="arrow"/></button></div>
          <div className="risk-list">
            {data.risks.map((risk) => <article className="risk-row" key={risk.rank}>
              <span className={`rank rank-${risk.severity.toLowerCase()}`}>{String(risk.rank).padStart(2, "0")}</span>
              <div className="risk-main"><strong>{risk.component}</strong><span>{risk.supplier}</span></div>
              <div className="shortfall"><strong>{risk.shortfall}</strong><span>Shortfall</span></div>
              <button className="evidence" title={risk.evidence.join(" · ")}>Evidence <b>{risk.evidence.length}</b></button>
            </article>)}
          </div>
        </section>

        <section className="panel activity-panel">
          <div className="panel-heading"><div><p className="section-label">AGENT NETWORK</p><h2>Activity</h2></div><span className="running"><i></i> Running</span></div>
          <div className="activity-list">
            {data.activity.map((item) => <article className="activity-row" key={item.id}>
              <span className={`activity-mark ${item.type}`}>{item.type === "sent" ? "→" : item.type === "warning" ? "!" : "◆"}</span>
              <div><strong>{item.agent}</strong><p>{item.action}</p></div><time>{item.time}</time>
            </article>)}
          </div>
        </section>

        <section className="panel threads-panel">
          <div className="panel-heading"><div><p className="section-label">SUPPLIER OPS</p><h2>Threads</h2></div><button className="icon-button" aria-label="Open thread">+</button></div>
          <div className="thread-layout">
            <div className="thread-list">
              {data.threads.map((thread) => <button key={thread.id} className={thread.id === threadId ? "thread-item selected" : "thread-item"} onClick={() => setThreadId(thread.id)}>
                <span className="avatar">{thread.initials}</span><div><strong>{thread.supplier}</strong><p>{thread.subject}</p></div><em>{thread.status}</em>
              </button>)}
            </div>
            <div className="thread-detail">
              <div className="thread-detail-head"><div><strong>{selectedThread.supplier}</strong><span>{selectedThread.subject}</span></div><em>{selectedThread.status}</em></div>
              <div className="messages">
                {selectedThread.messages.map((message, index) => <div className={`message ${message.side}`} key={index}>
                  <span>{message.sender}</span><p>{message.text}</p><time>{message.time}</time>
                </div>)}
              </div>
            </div>
          </div>
        </section>

        <section className="approval-panel">
          <div className="approval-head">
            <div><p className="section-label">HUMAN DECISION</p><h2>{data.approval.title}</h2></div>
            <span>{data.approval.owner}</span>
          </div>
          <div className="recommendation">
            <div className="recommendation-copy"><span className="recommended">Recommended</span><p>{data.approval.recommendation}</p></div>
            <div className="approval-price"><small>Aditional cost</small><strong>€{data.approval.price.toLocaleString("en-US")}</strong></div>
          </div>
          <div className="decision-meta">
            <div><span>Impact</span><strong>{data.approval.impact}</strong></div>
            <div><span>Residual risk</span><strong>{data.approval.risk}</strong></div>
            <div><span>Authorization</span><strong>{data.approval.threshold}</strong></div>
          </div>
          <div className="decision-actions">
            <span>{data.approval.deadline}</span>
            {approved ? <button className="approve-button approved" disabled><Icon name="check"/> Approved</button> :
              <><button className="review-button">Request review</button><button className="approve-button" onClick={() => { setApproved(true); void dashboardApi.approveAction("split-air-freight"); }}>Approve & release <Icon name="arrow"/></button></>}
          </div>
        </section>
      </div>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
