import { useEffect, useRef, useState, type ReactNode } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import { EmailBody } from "../EmailBody";
import { nativePrice, rateSource, type ExchangeRates } from "../currency";
import { Dialog, Heading, Icon } from "../desk/UI";
import { PriceCeiling, unitEuros, type PricePolicy } from "./ProductPricing";

type Alternative = { id: string; supplier: string; thread_id?: string; quantity?: number; price_eur?: number; total_eur?: number; eta?: string };
type DecisionEvent = { revision?: string; action: string; by: string; at: string | null; note?: string; terms: {
  order_quantity?: number; total_eur?: number; signer?: string; alternatives?: Alternative[];
} };

// T90 mail-agent: every supplier offer in one table, best offer per part on top,
// Approve / Decline per offer. Approve names the PP-07 signer and asks the supplier to
// reserve; Decline sends a polite no-thanks. Both emails go out through the mail agent.

type Decision = "approve" | "decline";
type Deal = {
  previous_price?: { amount: number; currency: string; at: string; thread_id: string };
  catalog_price?: {amount:number;currency:string};
  followup?: {state:string;detail:string;missing:string[];nextAt?:string;lastAt?:string;thread?:string};
  request?: {status:string; purpose:string};
  address?: string; revision?: string; required_by?: string; thread_id?: string; order_quantity?: number | null; expires_at?: string | null;
  offer_state?: "quoted" | "incomplete" | "late" | "unavailable" | "expired" | "superseded" | "approval_required";
  offer_kind?: "goods" | "freight"; carrier?: string | null; freight_charge?: number | null; freight_currency?:string|null;
  review_reason?: string;
  drafts?: Partial<Record<"approve" | "decline", { subject: string; body: string }>>;
  english_excerpt?: string;
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
type Data = { exchangeRates?: ExchangeRates; limits?: Record<string, PricePolicy>; deals: Deal[]; best: Deal[]; notes?: Record<string, string>; as_of?: string; gaps?: Record<string, number> };
type Reply = {deal: Deal; action: Decision | "negotiate"; body: string};
let practiceSession: Data | null = null;
type English = { original?: string; english: string | null; supplierText?: string | null; supplierLanguage?: string; summary: string | null; language: string | null; source: string; error?: string };

async function postDecision(path: string, payload: object) {
  const response = await fetch(path, {
    method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload),
  }).catch(() => { throw new Error("Connection interrupted. Check the latest offers before trying again."); });
  const result = await response.json().catch(() => null);
  if (!response.ok || result?.ok !== true) {
    throw new Error(result?.error || "The server could not confirm the update. Check the latest offers and try again.");
  }
  return result;
}

// One line a manager reads in seconds, built from the offer's own numbers (Gülşah, 22 Nov).
const STATE: Record<string, string> = { late: "Too late for the launch", unavailable: "Cannot supply", incomplete: "Offer is missing details",
  expired: "Offer expired", superseded: "Replaced by a newer offer", approval_required: "Needs approval first" };
function gist(d: Deal, rates?:ExchangeRates) {
  const parts: string[] = [];
  if (d.offer_state && STATE[d.offer_state]) parts.push(STATE[d.offer_state]);
  if (d.quantity != null) parts.push(`${d.quantity.toLocaleString("en-US")} of ${d.needed.toLocaleString("en-US")} units`);
  if (d.offer_kind === "freight") parts.push(`freight by ${d.carrier ?? "carrier"}`);
  else if (d.unit_price != null) parts.push(nativePrice(d.unit_price,d.currency ?? "",rates)+" each");
  if (d.total_eur != null) parts.push(`total ${eur(d.total_eur)}`);
  if (d.eta || d.eta_text) parts.push(`arrives ${arrives(d)}`);
  if (d.moq) parts.push(`minimum order ${d.moq.toLocaleString("en-US")}`);
  if (d.incoterm) parts.push(d.incoterm);
  if (d.proof) parts.push(`proof: ${d.proof}`);
  return parts.join(" · ") || "No numbers in the reply yet.";
}

