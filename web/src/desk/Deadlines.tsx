import { useEffect, useRef, useState } from "react";
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

type Outcome = "approve" | "done" | "dismiss";

function readReviewed(key: string): string[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
  } catch {return [];}
}

export function Deadlines({data, practice, practiceKey, refresh, onThread, onEvidence}: {
  data: DashboardData; practice: boolean; practiceKey: string; refresh: () => Promise<void>; onThread: (id: string) => void; onEvidence: (source: Source) => void;
}) {
  const [id, select] = useState<string | null>(null);
  const [busy, setBusy] = useState<Outcome | "preview" | null>(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const storageKey = "manti-reviewed-"+JSON.stringify([practiceKey, data.currentUser, data.launch.deadline]);
  const [reviewed, setReviewed] = useState<string[]>(()=>practice ? readReviewed(storageKey) : []);
  const [approved, setApproved] = useState<string[]>([]);
  const [note,setNote] = useState("");
  const [name,setName] = useState("");
  const [preview,setPreview] = useState<MailPreview | null>(null);
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const approveButton = useRef<HTMLButtonElement>(null);
  const status = useRef<HTMLParagraphElement>(null);
  const rawOptions = data.options ?? (data.approval ? [data.approval] : []);
  const options = rawOptions.map(option => practice && !option.id
    ? {...option, id: JSON.stringify([option.title, option.owner, option.deadline])} : option);
  const rows = data.actions ?? legacyActions(options);
  const pending = rows.filter(a => a.status==="pending" && !reviewed.includes(a.id))
    .sort((a,b)=>(Date.parse(a.dueAt ?? "") || Infinity)-(Date.parse(b.dueAt ?? "") || Infinity));
  const action = pending.find(a=>a.id===id);
  const option = options.find(o=>o.id===action?.optionId);
  const task = action?.task ?? option?.kind ?? action?.source ?? "";
  const workflow = workflows[task==="priority" ? "packplan" : task] ?? defaultWorkflow;
  const reviewMail = action && followUp[task] && data.teamReviewEmail && !practice ?
    "mailto:"+encodeURIComponent(data.teamReviewEmail).replace("%40","@")+"?subject="+encodeURIComponent(`For ${action.owner} · ${action.title}`)+
    "&body="+encodeURIComponent(`For ${action.approver || action.owner},\n\n${action.why}\n\nPlease confirm the next step and the supporting evidence.\n\n${data.currentUser || ""}`) : null;
  const canApprove = option && !approved.includes(option.id) && (!option.status || option.status==="pending") && option.approvalMode?.mode!=="NEVER" && workflow.approve;
  const simulated = practice || data.sync?.mailMode !== "live";
  const agent = agentBySource[action?.source ?? ""] ?? "Decision Copilot";
  const actor = data.currentUser || (practice ? "Practice reviewer" : name.trim());
  const evidence = action?.evidence?.find((item): item is Source=>!!item && typeof item==="object" && !!(item.file || item.source_file || item.quote));
  useEffect(()=>{if (preview) previewHeading.current?.focus();},[preview]);
  useEffect(()=>{if (feedback) status.current?.focus();},[feedback]);
  useEffect(()=>{
    if (id && !action && !busy) {
      select(null);
      setFeedback("This decision is no longer pending. The deadline list has been updated.");
    }
  },[id,action,busy]);
  function open(row: DeskAction) {
    select(row.id);setNote("");setPreview(null);setError("");setFeedback("");
  }
  async function submit(outcome: Outcome) {
    if (!action || busy || !actor || (outcome==="approve" && !canApprove)) return;
    const loadingPreview = outcome==="approve" && !practice && !preview;
    setBusy(loadingPreview ? "preview" : outcome);setError("");
    try {
      if (loadingPreview) {
        const mail = await dashboardApi.previewDecision?.(action.optionId!);
        if (!mail) throw new Error("The approval preview is unavailable. Please try again.");
        setPreview(mail);
        return;
      }
      let result = outcome==="approve" ? "Approval recorded" : outcome==="dismiss" ? "Proposal declined" : "Follow-up recorded";
      if (!practice && outcome==="approve") {
        const res = await dashboardApi.approveDecision(action.optionId!, actor);
        if (!res.ok || res.status !== "approved") throw new Error("Approval is still pending. Review the latest evidence.");
        result = res.effect?.lines?.join(" ") || result;
        setApproved(previous=>[...previous,action.optionId!]);
      } else {
        if (outcome!=="approve" && !practice) {
          const res = await recordDeskAction(action.id,outcome,actor,note.trim() || (outcome==="done" ? workflow.finish : workflow.decline));
          if (!res.ok) throw new Error("The decision could not be recorded. Try again.");
        }
        const next = [...reviewed,action.id];
        setReviewed(next);
        if (practice) {
          try {sessionStorage.setItem(storageKey,JSON.stringify(next));} catch {}
        }
      }
      select(null);
      setFeedback((simulated ? "Simulated · " : "")+action.title+" — "+result);
      if (!practice) void refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "The decision could not be recorded."); }
    finally {setBusy(null);}
  }
  return <section className="card"><Heading icon="clock" count={pending.length}>Decision deadlines</Heading>
    {feedback && <p className="decision-feedback" role="status" tabIndex={-1} ref={status}>{feedback}</p>}
    <div className="deadline-list" role="region" aria-label="Upcoming decisions" tabIndex={0}>{pending.map(r=>
      <button className="deadline-item" key={r.id} aria-haspopup="dialog" disabled={!!busy} onClick={()=>open(r)}>
        <span className="deadline-icon"><Icon name="clock"/></span><span className="deadline-copy"><b>{r.title}</b><small>{r.owner}</small></span>
        <span className="due">{due(r.dueAt)}</span>
      </button>)}{!pending.length && <p className="empty">No decisions due.</p>}</div>
    {action && <Dialog title={action.title} label={simulated ? "Simulated decision · test case" : "Decision deadline"} dismissible={!busy} close={()=>select(null)}>
      <p className="mini">{action.approver || action.owner}{action.dueAt && " · "+displayDate(action.dueAt)}
        {action.dueAt?.includes("T") && Date.parse(action.dueAt)<Date.now() && " · Deadline passed"}</p>
      <p className="decision-context">{action.why}</p>
      {option && (option.approvalMode?.mode==="NEVER" || option.status==="blocked") && <p className="mail-summary">Approval blocked. {option.approvalMode?.reason}</p>}
      {option?.status==="expired" && <p className="mail-summary">This approval has expired.</p>}
      {(option?.status==="approved" || (option && approved.includes(option.id))) && <p className="mini">Approval recorded. Follow-up is still open.</p>}
      {!busy && <div className="handoff-links">
        {reviewMail && <a className="outline-btn" href={reviewMail} title={"Via the launch team · "+data.teamReviewEmail}><Icon name="mail"/>{followUp[task]} (email draft)</a>}
        {action.contact && <a className="outline-btn" href={"tel:"+action.contact.phone.replace(/[^+0-9]/g,"")}>Call {action.contact.name} · {action.contact.phone}</a>}
        {action.threadId && <button className="outline-btn" onClick={()=>onThread(action.threadId!)}><Icon name="mail"/>Read supplier reply</button>}
        {evidence && <button className="outline-btn" onClick={()=>onEvidence(evidence)}>{workflow.evidence || "Inspect source"}</button>}
        <a className="quiet" href={"#agents?"+new URLSearchParams({agent})} onClick={()=>select(null)}><Icon name="network"/>View {agent} activity</a>
      </div>}
      {preview ? <section className="editor">
        <h3 ref={previewHeading} tabIndex={-1}>Review approval</h3>
        {canApprove ? <><p>{simulated && (preview.mode==="send" || preview.mode==="internal") ? "The test case simulates delivery of this message." : preview.note}</p>{preview.to && <p>To {preview.to}</p>}{preview.body && <><strong>{preview.subject}</strong><p className="draft-body">{preview.body}</p></>}
          <button className="btn" disabled={!!busy} onClick={()=>void submit("approve")}>{simulated ? "Confirm simulated approval" : preview.mode==="send" || preview.mode==="internal" ? "Confirm approval and send" : "Confirm approval"}</button></>
          : <p role="status">This option changed. Review the current decision before continuing.</p>}
        <button className="quiet" disabled={!!busy} onClick={()=>{setPreview(null);setError("");requestAnimationFrame(()=>approveButton.current?.focus());}}>Back</button></section> :
        <div className="editor">
          {!practice && !data.currentUser && <label>Reviewed by (required)<input value={name} required disabled={!!busy} maxLength={80} onChange={e=>setName(e.target.value)}/></label>}
          {(practice || data.actions) && <label>Follow-up or decline note (optional)<textarea rows={2} disabled={!!busy} maxLength={500} value={note} onChange={e=>setNote(e.target.value)}/></label>}
          <div className="decision-buttons">
            {canApprove && <button className="btn" ref={approveButton} disabled={!!busy || !actor} onClick={()=>void submit("approve")}>{workflow.approve}</button>}
            {(practice || data.actions) && <><button className={canApprove ? "outline-btn" : "btn"} disabled={!!busy || !actor} onClick={()=>void submit("done")}>{workflow.finish}</button>
            <button className="outline-btn" disabled={!!busy || !actor} onClick={()=>void submit("dismiss")}>{workflow.decline}</button></>}
          </div>
        </div>}
      {busy && <p role="status">{busy==="preview" ? "Loading approval preview…" : "Recording decision…"}</p>}
      {error && <p role="alert">{error}</p>}</Dialog>}
  </section>;
}
