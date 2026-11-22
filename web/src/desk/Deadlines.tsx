import { useState } from "react";
import { dashboardApi, recordDeskAction, type Approval, type DashboardData, type DeskAction, type MailPreview, type Source } from "../api";
import { Dialog, Heading, Icon } from "./UI";
import { displayDate } from "./Forecast";

type Workflow = { finish: string; decline: string; approve?: string; evidence?: string };
const workflows: Record<string, Workflow> = {
  partial: {finish:"Record supplier follow-up", decline:"Pass on this proposal", approve:"Approve reservation request", evidence:"Read the offer"},
  alternate: {finish:"Record stock check", decline:"Decline stock request", approve:"Approve stock enquiry", evidence:"Check supplier terms"},
  air: {finish:"Record freight quote review", decline:"Decline freight enquiry", approve:"Approve freight enquiry", evidence:"Check freight terms"},
  quality: {finish:"Record inspection follow-up", decline:"Dismiss inspection proposal", evidence:"Read inspection report"},
  pickup: {finish:"Confirm pickup verified", decline:"Dismiss pickup check", evidence:"Check shipment record"},
  receipt: {finish:"Confirm receipt verified", decline:"Dismiss receipt check", evidence:"Check receiving record"},
  inbound: {finish:"Record dock-slot follow-up", decline:"Decline dock proposal", approve:"Approve dock request", evidence:"Check shipment record"},
  short_ship_balance: {finish:"Record balance check", decline:"Dismiss balance check", evidence:"Inspect receipt"},
  packplan: {finish:"Record allocation review", decline:"Decline allocation proposal", approve:"Approve packing priority", evidence:"Inspect packing plan"},
  release_gate: {finish:"Record disposition follow-up", decline:"Dismiss follow-up", evidence:"Check release evidence"},
  ppap_release: {finish:"Record qualification follow-up", decline:"Dismiss follow-up", evidence:"Review qualification"},
  claims: {finish:"Record claim review", decline:"Decline claim review", evidence:"Read contract evidence"},
  supplier_chaser: {finish:"Record supplier follow-up", decline:"Dismiss follow-up"},
};
const defaultWorkflow: Workflow = {finish:"Record review", decline:"Dismiss proposal", approve:"Approve request"};
const followUp: Record<string,string> = {
  quality:"Request inspection sign-off", release_gate:"Request a disposition", ppap_release:"Request written release",
  pickup:"Ask for gate-out confirmation", receipt:"Request proof of receipt", inbound:"Request a dock window",
  packplan:"Request allocation sign-off", priority:"Request allocation sign-off", claims:"Request claim assessment",
};
const date = new Intl.DateTimeFormat("en-GB", {timeZone:"Europe/Berlin",weekday:"short",hour:"2-digit",minute:"2-digit"});
const due = (time?: string) => time && Number.isFinite(Date.parse(time)) ? (time.length === 10 ? displayDate(time,false) : date.format(Date.parse(time))) : "No deadline";
const agentBySource: Record<string,string> = {recovery:"Supplier Recovery", options:"Decision Copilot", release_gate:"Approvals",
  claims:"Decision Copilot", packplan:"Readiness Engine", triage:"Triage", supplier_chaser:"Supplier Chaser"};

function legacyActions(options: Approval[]): DeskAction[] {
  return options.filter(o=>!o.status || o.status==="pending" || o.status==="blocked").map(o=>({
    id:o.id,optionId:o.id,title:o.title,task:o.kind,source:"options",status:"pending",owner:o.owner,
    approver:o.approvalMode?.approver,why:o.recommendation,dueAt:o.latest_action ?? o.deadline,evidence:o.evidence ?? []
  }));
}

