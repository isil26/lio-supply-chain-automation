import { useEffect, useState, type ReactNode } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import "./offers.css";
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
  "CMP-GAM-004": "Cover sleeves", "CMP-GAM-003": "Card cases", "CMP-GAM-007": "Collector's boxes",
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

  if (!data) return <><section className="card offers"><h3>Supplier offers</h3><p role="status">{loadError ? "Supplier offers could not be loaded." : "Loading supplier offers…"}</p>{loadError && <button className="ghost-button" onClick={()=>void load()}>Retry</button>}</section><aside className="decision-side">{children}</aside></>;
  // Every part from the case keeps its tab; short parts come first, covered ones are marked "covered" (Gülşah, 22 Nov).
  const allMaterials = [...new Set(data.deals.map((d) => d.material))];
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
  const history = rows.flatMap(d => {
    const events: DecisionEvent[] = d.history?.length ? d.history : d.decided_by
      ? [{action:d.status, by:d.decided_by, at:d.decided_at, terms:{}}] : [];
    return events.map((event, index) => ({d, event, key:d.id + "-" + index}));
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
  return <><section className="card offers" aria-labelledby="offers-title"><h3 id="offers-title">{archive ? "Supplier decisions" : "Supplier offers"}</h3>
    {example && <small className="muted">Practice offers · decisions stay in this browser</small>}
    {loadError && <p role="status">Showing the last loaded offers. <button className="link-button" onClick={()=>void load()}>Retry</button></p>}
    {note && <p className="offers-note" role="status">{note}</p>}
    {!materials.length ? <p className="empty">Offers appear as suppliers reply.</p> : <>
      <div className="offers-tabs" aria-label="Products">{materials.map(m=><button key={m} className={current===m?"is-on":""} aria-pressed={current===m}
        onClick={()=>{setTab(m);setChoice(null);setReply(null);setNote(null);}}>{product(m)}</button>)}</div>
      {archive && <div className="offer-history">
        <h4>Recorded decisions</h4>
        {history.length ? history.map(({d,event,key}) => <article className="supplier-event" key={key}>
          <strong>{d.supplier} · {event.action}</strong><p>{event.by} {event.at && " · " + when(event.at)}</p>
          {(event.terms.order_quantity != null || event.terms.total_eur != null) && <p>
            {[event.terms.order_quantity != null && event.terms.order_quantity.toLocaleString("en-US")+" units",
              event.terms.total_eur != null && eur(event.terms.total_eur)+" total"].filter(Boolean).join(" · ")}
          </p>}
          {event.note && <p>{event.note}</p>}
          {event.terms.alternatives?.length ? <details open><summary>Options at decision time</summary>
            {event.terms.alternatives.map(a => <div className="historical-option" key={a.id}><span>{a.supplier} {a.id===d.id && <b>· {event.action}</b>}</span>
              <small>{a.quantity?.toLocaleString("en-US") ?? "Unconfirmed"} units · {a.price_eur ? unitEuros(a.price_eur)+"/unit" : "Price unconfirmed"}{a.eta && " · "+when(a.eta)}</small>
              {a.thread_id && <button className="link-button" onClick={()=>openThread(a.thread_id!)}>Open supplier email</button>}</div>)}</details>
            : <p className="muted">The original comparison was not recorded.</p>}
        </article>) : <p className="empty">No decision recorded for this product.</p>}
      </div>}
      {archive && <h4>Supplier offers on file</h4>}
      {selected && <div className="offer-recommendation offer-selected" key={selected.id}>
        <small>{archive ? "Offer on file" : best.some(d=>d.id===selected.id) ? "Recommended choice" : "Selected offer"}</small>
        <strong>{country(selected)}</strong>
        <p>{product(current)} · {unit(selected)}{selected.total_eur != null && " · " + eur(selected.total_eur) + " total"}</p>
        {tabNote && <p>{tabNote}</p>}
        {selected.conditions && <p>{selected.conditions}</p>}
        {(selected.excerpt || selected.quantity!=null) && <Words key={selected.id+selected.revision} d={selected} example={example}/>}
        {selected.thread_id && <button className="link-button" onClick={()=>openThread(selected.thread_id!)}>Open supplier email</button>}
        <details><summary>Offer terms and evidence</summary><p>{gist(selected)}</p><p>{[selected.carrier,selected.payment_terms,selected.signer&&"Signer · "+selected.signer,selected.required_by&&"Required by "+when(selected.required_by),selected.expires_at&&"Expires "+when(selected.expires_at),selected.p_on_time!=null&&"On time "+Math.round(selected.p_on_time*100)+"%",selected.list_price!=null&&"Contract price "+selected.list_price].filter(Boolean).join(" · ")}</p>
        {selected.history?.map((h,i)=><p key={i}>{when(h.at)} · {h.by} · {h.action} · {eur(h.terms.total_eur??null)}</p>)}</details>
        {!available && <p className="muted">{held ? "Automatically approved · email awaiting your review" : selected.review_reason || STATUS[selected.status]}{selected.decided_by && " · "+selected.decided_by}</p>}
        {!archive && sharedAccount && <form method="post" action="/logout" className="offers-actions">
          <p>Use your individual account to record an offer decision.</p><button className="ghost-button" type="submit">Switch account</button>
        </form>}
        {!archive && !sharedAccount && <div className="offers-actions">
          <button className="primary-button" disabled={(!available && !held) || !!busy} onClick={()=>prepare("approve")}>{held ? "Review supplier email" : "Approve"}</button>
          <button className="ghost-button" disabled={!available || !!busy} onClick={()=>prepare("decline")}>Decline</button>
          <button className="ghost-button" disabled={!!busy || selected.status==="superseded"} onClick={()=>prepare("negotiate")}>Negotiate</button>
        </div>}
        {!archive && draft && <section className="reply-review"><h4>{draft.action==="negotiate"?"Negotiation draft":draft.action==="approve"?"Review reservation request":"Review decline"}</h4>
        {draft.action==="negotiate" ? <><label>Message to {selected.supplier}<textarea rows={6} maxLength={1000} readOnly={draft.recorded || !!busy} value={draft.body} onChange={e=>setReply({...draft,body:e.target.value})}/></label>
          {!draft.recorded && !example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          {!draft.recorded ? <button className="primary-button" disabled={!!busy || !draft.body.trim() || (!example && !currentUser && !reviewer.trim())} onClick={()=>void recordNegotiation()}>Record negotiation</button> :
          example || !selected.address ? <small className="muted">Copy this draft into your supplier correspondence.</small> :
          <a className="ghost-button" href={`mailto:${encodeURIComponent(selected.address)}?subject=${encodeURIComponent("Re: "+product(selected.material))}&body=${encodeURIComponent(draft.body)}`}>Open in email app</a>}</> : <>
          <p><strong>To</strong> · {selected.address || selected.supplier}</p>
          <strong>{selected.drafts?.[draft.action]?.subject ?? product(selected.material)}</strong>
          <p className="supplier-email-preview">{selected.drafts?.[draft.action]?.body ?? (example
            ? draft.action === "approve" ? `Could you hold ${selected.order_quantity ?? selected.quantity} units of ${product(selected.material)} without charge and confirm the hold expiry? A separate purchase order is required before dispatch.` : "Thank you for the offer. We will not proceed with it for now."
            : "Reload the offer to preview the current supplier message.")}</p>
          {!example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          <button className="primary-button" disabled={(!available && !held) || !!busy || (!example && (!selected.drafts?.[draft.action] || (!currentUser && !reviewer.trim())))} onClick={()=>{void decide(selected,draft.action as "approve"|"decline");setReply(null);}}>{example?"Record practice decision":"Confirm and queue email"}</button></>}
          <button className="link-button" disabled={!!busy} onClick={()=>setReply(null)}>{draft.recorded ? "Close" : "Cancel"}</button>
        </section>}
      </div>}
      <div className="supplier-list" aria-label="Compare supplier offers">{rows.map(d => <button key={d.id} aria-pressed={selected?.id===d.id}
        onClick={()=>{setChoice(d.id);setReply(null);setNote(null);}}>
        <span><b>{country(d)}</b><small>{d.quantity?.toLocaleString("en-US") ?? "Unknown"} units · {arrives(d)}</small></span>
        <span>{best.some(offer=>offer.id===d.id) ? "Recommended" : STATUS[d.status]}</span></button>)}</div>
      {!archive && policy && <PriceCeiling key={current + ":" + policy.limit} policy={policy} product={product(current)} save={saveLimit} readOnly={sharedAccount}/>}
    </>}
  </section><aside className="decision-side">{children}
    {!archive && rows.length > 0 && <section className="card"><PriceChart rows={rows} product={product(current)} limit={policy?.limit ?? 0}/></section>}
  </aside></>;
}