function EmailPreview({ deal, example }: { deal: Deal; example: boolean }) {
  const [result, setResult] = useState<English | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (example || !deal.excerpt) return;
    const controller = new AbortController();
    setResult(null);
    fetch(`/api/deals/${deal.id}/english`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error();
        const translation = await response.json();
        if (!controller.signal.aborted) setResult(translation);
      }).catch(() => {
        if (!controller.signal.aborted) setResult({english:null, summary:null, language:null, source:"failed"});
      });
    return () => controller.abort();
  }, [deal.id, deal.revision, deal.excerpt, example, attempt]);
  if (!deal.excerpt) return <p className="modal-p">No supplier message is available.</p>;
  const sourceText = result?.original ?? deal.excerpt;
  const english = example ? deal.english_excerpt ?? deal.excerpt : result?.english;
  return <EmailBody original={sourceText} english={english} supplierLanguage={result?.supplierLanguage}
    supplierText={result?.supplierText} loading={!example && !result}
    onRetry={example ? undefined : () => setAttempt(n => n + 1)}/>;
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

const decisionLabels = {approved: "Approved", declined: "Declined", negotiating: "Negotiating"} as const;
function eventTone(action: string) {
  if (action === "negotiation started") return "negotiating";
  if (action === "approved" || action === "declined") return action;
}

function quoteTone(deal: Deal) {
  if (deal.status === "superseded") return;
  const latest = deal.history?.find(event => event.revision === deal.revision && eventTone(event.action));
  if (latest?.action === "negotiation started" &&
      (!deal.decided_at || (latest.at && Date.parse(latest.at) >= Date.parse(deal.decided_at)))) return "negotiating";
  return eventTone(deal.status);
}

