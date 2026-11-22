import { useState } from "react";
import { ActionList } from "../ActionList";
import { dashboardApi, type DashboardData, type Source } from "../api";
import { Dialog, Heading, Icon } from "./UI";
import { displayDate } from "./Forecast";

const shortDeadline = (value: string) => {
  if (!value) return "Unconfirmed";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Intl.DateTimeFormat("en-GB", {
    timeZone:"Europe/Berlin", weekday:"short", hour:"2-digit", minute:"2-digit"
  }).format(timestamp) : value;
};

export function Deadlines({data, practice, refresh, onThread, onEvidence}: {
  data: DashboardData; practice: boolean; refresh: () => Promise<void>; onThread: (id: string) => void; onEvidence: (source: Source) => void;
}) {
  const [selected, select] = useState<{id:string} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState<string[]>([]);
  const options = data.options ?? (data.approval ? [data.approval] : []);
  const reviews = data.recoveryApprovals ?? [];
  const rows = options.filter(o => !o.status || o.status === "pending" || (o.status === "blocked" && o.approvalMode)).map(o => {
    const r = reviews.find(r => r.id===o.id);
    return {id:o.id, title:r?.title??o.title, owner:r?.approver??o.approvalMode?.approver??o.owner, due:r?.dueAt??o.latest_action??o.deadline};
  });
  for (const r of reviews) if (!options.some(o=>o.id===r.id)) rows.push({id:r.id,title:r.title,owner:r.approver,due:r.dueAt??""});
  const pending = rows.filter(r=>!reviewed.includes(r.id)).sort((a,b)=>(Date.parse(a.due)||Infinity)-(Date.parse(b.due)||Infinity));
  const current = pending.find(r=>r.id===selected?.id);
  async function decide(id:string, review:boolean, by?:string) {
    setBusy(true);
    setError("");
    try {
      if (practice) setReviewed(old=>[...old,id]);
      else {
        if (review) await dashboardApi.reviewDecision(id);
        else await dashboardApi.approveDecision(id, data.currentUser??by);
        await refresh();
      }
      select(null);
    } catch (e) { setError(e instanceof Error?e.message:"The decision could not be updated."); }
    finally { setBusy(false); }
  }
  return <section className="card"><Heading icon="clock" count={pending.length}>Decision deadlines</Heading>
    <div className="deadline-list" role="region" aria-label="Upcoming decisions" tabIndex={0}>{pending.map(r=>
      <button className="deadline-item" key={r.id} onClick={()=>{setError("");select({id:r.id});}}>
        <span className="deadline-icon"><Icon name="clock"/></span><span className="deadline-copy"><b>{r.title}</b><small>{r.owner}</small></span>
        <span className="due">{shortDeadline(r.due)}</span>
      </button>)}{!pending.length && <p className="empty">No decisions due.</p>}</div>
    {current && <Dialog title={current.title} label="Decision deadline" close={()=>select(null)}>
      <p className="mini">{current.due ? displayDate(current.due) : "Time unconfirmed"}</p>
      <ActionList detailOnly requestedAction={selected} options={options.filter(o=>o.id===current.id)} reviews={reviews.filter(r=>r.id===current.id)}
        costOf={id=>{const r=data.readiness.find(r=>r.productId===id);return r?.missCostEur??r?.stdCostEur??null;}} busy={busy} readOnly={false}
        onDecide={decide} onEvidence={onEvidence} autoLimit={0} autoIds={data.autoApproved??[]}
        onOpenThread={onThread} onPreview={practice ? undefined : dashboardApi.previewDecision} practiceNote={practice?"Simulated decision · test case":undefined}/>
      {error && <p role="alert">{error}</p>}</Dialog>}
  </section>;
}
