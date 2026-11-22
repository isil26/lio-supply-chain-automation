import { useEffect, useState, type ReactNode } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import { Dialog, Heading, Icon } from "../desk/UI";
import { PriceCeiling, PriceChart, unitEuros, type PricePolicy } from "./ProductPricing";

type Alternative = { id: string; supplier: string; thread_id?: string; quantity?: number; price_eur?: number; total_eur?: number; eta?: string };
type DecisionEvent = { revision?: string; action: string; by: string; at: string | null; note?: string; terms: {
  order_quantity?: number; total_eur?: number; signer?: string; alternatives?: Alternative[];
} };

// T90 mail-agent: every supplier offer in one table, best offer per part on top,
// Approve / Decline per offer. Approve names the PP-07 signer and asks the supplier to
// reserve; Decline sends a polite no-thanks. Both emails go out through the mail agent.

type Deal = {
  address?: string; revision?: string; required_by?: string; thread_id?: string; order_quantity?: number | null; expires_at?: string | null;
  offer_state?: "quoted" | "incomplete" | "late" | "unavailable" | "expired" | "superseded" | "approval_required";
  offer_kind?: "goods" | "freight"; carrier?: string | null; freight_charge?: number | null;
  review_reason?: string;
  drafts?: Partial<Record<"approve" | "decline", { subject: string; body: string }>>;
  awaiting_send?: number;
  catalog_eur?: number | null;
  history?: DecisionEvent[];
  id: string; supplier_id?: string; eta_text?: string | null; supplier: string; material: string; needed: number; quantity: number | null;
  unit_price: number | null; currency: string | null; price_eur: number | null; total_eur: number | null;
  eta: string | null; p_on_time: number | null; score: number | null; best: number; eligible: number;
  proof: string | null; incoterm: string | null; payment_terms: string | null; moq: number | null;
  list_price: number | null; conditions: string | null; excerpt: string | null; signer: string;
  status: "pending" | "approved" | "declined" | "changed" | "superseded"; decided_by: string | null; decided_at: string | null;
};
type Data = { limits?: Record<string, PricePolicy>; deals: Deal[]; best: Deal[]; notes?: Record<string, string>; as_of?: string; gaps?: Record<string, number> };
type English = { english: string | null; summary: string | null; language: string | null; source: string; error?: string };

// One line a manager reads in seconds, built from the offer's own numbers (Gülşah, 22 Nov).
const STATE: Record<string, string> = { late: "Too late for the launch", unavailable: "Cannot supply", incomplete: "Offer is missing details",
  expired: "Offer expired", superseded: "Replaced by a newer offer", approval_required: "Needs approval first" };
function gist(d: Deal) {
  const parts: string[] = [];
  if (d.offer_state && STATE[d.offer_state]) parts.push(STATE[d.offer_state]);
  if (d.quantity != null) parts.push(`${d.quantity.toLocaleString("en-US")} of ${d.needed.toLocaleString("en-US")} units`);
  if (d.offer_kind === "freight") parts.push(`freight by ${d.carrier ?? "carrier"}`);
  else if (d.unit_price != null) parts.push(`${d.unit_price} ${d.currency ?? ""} each${d.price_eur != null && d.currency !== "EUR" ? ` (≈ €${d.price_eur.toFixed(2)})` : ""}`);
  if (d.total_eur != null) parts.push(`total ${eur(d.total_eur)}`);
  if (d.eta || d.eta_text) parts.push(`arrives ${arrives(d)}`);
  if (d.moq) parts.push(`minimum order ${d.moq.toLocaleString("en-US")}`);
  if (d.incoterm) parts.push(d.incoterm);
  if (d.proof) parts.push(`proof: ${d.proof}`);
  return parts.join(" · ") || "No numbers in the reply yet.";
}