function eur(value: number | null) { return value == null ? "–" : `€${Math.round(value).toLocaleString("en-US")}`; }
function when(iso: string | null) {
  if (!iso) return "no date";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
}
function arrives(d: Deal) { return d.eta_text ?? when(d.eta); }
function priceDisplay(d: Deal, rates?:ExchangeRates) {
  if (d.offer_kind === "freight") return {value:d.freight_charge == null ? "Awaiting quote" : nativePrice(d.freight_charge,d.currency ?? "",rates), source:"Freight charge", currency:d.currency};
  if (d.unit_price != null) return {value:nativePrice(d.unit_price,d.currency ?? "",rates)+" / unit", source:"Current supplier quote", currency:d.currency};
  if (d.previous_price) return {value:nativePrice(d.previous_price.amount,d.previous_price.currency,rates)+" / unit",
    source:`Earlier supplier quote · ${when(d.previous_price.at)}`, currency:d.previous_price.currency};
  if (d.catalog_price) return {value:nativePrice(d.catalog_price.amount,d.catalog_price.currency,rates)+" / unit", source:"Supplier catalogue", currency:d.catalog_price.currency};
  if (d.catalog_eur != null) return {value:`${unitEuros(d.catalog_eur)} / unit`, source:"Supplier catalogue",currency:"EUR"};
  return {value:"Awaiting quote", source:"Supplier pricing",currency:null};
}

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
  const [data, setData] = useState<Data | null>(() => example ? practiceSession ?? exampleData() : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{material:string; message:ReactNode} | null>(null);
  const [choice, setChoice] = useState<string | null>(null);
  const [draft, setReply] = useState<Reply | null>(null);
  const [draftError, setDraftError] = useState("");
  const [loadError,setLoadError] = useState(false);
  const [retrying,setRetrying] = useState(false);
  const [emailId, setEmailId] = useState<string | null>(null);
  const [eventKey, setEventKey] = useState<string | null>(null);
  const [switchAccount,setSwitchAccount] = useState(false);
  const [details, setDetails] = useState<{d:Deal; event:DecisionEvent} | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const previousArchive = useRef(archive);

  const requestNumber = useRef(0);
  async function load(manual = false) {
    const request = ++requestNumber.current;
    if (manual) setRetrying(true);
    try {
      const response = await fetch("/api/deals", { cache: "no-store" });
      if (!response.ok) throw new Error("Offers unavailable");
      const latest = await response.json();
      if (!Array.isArray(latest?.deals) || !Array.isArray(latest.best)) throw new Error("Invalid offers response");
      if (request !== requestNumber.current) return;
      setData(latest);
      setLoadError(false);
    } catch { if (request === requestNumber.current) setLoadError(true); }
    finally { if (request === requestNumber.current) setRetrying(false); }
  }

  useEffect(() => {
    if (example) return;
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => { window.clearInterval(timer); requestNumber.current++; };
  }, [example]);
  useEffect(() => { if (example && data) practiceSession = data; }, [example, data]);
  useEffect(() => {
    if (previousArchive.current === archive) return;
    previousArchive.current = archive;
    setReply(null); setEmailId(null); setDetails(null); setSwitchAccount(false); setNote(null);
  }, [archive]);

  async function decide(deal: Deal, action: Decision, message: string) {
    setDraftError("");
    if (example) {
      const status: Deal["status"] = action === "approve" ? "approved" : "declined";
      setData((old) => {
        if (!old) return old;
        const actor = currentUser || "Practice reviewer";
        const at = new Date().toISOString();
        const alternatives = old.deals.filter(d => d.material === deal.material).map(d => ({
          id:d.id,supplier:d.supplier,quantity:d.quantity??undefined,price_eur:d.price_eur??undefined
        }));
        const deals = old.deals.map(d => {
          if (d.id !== deal.id) return d;
          if (d.awaiting_send) return {...d, awaiting_send:0};
          const event = {revision:deal.revision, action:status, by:actor, at, note:message, terms:{alternatives}};
          const history = [event, ...(d.history ?? [])];
          return {...d, status, decided_at:at, decided_by:actor, history};
        });
        return { ...old, deals, best: deals.filter((d) => d.best) };
      });
      setReply(null);
      setNote({material:deal.material, message:`Practice decision recorded for ${country(deal)}.`});
      return;
    }
    setBusy(deal.id + action);
    try {
      const result = await postDecision(`/api/deals/${deal.id}/${action}`, {
        revision: deal.revision, message,
        confirmHeld: Boolean(deal.awaiting_send), by:currentUser || reviewer.trim(),
      });
      setData(old => {
        if (!old) return old;
        const deals = old.deals.map(d => {
          if (d.id !== deal.id || d.revision !== deal.revision) return d;
          return result.deal ? {...d,...result.deal} : d;
        });
        return {...old, deals, best:deals.filter(d=>d.best)};
      });
      setReply(null);
      setNote({material:deal.material, message:result.deal?.awaiting_send
        ? `Approval recorded for ${deal.supplier}. Review the supplier email to queue it.`
        : action === "approve" ? `Reservation request queued for ${deal.supplier}. ${deal.offer_kind === "freight" ? "Booking authorization" : "PO signer"} · ${deal.signer}.`
        : `Decline email queued for ${deal.supplier}.`});
      await load();
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : "The server could not confirm the decision. Your draft is still here.");
      await load();
    } finally {
      setBusy(null);
    }
  }

  const retryButton = <button className="quiet" disabled={retrying} onClick={()=>void load(true)}>{retrying ? "Retrying…" : "Retry"}</button>;
  if (!data) return <><section className="card offers-card"><Heading icon="inbox">{archive ? "Supplier decisions" : "Supplier offers"}</Heading><p role="status">{loadError ? "Supplier offers could not be loaded." : "Loading supplier offers…"}</p>{loadError && retryButton}</section><aside className="side-stack">{archive ? null : children}</aside></>;
  // Every part from the case keeps its tab; short parts come first, covered ones are marked "covered" (Gülşah, 22 Nov).
  const allMaterials = [...new Set(data.deals.map((d) => d.material))];
  const order = ["CMP-GAM-008","CMP-GAM-001","CMP-GAM-010","CMP-GAM-004","CMP-GAM-003"];
  allMaterials.sort((a,b)=>(order.includes(a)?order.indexOf(a):order.length)-(order.includes(b)?order.indexOf(b):order.length));
  const short = (m: string) => (data.gaps?.[m] ?? 0) > 0;
  const covered = allMaterials.filter((m) => !short(m));
  const materials = [...allMaterials.filter(short), ...covered];
  const current = tab && materials.includes(tab) ? tab : materials[0];
  const rows = data.deals.filter((d) => d.material === current);
  const rankedIds = new Set(data.best.map(d => d.id));
  const recommended = rows.filter(d => rankedIds.has(d.id) && d.eligible && ["pending", "changed", "approved"].includes(d.status));
  const best = recommended.filter(d => d.status !== "approved");
  const recommendation = (d: Deal) => recommended.some(r => r.id === d.id)
    ? "Recommended" + (recommended.length > 1 && d.required_by ? " · due " + when(d.required_by) : "") : null;
  const tabNote = current ? data.notes?.[current] : undefined;

  const selected = rows.find(d=>d.id===choice) ?? best[0]
    ?? rows.find(d=>d.eligible && ["pending","changed"].includes(d.status))
    ?? rows.find(d=>d.followup && ["due","queued","sent","scheduled"].includes(d.followup.state)) ?? rows[0];
  const selectedTone = selected && quoteTone(selected);
  const openOffer = selected && ["changed","pending"].includes(selected.status);
  const available = openOffer && !!selected.eligible && (example || !!selected.drafts?.approve);
  const canDecline = openOffer && (example || !!selected.drafts?.decline);
  const held = selected?.eligible && selected.status === "approved" && selected.awaiting_send && (example || !!selected.drafts?.approve);
  const latestDraftOffer = draft && data.deals.find(d=>d.id===draft.deal.id);
  const staleDraft = draft && (!latestDraftOffer || latestDraftOffer.revision !== draft.deal.revision
    || latestDraftOffer.status !== draft.deal.status || latestDraftOffer.awaiting_send !== draft.deal.awaiting_send
    || latestDraftOffer.status === "superseded"
    || ((draft.action === "approve" || draft.action === "decline") && !example && !latestDraftOffer.drafts?.[draft.action]));
  function prepare(action:Decision|"negotiate") {
    if (sharedAccount) { setSwitchAccount(true);return; }
    const d = selected;
    const ask = d.offer_kind==="freight" ? "Please compare standard and priority freight, including the first pickup, guaranteed handover and all-in charge."
      : d.offer_state==="late" || d.offer_state==="unavailable" ? "Could you offer an earlier partial lot, local stock or an alternative shipping point? Please confirm quantities, delivery windows and any premium."
      : "Could you offer a split shipment or a better unit price for the required quantity? Please confirm the earliest delivery, minimum order and offer expiry.";
    const gap = data?.gaps?.[d.material];
    const need = gap == null ? `Our original enquiry was for ${d.needed.toLocaleString("en-US")} units.`
      : gap > 0 ? `We still need ${gap.toLocaleString("en-US")} units${d.required_by ? " by "+when(d.required_by) : ""}.`
      : "Our current plan covers launch demand, subject to the expected deliveries.";
    const body = `Hello ${d.supplier} team,\n\nThank you for the ${product(d.material).toLowerCase()} update. ${need}\n\n${ask}\n\nKind regards,\nSoony launch team`;
    setDraftError("");
    let message = body;
    if (action !== "negotiate") {
      const sampleBody = action === "approve"
        ? `Could you hold ${d.order_quantity ?? d.quantity} units of ${product(d.material)} without charge and confirm the hold expiry? A separate purchase order is required before dispatch.`
        : `Hello ${d.supplier} team,\n\nThank you for your offer for ${product(d.material).toLowerCase()}. We have decided to decline it for now. Thank you for your help.\n\nSoony launch team`;
      message = d.drafts?.[action]?.body ?? (example ? sampleBody : "");
    }
    setChoice(d.id);
    setNote(null);
    setReply({deal:d, action, body:message});
  }
  const policy = data.limits?.[current];
  async function recordNegotiation() {
    if (!draft || staleDraft || busy) return;
    const deal = draft.deal;
    setDraftError("");
    setBusy(deal.id + "negotiate");
    try {
      if (example) {
        const event = { revision:deal.revision, action:"negotiation started", by:currentUser || "Practice reviewer", at:new Date().toISOString(), note:draft.body,
          terms:{alternatives:rows.map(d => ({id:d.id,supplier:d.supplier,quantity:d.quantity??undefined,price_eur:d.price_eur??undefined}))} };
        setData(old => old && ({...old, deals:old.deals.map(d => d.id===deal.id ? {...d,history:[event,...(d.history ?? [])]} : d)}));
      } else {
        await postDecision(`/api/deals/${deal.id}/negotiate`, {revision:deal.revision, message:draft.body, by:currentUser || reviewer.trim()});
      }
      setReply(null);
      setNote({material:deal.material, message:<>Negotiation recorded for {deal.supplier}. Your draft is in the Activity Log.{" "}
        {!example && deal.address && <a className="quiet" href={`mailto:${encodeURIComponent(deal.address)}?subject=${encodeURIComponent("Re: "+product(deal.material))}&body=${encodeURIComponent(draft.body)}`}>Open in email app</a>}</>});
      if (!example) await load();
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : "The negotiation could not be recorded.");
      await load();
    } finally {
      setBusy(null);
    }
  }
  const history = data.deals.flatMap(d => {
    const events: DecisionEvent[] = d.history?.length ? d.history : d.decided_by
      ? [{action:d.status, by:d.decided_by, at:d.decided_at, terms:{}}] : [];
    return events.map(event => ({d, event, key:JSON.stringify([d.id, event.at, event.revision, event.action, event.by, event.note])}));
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
    } else {
      try {
        await postDecision("/api/deals", {material:current,limit:value,previous:policy.limit,by:currentUser || reviewer.trim()});
        setData(old => old && ({...old,limits:{...old.limits,[current]:{...policy,limit:value,actor:currentUser || reviewer.trim()}}}));
      } finally { await load(); }
    }
    setNote({material:current,message:value ? `${product(current)} automatic approval ceiling saved at ${unitEuros(value)} per unit.`
      : `Automatic approval switched off for ${product(current)}.`});
  }
  const record = history.find(r=>r.key===eventKey && r.d.material===current) ?? history.find(r=>r.d.material===current);
  const threadCount = new Set(rows.map(d=>d.thread_id??d.id)).size;
  const mail = rows.find(d=>d.id===emailId);
  const chooseTab = (id:string) => {setTab(id);setChoice(null);setReply(null);setNote(null);setEventKey(null);};
  return <><section className="card offers-card"><Heading icon="inbox">{archive?"Supplier decisions":"Supplier offers"}</Heading>
    {example && <p className="mini">Practice offers · decisions stay in this browser</p>}
    {loadError && <p role="status">Showing the last loaded offers. {retryButton}</p>}
    {note && note.material===current && <p className="mail-summary" role="status">{note.message}</p>}
    {!materials.length ? <p className="empty">Offers appear as suppliers reply.</p> : <>
      <div className="tabs" role="tablist" aria-label="Products">{materials.map((m,i)=><button key={m} role="tab" id={"tab-"+m} aria-controls="product-panel" tabIndex={current===m?0:-1} aria-selected={current===m}
        onClick={()=>chooseTab(m)} onKeyDown={e=>{
          const next=({ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:materials.length-1} as Record<string,number>)[e.key];
          if(next==null)return;
          e.preventDefault();const id=materials[(next+materials.length)%materials.length];chooseTab(id);document.getElementById("tab-"+id)?.focus();
        }}>{product(m)}</button>)}</div>
      <div role="tabpanel" id="product-panel" aria-labelledby={"tab-"+current}>
        {!archive && policy && <>
          {!example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          <PriceCeiling key={current} policy={policy} product={product(current)} save={saveLimit} readOnly={sharedAccount || (!example && !currentUser && !reviewer.trim())}/>
          {sharedAccount && <button className="quiet" onClick={()=>setSwitchAccount(true)}>Sign in to edit the ceiling</button>}
        </>}
        {archive ? <div className="recommend" data-decision={record && eventTone(record.event.action)}>{record ? <><div className="rec-label"><Icon name="history"/>Recorded decision</div>
          <h3>{record.d.supplier} · {record.event.action}</h3><p>{record.event.by} · {when(record.event.at)}</p>
          <button className="quiet" onClick={()=>setDetails(record)}><Icon name="mail"/>Read decision</button></> :
          <><h3>No decisions recorded for this product</h3><p>Reviewed offers and negotiations appear here.</p></>}</div> :
          selected && <div className="recommend" data-decision={selectedTone}><div className="rec-top"><div className="quote-labels">
            <span className="rec-label">{recommendation(selected) ?? (selected.eligible ? "Supplier quote" : "Supplier response")}</span>
            {selectedTone && <span className="quote-state">{decisionLabels[selectedTone]}</span>}</div>
            {selected.expires_at && <span className="rec-due">{when(selected.expires_at)}</span>}</div>
            <h3>{selected.supplier}</h3><p>{(!selected.followup || selected.followup.state!=="closed" ? selected.review_reason : STATE[selected.offer_state ?? ""]) || selected.conditions || tabNote || gist(selected,data.exchangeRates)}</p>
            <div className="rec-cost"><b>{selected.total_eur!=null?eur(selected.total_eur):priceDisplay(selected,data.exchangeRates).value}</b>
              {selected.total_eur!=null && <small>{selected.offer_kind==="freight" ? "Total freight · "+priceDisplay(selected,data.exchangeRates).value :
                [(selected.order_quantity??selected.quantity)?.toLocaleString("en-US"), priceDisplay(selected,data.exchangeRates).value].filter(Boolean).join(" × ")}</small>}
              {selected.offer_kind==="goods" && selected.freight_charge!=null && selected.freight_currency &&
                <small>Additional freight · {nativePrice(selected.freight_charge,selected.freight_currency,data.exchangeRates)}</small>}
              {selected.total_eur==null && <small>{priceDisplay(selected,data.exchangeRates).source}</small>}
              {selected.unit_price==null && selected.previous_price && selected.offer_kind!=="freight" &&
                <button className="quiet" onClick={()=>openThread(selected.previous_price!.thread_id)}>Read quote thread</button>}</div>
            {!available && (held || selected.decided_by) && <p>{held?"Automatically approved · email awaiting review":STATUS[selected.status]}{selected.decided_by && " · "+selected.decided_by}</p>}
            {data.exchangeRates && priceDisplay(selected,data.exchangeRates).currency && (priceDisplay(selected,data.exchangeRates).currency!=="EUR" || (selected.freight_currency && selected.freight_currency!=="EUR")) &&
              <small className="mini">{data.exchangeRates.url ? <a href={data.exchangeRates.url} target="_blank" rel="noreferrer">{rateSource(data.exchangeRates)}</a> : rateSource(data.exchangeRates)}</small>}
            {selected.followup && <div className="quote-followup">
              <b>Mail agent</b><span>{selected.followup.detail}</span>
              {["due","queued","sent","scheduled","waiting"].includes(selected.followup.state) && !!selected.followup.missing.length && <small>Outstanding · {selected.followup.missing.join(", ")}</small>}
              {selected.followup.nextAt && <small>Next check · {when(selected.followup.nextAt)}</small>}
              {selected.followup.thread && <button className="quiet" onClick={()=>openThread(selected.followup!.thread!)}>View correspondence</button>}
            </div>}
            {selected.request && <p role="status">{selected.request.purpose.charAt(0).toUpperCase()+selected.request.purpose.slice(1)} approved · {selected.request.status === "draft" ? "Queued for sending" : selected.request.status}</p>}
            <div className="decision-buttons">{(available || held) ? <button className="btn" disabled={!!busy} onClick={()=>prepare("approve")}>{held?"Review supplier email":"Approve offer"}</button> : null}
              <button className="outline-btn" disabled={!canDecline||!!busy} onClick={()=>prepare("decline")}>Decline</button>
              <button className="outline-btn" disabled={!!busy||selected.status==="superseded"} onClick={()=>prepare("negotiate")}>Negotiate</button></div></div>}
        {!archive && !recommended.length && <p className="ranking-note">No current recommendation for {product(current).toLowerCase()}.</p>}
        <div className="offers-heading"><b>Supplier emails</b><small>{threadCount} {threadCount===1?"thread":"threads"}</small></div>
        {rows.map(d=>{
          const tone = quoteTone(d);
          const label = recommendation(d);
          const body=<><span className="vendor-avatar">{d.supplier.split(/\s+/).slice(0,2).map(w=>w[0]).join("")}</span>
            <span className="offer-info"><strong>{d.supplier}</strong>{(tone || label) && <span className="row-labels">
              {tone && <b className="quote-state">{decisionLabels[tone]}</b>}{label && <b className="rank-label">{label}</b>}
            </span>}<span>{d.quantity!=null && d.quantity.toLocaleString("en-US")+(d.eligible ? " offered · " : " mentioned · ")}{priceDisplay(d,data.exchangeRates).value} · {priceDisplay(d,data.exchangeRates).source}</span></span></>;
          return <div className={"offer-row "+(selected?.id===d.id?"picked":"")} key={d.id} data-decision={tone}>
            {rows.length>1 && !archive ? <button className="offer-pick" aria-pressed={selected?.id===d.id} onClick={()=>{setChoice(d.id);setReply(null);setNote(null);}}><span className="radio-dot"/>{body}</button> : body}
            <button className="email-button" aria-label={"Read email from "+d.supplier} onClick={()=>setEmailId(d.id)}><Icon name="mail"/></button></div>;
        })}
      </div></>}
  </section><aside className="side-stack">{archive ? <section className="card"><Heading icon="history" count={history.length}>Decision history</Heading>
    <div className="deadline-list" tabIndex={0} aria-label="Decision history">{history.map(r=>
      <button className="deadline-item" data-decision={eventTone(r.event.action)} key={r.key} aria-haspopup="dialog" onClick={()=>{chooseTab(r.d.material);setEventKey(r.key);setDetails(r);}}>
        <span className="deadline-icon"><Icon name="history"/></span><span className="deadline-copy"><b>{product(r.d.material)} · {r.event.action}</b><small>{r.event.by} · {r.d.supplier}</small></span>
        {r.event.at && <span className="due">{when(r.event.at)}</span>}</button>)}{!history.length && <p className="empty">No saved decisions yet.</p>}</div></section> :
    children}</aside>
  {!archive && switchAccount && <Dialog title="Sign in to review offers" label="Supplier decision" close={()=>setSwitchAccount(false)}>
    <p className="modal-p">Use your individual account so the decision is recorded in your name.</p>
    <form className="dialog-actions" action="/logout" method="post"><button className="btn">Switch account</button></form></Dialog>}
  {mail && <Dialog title={mail.supplier} label="Supplier email" close={()=>setEmailId(null)}>
    <EmailPreview key={mail.id+":"+mail.revision} deal={mail} example={example}/>{mail.thread_id && <div className="dialog-actions"><button className="btn" onClick={()=>{setEmailId(null);openThread(mail.thread_id!);}}>Open email thread</button></div>}</Dialog>}
  {archive && details && <Dialog title={details.d.supplier} label="Recorded decision" close={()=>setDetails(null)}>
    <p className="mini">{details.event.action} · {details.event.by} · {when(details.event.at)}</p>
    {details.event.note && <p className="mail-summary draft-body">{details.event.note}</p>}
    {details.event.terms.total_eur!=null && <p>{eur(details.event.terms.total_eur)} total</p>}
    {(details.event.terms.alternatives??[]).map(a=><div className="offer-row" key={a.id}><div className="offer-info"><strong>{a.supplier}</strong><span>{a.quantity?.toLocaleString("en-US")??"Unconfirmed"} units · {a.price_eur==null?"Price unconfirmed":unitEuros(a.price_eur)+"/unit"}</span></div>
      {a.thread_id && <button className="email-button" aria-label={"Read email from "+a.supplier} onClick={()=>{setDetails(null);openThread(a.thread_id!);}}><Icon name="mail"/></button>}</div>)}</Dialog>}
  {!archive && draft && <Dialog label={product(draft.deal.material)+" · "+draft.action} title={draft.action==="approve" ? "Review supplier offer" : "Review email draft"} dismissible={!busy} close={()=>setReply(null)}><div className="editor">
    {draft.action==="approve" && <div className="quote-followup" aria-label="Quoted terms">
      <b>{draft.deal.supplier}</b>
      <span>{(draft.deal.order_quantity??draft.deal.quantity)?.toLocaleString("en-GB")} units · {priceDisplay(draft.deal,data.exchangeRates).value}</span>
      <span>Delivery · {arrives(draft.deal)}</span>
      {draft.deal.total_eur!=null && <span>Total · {eur(draft.deal.total_eur)}</span>}
      {draft.deal.expires_at && <small>Quote valid until {when(draft.deal.expires_at)}</small>}
      <small>Purchase order approval · {draft.deal.signer}</small>
    </div>}
    {draft.action!=="negotiate" && <><p><strong>To</strong> · {draft.deal.address || draft.deal.supplier}</p>
      <strong>{draft.deal.drafts?.[draft.action]?.subject ?? product(draft.deal.material)}</strong></>}
    <label>Message to {draft.deal.supplier}<textarea rows={draft.action==="negotiate" ? 6 : 8} maxLength={1000} readOnly={!!busy || !!staleDraft}
      value={draft.body} onChange={e=>setReply({...draft,body:e.target.value})}/></label>
    {draft.action==="negotiate" && <p>Recording saves this message to the Activity Log. You can send it from your email app afterward.</p>}
    {!example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} readOnly={!!busy} onChange={e=>onReviewer(e.target.value)}/></label>}
    {draftError && <p role="alert">{draftError}</p>}
    {staleDraft && <p role="alert">This offer changed while you were reviewing it. Close the draft to review the latest terms.</p>}
    <button className="btn" disabled={!!busy || !!staleDraft || !draft.body.trim() || (!example && !currentUser && !reviewer.trim())}
      onClick={()=>draft.action==="negotiate" ? void recordNegotiation() : void decide(draft.deal, draft.action, draft.body)}>
      {draft.action==="negotiate" ? busy ? "Recording…" : "Record negotiation" : busy ? "Queuing…" : example ? "Record practice decision" : draft.action==="approve" && !draft.deal.awaiting_send ? "Approve offer and queue reservation" : "Confirm and queue email"}
    </button>
    <button className="quiet" disabled={!!busy} onClick={()=>setReply(null)}>{staleDraft ? "Close draft" : "Cancel"}</button>
  </div></Dialog>}</>;
}