export function Deadlines({data, practice, refresh, onThread, onEvidence}: {
  data: DashboardData; practice: boolean; refresh: () => Promise<void>; onThread: (id: string) => void; onEvidence: (source: Source) => void;
}) {
  const [id, select] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [reviewed, setReviewed] = useState<string[]>([]);
  const [note,setNote] = useState("");
  const [name,setName] = useState("");
  const [preview,setPreview] = useState<MailPreview | null>(null);
  const options = data.options ?? (data.approval ? [data.approval] : []);
  const rows = data.actions ?? legacyActions(options);
  const pending = rows.filter(a => a.status==="pending" && !reviewed.includes(a.id))
    .sort((a,b)=>(Date.parse(a.dueAt ?? "") || Infinity)-(Date.parse(b.dueAt ?? "") || Infinity));
  const action = pending.find(a=>a.id===id);
  const option = options.find(o=>o.id===action?.optionId);
  const task = action?.task ?? option?.kind ?? action?.source ?? "";
  const workflow = workflows[task==="priority" ? "packplan" : task] ?? defaultWorkflow;
  const reviewMail = action && followUp[task] && data.teamReviewEmail && !practice ?
    "mailto:"+encodeURIComponent(data.teamReviewEmail)+"?subject="+encodeURIComponent(`For ${action.owner} · ${action.title}`)+
    "&body="+encodeURIComponent(`For ${action.approver || action.owner},\n\n${action.why}\n\nPlease confirm the next step and the supporting evidence.\n\n${data.currentUser || ""}`) : null;
  const canApprove = option && (!option.status || option.status==="pending") && option.approvalMode?.mode!=="NEVER" && workflow.approve;
  const agent = agentBySource[action?.source ?? ""] ?? "Decision Copilot";
  const actor = data.currentUser || (practice ? "Practice reviewer" : name.trim());
  const evidence = action?.evidence?.find((item): item is Source=>typeof item==="object" && !!(item.file || item.source_file || item.quote));
  function open(row: DeskAction) {
    select(row.id);setNote("");setPreview(null);setError("");setFeedback("");
  }
  async function submit(outcome: "approve" | "done" | "dismiss") {
    if (!action || busy) return;
    setBusy(true);setError("");
    try {
      if (outcome==="approve" && !practice && !preview) {
        const mail = await dashboardApi.previewDecision?.(action.optionId!);
        if (!mail) throw new Error("The approval preview is unavailable. Please try again.");
        setPreview(mail);
        return;
      }
      let result = outcome==="approve" ? "Approval recorded" : outcome==="dismiss" ? "Proposal declined" : "Follow-up recorded";
      if (practice) setReviewed(previous=>[...previous,action.id]);
      else if (outcome==="approve") {
        const res = await dashboardApi.approveDecision(action.optionId!, actor);
        if (res.status !== "approved") throw new Error("Approval is still pending. Refresh to review the latest evidence.");
        result = res.effect?.lines?.join(" ") || result;
      } else {
        await recordDeskAction(action.id,outcome,actor,note.trim() || (outcome==="done" ? workflow.finish : workflow.decline));
      }
      select(null);
      setFeedback((practice ? "Simulated · " : "")+result);
      if (!practice) await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "The decision could not be recorded."); }
    finally {setBusy(false);}
  }
  return <section className="card"><Heading icon="clock" count={pending.length}>Decision deadlines</Heading>
    {feedback && <p className="decision-feedback" role="status">{feedback}</p>}
    <div className="deadline-list" role="region" aria-label="Upcoming decisions" tabIndex={0}>{pending.map(r=>
      <button className="deadline-item" key={r.id} onClick={()=>open(r)}>
        <span className="deadline-icon"><Icon name="clock"/></span><span className="deadline-copy"><b>{r.title}</b><small>{r.owner}</small></span>
        <span className="due">{due(r.dueAt)}</span>
      </button>)}{!pending.length && <p className="empty">No decisions due.</p>}</div>
    {action && <Dialog title={action.title} label={practice || data.sync?.mailMode==="dry-run" ? "Simulated decision · test case" : "Decision deadline"} close={()=>{if(!busy)select(null);}}>
      <p className="mini">{action.approver || action.owner}{action.dueAt && " · "+displayDate(action.dueAt)}</p>
      <p className="decision-context">{action.why}</p>
      <div className="handoff-links">
        {reviewMail && <a className="outline-btn" href={reviewMail} title={"Via the launch team · "+data.teamReviewEmail}><Icon name="mail"/>{followUp[task]}</a>}
        {action.contact && <a className="outline-btn" href={"tel:"+action.contact.phone.replace(/[^+0-9]/g,"")}>Call {action.contact.name} · {action.contact.phone}</a>}
        {action.threadId && <button className="outline-btn" onClick={()=>onThread(action.threadId!)}><Icon name="mail"/>Read supplier reply</button>}
        {evidence && <button className="outline-btn" onClick={()=>onEvidence(evidence)}>{workflow.evidence || "Inspect source"}</button>}
        <a className="quiet" href={"#agents?"+new URLSearchParams({agent})} onClick={()=>select(null)}><Icon name="network"/>View {agent} activity</a>
      </div>
      {preview ? <section className="editor"><p>{preview.note}</p>{preview.body && <><strong>{preview.subject}</strong><p className="draft-body">{preview.body}</p></>}
        <button className="btn" disabled={busy} onClick={()=>void submit("approve")}>{preview.mode==="send" || preview.mode==="internal" ? "Confirm approval and send" : "Confirm approval"}</button>
        <button className="quiet" disabled={busy} onClick={()=>setPreview(null)}>Back</button></section> :
        <div className="editor">
          {!practice && !data.currentUser && <label>Reviewed by<input value={name} maxLength={80} onChange={e=>setName(e.target.value)}/></label>}
          <label>Follow-up or decline note (optional)<textarea rows={2} maxLength={500} value={note} onChange={e=>setNote(e.target.value)}/></label>
          <div className="decision-buttons">
            {canApprove && <button className="btn" disabled={busy || !actor} onClick={()=>void submit("approve")}>{workflow.approve}</button>}
            {(practice || data.actions) && <><button className={canApprove ? "outline-btn" : "btn"} disabled={busy || !actor} onClick={()=>void submit("done")}>{workflow.finish}</button>
            <button className="outline-btn" disabled={busy || !actor} onClick={()=>void submit("dismiss")}>{workflow.decline}</button></>}
          </div>
        </div>}
      {error && <p role="alert">{error}</p>}</Dialog>}
  </section>;
}