// "What they said": English gist first, the English text on request, the original language last.
function Words({ d, example }: { d: Deal; example: boolean }) {
  const [english, setEnglish] = useState<English | "loading" | null>(null);
  const open = () => {
    if (example || english) return;
    setEnglish("loading");
    fetch(`/api/deals/${d.id}/english`, { cache: "no-store" }).then((r) => r.ok ? r.json() : null)
      .then((value) => setEnglish(value ?? { english: null, summary: null, language: null, source: "failed", error: "Translation could not be loaded." }))
      .catch(() => setEnglish({ english: null, summary: null, language: null, source: "failed", error: "Translation could not be loaded." }));
  };
  const e = english && english !== "loading" ? english : null;
  return <details className="offers-words" onToggle={(event) => (event.target as HTMLDetailsElement).open && open()}>
    <summary>What they said</summary>
    <p className="offers-gist"><strong>In short:</strong> {e?.summary ?? gist(d)}</p>
    {english === "loading" && <p className="muted">Translating…</p>}
    {e?.english && e.source === "translated" && <><p className="offers-label">In English{e.language ? ` (from ${e.language})` : ""}</p><p className="offers-email">{e.english}</p></>}
    {e?.english && e.source === "original" && <p className="offers-email">{e.english}</p>}
    {e?.error && <p className="muted">{e.error}</p>}
    {d.excerpt && !(e?.source === "original") && <details className="offers-original"><summary>Original email</summary><p className="offers-email">{d.excerpt}</p></details>}
  </details>;
}

// Suppliers are shown by name and country of origin, e.g. "Hwaseong Memory (South Korea)".
const COUNTRY: Record<string, string> = {
  "SUP-0010": "South Korea", "SUP-0011": "USA", "SUP-0018": "India",
  "SUP-0019": "China", "SUP-0028": "Poland", "SUP-0029": "China",
};
const PRODUCT: Record<string, string> = {
  "CMP-GAM-001": "Game cards", "CMP-GAM-010": "Statues", "CMP-GAM-008": "Art books",
  "CMP-GAM-004": "Sleeves", "CMP-GAM-003": "Game cases", "CMP-GAM-007": "Collector's boxes",
};
function country(d: Deal) {
  const origin = d.supplier_id ? COUNTRY[d.supplier_id] : undefined;
  return origin && origin !== d.supplier ? `${d.supplier} (${origin})` : d.supplier;
}
function product(material: string) { return PRODUCT[material] ?? material; }

const STATUS: Record<Deal["status"], string> = { pending: "Open", approved: "Approved", declined: "Declined", changed: "Changed, decide again", superseded: "Superseded by supplier update" };

function eur(value: number | null) { return value == null ? "–" : `€${Math.round(value).toLocaleString("en-US")}`; }
function when(iso: string | null) {
  if (!iso) return "no date";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
}
function arrives(d: Deal) { return d.eta_text ?? when(d.eta); }
function unit(d: Deal) { return d.unit_price == null ? "Unit price unconfirmed" : `${d.unit_price} ${d.currency ?? ""}`; }

function exampleData(): Data {
  const data = sample as unknown as Data;
  const limits: Record<string, PricePolicy> = {};
  for (const material of new Set(data.deals.map(d => d.material))) {
    const rows = data.deals.filter(d => d.material === material);
    const quotes = rows.flatMap(d => d.price_eur ? [d.price_eur] : []);
    const prices = (quotes.length ? quotes : rows.flatMap(d => d.catalog_eur ? [d.catalog_eur] : [])).sort((a,b) => a-b);
    const top = (prices[prices.length - 1] ?? 0) * 1.5;
    const step = top ? Math.max(.0001, 10 ** (Math.floor(Math.log10(top))-2)) : .01;
    const midpoint = Math.floor(prices.length/2);
    const reference = prices.length ? (prices[midpoint] + prices[Math.floor((prices.length-1)/2)]) / 2 : null;
    limits[material] = {limit:0, actor:null, reference, source:quotes.length?"Supplier quotes":"Supplier catalogue",
      maximum:Number((Math.ceil(Number((top/step).toFixed(9)))*step).toFixed(4)), step};
  }
  return { ...data, limits, best: data.deals.filter((d) => d.best) };
}

type Props = {
  children: ReactNode;
  archive: boolean;
  currentUser?: string | null;
  reviewer: string;
  onReviewer: (name: string) => void;
  openThread: (id: string) => void;
};
export function Offers({ archive, currentUser, reviewer, onReviewer, openThread, children }: Props) {
  // Hosted recording and static builds have no live backend: show a labelled example,
  // and keep Approve / Decline in this browser only (nothing is sent).
  const example = hostedReplayBuild || isStaticMode();
  const sharedAccount = currentUser === "Shared team login";
  const [data, setData] = useState<Data | null>(example ? exampleData() : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [choice, setChoice] = useState<string | null>(null);
  const [reply, setReply] = useState<{id:string; revision?:string; action:"approve"|"decline"|"negotiate"; body:string; recorded?:boolean} | null>(null);
  const [loadError,setLoadError] = useState(false);
  const [emailId, setEmailId] = useState<string | null>(null);
  const [eventKey, setEventKey] = useState<string | null>(null);
  const [switchAccount,setSwitchAccount] = useState(false);
  const [details, setDetails] = useState(false);
  const [tab, setTab] = useState<string | null>(null);

  async function load() {
    try {
      const response = await fetch("/api/deals", { cache: "no-store" });
      if (!response.ok) throw new Error("Offers unavailable");
      setData(await response.json());
      setLoadError(false);
    } catch { setLoadError(true); }
  }

  useEffect(() => {
    if (example) return;
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [example]);

  async function decide(deal: Deal, action: "approve" | "decline") {
    if (example) {
      const status = action === "approve" ? "approved" : "declined";
      setData((old) => {
        if (!old) return old;
        const actor = currentUser || "Practice reviewer";
        const at = new Date().toISOString();
        const alternatives = old.deals.filter(d => d.material === deal.material).map(d => ({
          id:d.id,supplier:d.supplier,quantity:d.quantity??undefined,price_eur:d.price_eur??undefined
        }));
        const deals = old.deals.map(d => d.id !== deal.id ? d : d.awaiting_send ? {...d, awaiting_send:0} :
          {...d, status, decided_at:at, decided_by:actor, history:[{action:status,by:actor,at,terms:{alternatives}}, ...(d.history ?? [])]} as Deal);
        return { ...old, deals, best: deals.filter((d) => d.best) };
      });
      setNote(`Example only: in the live app this ${action === "approve" ? "asks the supplier in " + country(deal) + " to reserve the units (the purchase order needs the " + deal.signer + ")" : "sends the supplier in " + country(deal) + " a polite no-thanks"}. Nothing was sent here.`);
      return;
    }
    setBusy(deal.id + action);
    try {
      const response = await fetch(`/api/deals/${deal.id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: deal.revision, confirmHeld: Boolean(deal.awaiting_send), ...(!currentUser && reviewer.trim() ? {by:reviewer.trim()} : {}) }) });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setNote(error.error ?? "The offer could not be updated. Review the latest terms.");
        await load();
        return;
      }
      setNote(action === "approve"
        ? `Reservation request recorded for ${deal.supplier}. ${deal.offer_kind === "freight" ? "Booking authorization" : "PO signer"} · ${deal.signer}.`
        : `Decline recorded for ${deal.supplier}.`);
      await load();
    } catch {
      setNote("That did not work. Refresh and try again.");
    } finally {
      setBusy(null);
    }
  }

  if (!data) return <><section className="card offers-card"><Heading icon="inbox">{archive ? "Supplier decisions" : "Supplier offers"}</Heading><p role="status">{loadError ? "Supplier offers could not be loaded." : "Loading supplier offers…"}</p>{loadError && <button className="quiet" onClick={()=>void load()}>Retry</button>}</section><aside className="side-stack">{archive ? null : children}</aside></>;
  // Every part from the case keeps its tab; short parts come first, covered ones are marked "covered" (Gülşah, 22 Nov).
  const allMaterials = [...new Set(data.deals.map((d) => d.material))];
  const order = ["CMP-GAM-008","CMP-GAM-001","CMP-GAM-010","CMP-GAM-004","CMP-GAM-003"];
  allMaterials.sort((a,b)=>(order.includes(a)?order.indexOf(a):order.length)-(order.includes(b)?order.indexOf(b):order.length));
  const short = (m: string) => !data.gaps || !(m in data.gaps) || (data.gaps[m] ?? 0) > 0;
  const covered = allMaterials.filter((m) => !short(m));
  const materials = [...allMaterials.filter(short), ...covered];
  const current = tab && materials.includes(tab) ? tab : materials[0];
  const rows = data.deals.filter((d) => d.material === current);
  const best = data.best.filter((d) => d.material === current && d.eligible && ["pending", "changed"].includes(d.status));
  const tabNote = current ? data.notes?.[current] : undefined;

  const selected = rows.find(d=>d.id===choice) ?? best[0] ?? rows[0];
  const draft = reply && selected && reply.id===selected.id && reply.revision===selected.revision ? reply : null;
  const available = selected?.eligible && ["changed","pending"].includes(selected.status);
  const held = selected?.eligible && selected.status === "approved" && selected.awaiting_send;
  function prepare(action:"approve"|"decline"|"negotiate") {
    if (sharedAccount) { setSwitchAccount(true);return; }
    const d = selected;
    const ask = d.offer_kind==="freight" ? "Please compare standard and priority freight, including the first pickup, guaranteed handover and all-in charge."
      : d.offer_state==="late" || d.offer_state==="unavailable" ? "Could you offer an earlier partial lot, local stock or an alternative shipping point? Please confirm quantities, delivery windows and any premium."
      : "Could you offer a split shipment or a better unit price for the required quantity? Please confirm the earliest delivery, minimum order and offer expiry.";
    const body = `Hello ${d.supplier} team,\n\nThank you for the ${product(d.material).toLowerCase()} update. We need ${d.needed.toLocaleString("en-US")} units${d.required_by ? " by "+when(d.required_by):""}. Your reply indicates ${d.quantity?.toLocaleString("en-US") ?? "an unconfirmed quantity"} units, with arrival ${arrives(d)}.\n\n${ask}\n\nKind regards,\nSoony launch team`;
    setReply({id:d.id, revision:d.revision, action, body});
  }
  const policy = data.limits?.[current];
  async function recordNegotiation() {
    if (!draft || !selected || busy) return;
    setBusy(selected.id + "negotiate");
    try {
      if (example) {
        const event = { action:"negotiation started", by:currentUser || "Practice reviewer", at:new Date().toISOString(), note:draft.body,
          terms:{alternatives:rows.map(d => ({id:d.id,supplier:d.supplier,quantity:d.quantity??undefined,price_eur:d.price_eur??undefined}))} };
        setData(old => old && ({...old, deals:old.deals.map(d => d.id===selected.id ? {...d,history:[event,...(d.history ?? [])]} : d)}));
      } else {
        const response = await fetch(`/api/deals/${selected.id}/negotiate`, {method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({revision:selected.revision, message:draft.body, ...(!currentUser ? {by:reviewer.trim()} : {})})});
        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(result.error || "The negotiation could not be recorded.");
        }
        await load();
      }
      setReply(currentDraft => currentDraft === draft ? {...draft,recorded:true} : currentDraft);
      setNote(`Negotiation recorded for ${selected.supplier}. Your draft is ready to send.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "The negotiation could not be recorded.");
    } finally {
      setBusy(null);
    }
  }
  const history = data.deals.flatMap(d => {
    const events: DecisionEvent[] = d.history?.length ? d.history : d.decided_by
      ? [{action:d.status, by:d.decided_by, at:d.decided_at, terms:{}}] : [];
    return events.map((event, index) => ({d, event, key:[d.id, event.at, event.revision, event.action, event.by, index].join("-")}));
  }).sort((a,b) => (b.event.at || "").localeCompare(a.event.at || ""));
  async function saveLimit(value: number) {
    if (!policy) return;
    if (example) {
      setData(old => {
        if (!old) return old;
        const actor = currentUser || "Practice reviewer";
        const pick = !rows.some(d=>d.status==="approved") && best.find(d => d.price_eur != null && d.price_eur > 0 && d.price_eur <= value);
        const deals = old.deals.map(d => pick && pick.id === d.id ? {...d, status:"approved" as const,
          decided_by:actor, awaiting_send:1, decided_at:new Date().toISOString(),
          history:[{action:"approved", by:actor, at:new Date().toISOString(), note:"Automatic practice approval",
            terms:{alternatives:rows.map(r=>({id:r.id,supplier:r.supplier,quantity:r.quantity??undefined,price_eur:r.price_eur??undefined}))}}, ...(d.history ?? [])]} : d);
        return {...old, deals, best:deals.filter(d => d.best), limits:{...old.limits, [current]:{...policy,limit:value,actor}}};
      });
      return;
    }
    const response = await fetch("/api/deals", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({material:current,limit:value,previous:policy.limit,...(!currentUser ? {by:reviewer} : {})})});
    if (!response.ok) {
      const message = await response.json().catch(() => ({}));
      await load();
      throw new Error(message.error || "Could not save this limit.");
    }
    await load();
  }
  const record = history.find(r=>r.key===eventKey && r.d.material===current) ?? history.find(r=>r.d.material===current);
  const threadCount = new Set(rows.map(d=>d.thread_id??d.id)).size;
  const mail = rows.find(d=>d.id===emailId);
  const chooseTab = (id:string) => {setTab(id);setChoice(null);setReply(null);setNote(null);setEventKey(null);};
  return <><section className="card offers-card"><Heading icon="inbox">{archive?"Supplier decisions":"Supplier offers"}</Heading>
    {example && <p className="mini">Practice offers · decisions stay in this browser</p>}
    {loadError && <p role="status">Showing the last loaded offers. <button className="quiet" onClick={()=>void load()}>Retry</button></p>}
    {note && <p className="mail-summary" role="status">{note}</p>}
    {!materials.length ? <p className="empty">Offers appear as suppliers reply.</p> : <>
      <div className="tabs" role="tablist" aria-label="Products">{materials.map((m,i)=><button key={m} role="tab" id={"tab-"+m} aria-controls="product-panel" tabIndex={current===m?0:-1} aria-selected={current===m}
        onClick={()=>chooseTab(m)} onKeyDown={e=>{
          const next=({ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:materials.length-1} as Record<string,number>)[e.key];
          if(next==null)return;
          e.preventDefault();const id=materials[(next+materials.length)%materials.length];chooseTab(id);document.getElementById("tab-"+id)?.focus();
        }}>{product(m)}</button>)}</div>
      <div role="tabpanel" id="product-panel" aria-labelledby={"tab-"+current}>
        {archive ? <div className="recommend">{record ? <><div className="rec-label"><Icon name="history"/>Recorded decision</div>
          <h3>{record.d.supplier} · {record.event.action}</h3><p>{record.event.by} · {when(record.event.at)}</p>
          <button className="quiet" onClick={()=>setDetails(true)}><Icon name="mail"/>Read decision</button></> :
          <><h3>No decisions recorded for this product</h3><p>Reviewed offers and negotiations appear here.</p></>}</div> :
          selected && <div className="recommend"><div className="rec-top"><div className="rec-label"><Icon name="spark"/>{best.some(d=>d.id===selected.id)?"Recommended choice":"Selected offer"}</div>
            {selected.expires_at && <span className="rec-due">{when(selected.expires_at)}</span>}</div>
            <h3>{selected.supplier}</h3><p>{selected.review_reason || selected.conditions || tabNote || gist(selected)}</p>
            <div className="rec-cost"><b>{selected.total_eur!=null?eur(selected.total_eur):unit(selected)}</b>
              {selected.total_eur!=null && <small>{(selected.order_quantity??selected.quantity)?.toLocaleString("en-US")} × {unit(selected)} per unit</small>}</div>
            {!available && (held || selected.decided_by) && <p>{held?"Automatically approved · email awaiting review":STATUS[selected.status]}{selected.decided_by && " · "+selected.decided_by}</p>}
            <div className="decision-buttons"><button className="btn" disabled={(!available&&!held)||!!busy} onClick={()=>prepare("approve")}>{held?"Review supplier email":"Approve"}</button>
              <button className="outline-btn" disabled={!available||!!busy} onClick={()=>prepare("decline")}>Decline</button>
              <button className="outline-btn" disabled={!!busy||selected.status==="superseded"} onClick={()=>prepare("negotiate")}>Negotiate</button></div></div>}
        <div className="offers-heading"><b>Supplier emails</b><small>{threadCount} {threadCount===1?"thread":"threads"}</small></div>
        {rows.map(d=>{
          const body=<><span className="vendor-avatar">{d.supplier.split(/\s+/).slice(0,2).map(w=>w[0]).join("")}</span>
            <span className="offer-info"><strong>{d.supplier}</strong><span>{d.quantity==null?"Quantity unconfirmed":d.quantity.toLocaleString("en-US")+" available"} · {unit(d)}</span></span></>;
          return <div className={"offer-row "+(selected?.id===d.id?"picked":"")} key={d.id}>
            {rows.length>1 && !archive ? <button className="offer-pick" aria-pressed={selected?.id===d.id} onClick={()=>{setChoice(d.id);setReply(null);setNote(null);}}><span className="radio-dot"/>{body}</button> : body}
            <button className="email-button" aria-label={"Read email from "+d.supplier} onClick={()=>setEmailId(d.id)}><Icon name="mail"/></button></div>;
        })}
        {!archive && policy && <PriceCeiling key={current+":"+policy.limit} policy={policy} product={product(current)} save={saveLimit} readOnly={sharedAccount}/>}
      </div></>}
  </section><aside className="side-stack">{archive ? <section className="card"><Heading icon="history" count={history.length}>Decision history</Heading>
    <div className="deadline-list" tabIndex={0} aria-label="Decision history">{history.map(r=>
      <button className="deadline-item" key={r.key} aria-pressed={record?.key===r.key} onClick={()=>{chooseTab(r.d.material);setEventKey(r.key);}}>
        <span className="deadline-icon"><Icon name="history"/></span><span className="deadline-copy"><b>{product(r.d.material)} · {r.event.action}</b><small>{r.event.by} · {r.d.supplier}</small></span>
        {r.event.at && <span className="due">{when(r.event.at)}</span>}</button>)}{!history.length && <p className="empty">No saved decisions yet.</p>}</div></section> :
    <>{children}{rows.length>0 && <PriceChart rows={rows} product={product(current)}/>}</>}</aside>
  {!archive && switchAccount && <Dialog title="Sign in to review offers" label="Supplier decision" close={()=>setSwitchAccount(false)}>
    <p className="modal-p">Use your individual account so the decision is recorded in your name.</p>
    <form className="dialog-actions" action="/logout" method="post"><button className="btn">Switch account</button></form></Dialog>}
  {mail && <Dialog title={mail.supplier} label="Supplier email" close={()=>setEmailId(null)}>
    <p className="mail-summary">{gist(mail)}</p>{mail.excerpt && <p className="draft-body">{mail.excerpt}</p>}
    <Words d={mail} example={example}/>{mail.thread_id && <div className="dialog-actions"><button className="btn" onClick={()=>{setEmailId(null);openThread(mail.thread_id!);}}>Open email thread</button></div>}</Dialog>}
  {archive && details && record && <Dialog title={record.d.supplier} label="Recorded decision" close={()=>setDetails(false)}>
    <p className="mini">{record.event.action} · {record.event.by} · {when(record.event.at)}</p>
    {record.event.note && <p className="mail-summary draft-body">{record.event.note}</p>}
    {record.event.terms.total_eur!=null && <p>{eur(record.event.terms.total_eur)} total</p>}
    {(record.event.terms.alternatives??[]).map(a=><div className="offer-row" key={a.id}><div className="offer-info"><strong>{a.supplier}</strong><span>{a.quantity?.toLocaleString("en-US")??"Unconfirmed"} units · {a.price_eur==null?"Price unconfirmed":unitEuros(a.price_eur)+"/unit"}</span></div>
      {a.thread_id && <button className="email-button" aria-label={"Read email from "+a.supplier} onClick={()=>{setDetails(false);openThread(a.thread_id!);}}><Icon name="mail"/></button>}</div>)}</Dialog>}
  {!archive && draft && selected && <Dialog label={product(current)+" · "+draft.action} title="Review email draft" close={()=>setReply(null)}><div className="editor">
        {draft.action==="negotiate" ? <><label>Message to {selected.supplier}<textarea rows={6} maxLength={1000} readOnly={draft.recorded || !!busy} value={draft.body} onChange={e=>setReply({...draft,body:e.target.value})}/></label>
          {!draft.recorded && !example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          {!draft.recorded ? <button className="btn" disabled={!!busy || !draft.body.trim() || (!example && !currentUser && !reviewer.trim())} onClick={()=>void recordNegotiation()}>Record negotiation</button> :
          example || !selected.address ? <small className="muted">Copy this draft into your supplier correspondence.</small> :
          <a className="outline-btn" href={`mailto:${encodeURIComponent(selected.address)}?subject=${encodeURIComponent("Re: "+product(selected.material))}&body=${encodeURIComponent(draft.body)}`}>Open in email app</a>}</> : <>
          <p><strong>To</strong> · {selected.address || selected.supplier}</p>
          <strong>{selected.drafts?.[draft.action]?.subject ?? product(selected.material)}</strong>
          <p className="supplier-email-preview">{selected.drafts?.[draft.action]?.body ?? (example
            ? draft.action === "approve" ? `Could you hold ${selected.order_quantity ?? selected.quantity} units of ${product(selected.material)} without charge and confirm the hold expiry? A separate purchase order is required before dispatch.` : "Thank you for the offer. We will not proceed with it for now."
            : "Reload the offer to preview the current supplier message.")}</p>
          {!example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          <button className="btn" disabled={(!available && !held) || !!busy || (!example && (!selected.drafts?.[draft.action] || (!currentUser && !reviewer.trim())))} onClick={()=>{void decide(selected,draft.action as "approve"|"decline");setReply(null);}}>{example?"Record practice decision":"Confirm and queue email"}</button></>}
          <button className="quiet" disabled={!!busy} onClick={()=>setReply(null)}>{draft.recorded ? "Close" : "Cancel"}</button>
  </div></Dialog>}</>;
}
