import { useEffect, useState } from "react";
import { hostedReplayBuild, isStaticMode } from "../api";
import sample from "./offers-sample.json";
import "./offers.css";

// T90 mail-agent: every supplier offer in one table, best offer per part on top,
// Approve / Decline per offer. Approve names the PP-07 signer and asks the supplier to
// reserve; Decline sends a polite no-thanks. Both emails go out through the mail agent.

type Deal = {
  address?: string; revision?: string; required_by?: string; thread_id?: string; order_quantity?: number | null; expires_at?: string | null;
  offer_state?: "quoted" | "incomplete" | "late" | "unavailable" | "expired" | "superseded" | "approval_required";
  offer_kind?: "goods" | "freight"; carrier?: string | null; freight_charge?: number | null;
  review_reason?: string;
  history?: { revision: string; action: string; by: string; at: string; terms: { order_quantity?: number; total_eur?: number; signer?: string } }[];
  id: string; supplier_id?: string; eta_text?: string | null; supplier: string; material: string; needed: number; quantity: number | null;
  unit_price: number | null; currency: string | null; price_eur: number | null; total_eur: number | null;
  eta: string | null; p_on_time: number | null; score: number | null; best: number; eligible: number;
  proof: string | null; incoterm: string | null; payment_terms: string | null; moq: number | null;
  list_price: number | null; conditions: string | null; excerpt: string | null; signer: string;
  status: "pending" | "approved" | "declined" | "changed" | "superseded"; decided_by: string | null; decided_at: string | null;
};
type Data = { deals: Deal[]; best: Deal[]; notes?: Record<string, string>; as_of?: string; gaps?: Record<string, number> };
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
function unit(d: Deal) { return d.unit_price == null ? "no price" : `${d.unit_price} ${d.currency ?? ""}`; }

function exampleData(): Data {
  const data = sample as unknown as Data;
  return { ...data, best: data.deals.filter((d) => d.best) };
}

type Props = {
  archive: boolean;
  currentUser?: string | null;
  reviewer: string;
  onReviewer: (name: string) => void;
  openThread: (id: string) => void;
};
export function Offers({ archive, currentUser, reviewer, onReviewer, openThread }: Props) {
  // Hosted recording and static builds have no live backend: show a labelled example,
  // and keep Approve / Decline in this browser only (nothing is sent).
  const example = hostedReplayBuild || isStaticMode();
  const [data, setData] = useState<Data | null>(example ? exampleData() : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [choice, setChoice] = useState<string | null>(null);
  const [reply, setReply] = useState<{id:string; revision?:string; action:"approve"|"decline"|"negotiate"; body:string} | null>(null);
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
        const deals = old.deals.map((d) => d.id === deal.id ? { ...d, status, decided_by: "you" } as Deal : d);
        return { ...old, deals, best: deals.filter((d) => d.best) };
      });
      setNote(`Example only: in the live app this ${action === "approve" ? "asks the supplier in " + country(deal) + " to reserve the units (the purchase order needs the " + deal.signer + ")" : "sends the supplier in " + country(deal) + " a polite no-thanks"}. Nothing was sent here.`);
      return;
    }
    setBusy(deal.id + action);
    try {
      const response = await fetch(`/api/deals/${deal.id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: deal.revision, ...(!currentUser && reviewer.trim() ? {by:reviewer.trim()} : {}) }) });
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

  if (!data) return <section className="card offers"><h3>Supplier offers</h3><p role="status">{loadError ? "Supplier offers could not be loaded." : "Loading supplier offers…"}</p>{loadError && <button className="ghost-button" onClick={()=>void load()}>Retry</button>}</section>;
  // Every part from the case keeps its tab; short parts come first, covered ones are marked "covered" (Gülşah, 22 Nov).
  const allMaterials = [...new Set(data.deals.map((d) => d.material))];
  const short = (m: string) => !data.gaps || !(m in data.gaps) || (data.gaps[m] ?? 0) > 0;
  const covered = allMaterials.filter((m) => !short(m));
  const materials = [...allMaterials.filter(short), ...covered];
  const current = tab && materials.includes(tab) ? tab : materials[0];
  const rows = data.deals.filter((d) => d.material === current);
  const best = data.best.filter((d) => d.material === current);
  const tabNote = current ? data.notes?.[current] : undefined;

  const selected = rows.find(d=>d.id===choice) ?? best[0] ?? rows[0];
  const draft = reply && selected && reply.id===selected.id && reply.revision===selected.revision ? reply : null;
  const available = selected?.eligible && ["changed","pending"].includes(selected.status);
  function prepare(action:"approve"|"decline"|"negotiate") {
    const d = selected;
    const ask = d.offer_kind==="freight" ? "Please compare standard and priority freight, including the first pickup, guaranteed handover and all-in charge."
      : d.offer_state==="late" || d.offer_state==="unavailable" ? "Could you offer an earlier partial lot, local stock or an alternative shipping point? Please confirm quantities, delivery windows and any premium."
      : "Could you offer a split shipment or a better unit price for the required quantity? Please confirm the earliest delivery, minimum order and offer expiry.";
    const body = `Hello ${d.supplier} team,\n\nThank you for the ${product(d.material).toLowerCase()} update. We need ${d.needed.toLocaleString("en-US")} units${d.required_by ? " by "+when(d.required_by):""}. Your reply indicates ${d.quantity?.toLocaleString("en-US") ?? "an unconfirmed quantity"} units, with arrival ${arrives(d)}.\n\n${ask}\n\nKind regards,\nSoony launch team`;
    setReply({id:d.id, revision:d.revision, action, body});
  }
  if (archive) {
    const history = data.deals.flatMap(d=>(d.history?.length ? d.history : d.decided_by ? [{action:d.status, by:d.decided_by, at:d.decided_at, revision:d.revision}] : [])
      .map((h,i)=>({d,h,key:d.id+"-"+i}))).sort((a,b)=>(b.h.at??"").localeCompare(a.h.at??""));
    return <section className="card offers"><h3>Supplier decision history</h3>{history.length ? history.map(({d,h,key})=><article className="supplier-event" key={key}><strong>{d.supplier} · {h.action}</strong>
      <p>{product(d.material)} · {h.by || "Reviewer not recorded"}{h.at && " · "+when(h.at)}</p>
      {d.thread_id && <button className="link-button" onClick={()=>openThread(d.thread_id!)}>Open supplier email</button>}</article>):<p className="empty">No supplier decisions recorded.</p>}</section>;
  }
  return <section className="card offers" aria-labelledby="offers-title"><h3 id="offers-title">Supplier offers</h3>
    {example && <small className="muted">Practice offers · decisions stay in this browser</small>}
    {loadError && <p role="status">Showing the last loaded offers. <button className="link-button" onClick={()=>void load()}>Retry</button></p>}
    {note && <p className="offers-note" role="status">{note}</p>}
    {!materials.length ? <p className="empty">Offers appear as suppliers reply.</p> : <>
      <div className="offers-tabs" aria-label="Products">{materials.map(m=><button key={m} className={current===m?"is-on":""} aria-pressed={current===m}
        onClick={()=>{setTab(m);setChoice(null);setReply(null);setNote(null);}}>{product(m)}</button>)}</div>
      <div className="offer-recommendation"><small>{best.length ? "Recommended choice" : covered.includes(current) ? "Covered by existing supply" : "Supplier outlook"}</small>
        <strong>{best.length ? best.map(d=>d.supplier).join(" + ") : product(current)}</strong>
        <p>{best.length ? best.map(d=>gist(d)).join(" / ") : tabNote || rows[0]?.review_reason || "Compare the supplier replies and outstanding conditions below."}</p>
        {best.length>0 && tabNote && <p>{tabNote}</p>}
      </div>
      <div className="supplier-list" aria-label="Select a supplier offer">{rows.map(d=><button key={d.id} aria-pressed={selected?.id===d.id} onClick={()=>{setChoice(d.id);setReply(null);setNote(null);}}>
        <span><b>{country(d)}</b><small>{d.quantity?.toLocaleString("en-US") ?? "Unknown"} units · {arrives(d)}</small></span><span>{d.best?"Recommended":STATUS[d.status]}</span></button>)}</div>
      {selected && <div className="offer-selected" key={selected.id}>
        <p><b>{selected.supplier}</b> · {unit(selected)} · {eur(selected.total_eur)} total</p>
        {selected.conditions && <p>{selected.conditions}</p>}
        {(selected.excerpt || selected.quantity!=null) && <Words key={selected.id+selected.revision} d={selected} example={example}/>}
        {selected.thread_id && <button className="link-button" onClick={()=>openThread(selected.thread_id!)}>Open supplier email</button>}
        <details><summary>Offer terms and evidence</summary><p>{gist(selected)}</p><p>{[selected.carrier,selected.payment_terms,selected.signer&&"Signer · "+selected.signer,selected.required_by&&"Required by "+when(selected.required_by),selected.expires_at&&"Expires "+when(selected.expires_at),selected.p_on_time!=null&&"On time "+Math.round(selected.p_on_time*100)+"%",selected.list_price!=null&&"Contract price "+selected.list_price].filter(Boolean).join(" · ")}</p>
        {selected.history?.map((h,i)=><p key={i}>{when(h.at)} · {h.by} · {h.action} · {eur(h.terms.total_eur??null)}</p>)}</details>
        {!available && <p className="muted">{selected.review_reason || STATUS[selected.status]}{selected.decided_by && " · "+selected.decided_by}</p>}
        <div className="offers-actions">
          <button className="primary-button" disabled={!available || !!busy} onClick={()=>prepare("approve")}>Approve</button>
          <button className="ghost-button" disabled={!available || !!busy} onClick={()=>prepare("decline")}>Decline</button>
          <button className="ghost-button" disabled={!!busy} onClick={()=>prepare("negotiate")}>Negotiate</button>
        </div>
        {draft && <section className="reply-review"><h4>{draft.action==="negotiate"?"Negotiation draft":draft.action==="approve"?"Review reservation request":"Review decline"}</h4>
        {draft.action==="negotiate" ? <><label>Message to {selected.supplier}<textarea rows={6} value={draft.body} onChange={e=>setReply({...draft,body:e.target.value})}/></label>
          {example || !selected.address ? <small className="muted">Copy this draft into your supplier correspondence.</small> :
          <a className="ghost-button" href={`mailto:${encodeURIComponent(selected.address)}?subject=${encodeURIComponent("Re: "+product(selected.material))}&body=${encodeURIComponent(draft.body)}`}>Open in email app</a>}</> : <>
          <p>{example?"Practice decision for ":draft.action==="approve"?"Queue a nonbinding reservation request to ":"Queue a decline email to "}<b>{selected.supplier}</b> · {(selected.order_quantity??selected.quantity)?.toLocaleString("en-US")} units · {eur(selected.total_eur)}.</p>
          {!example && !currentUser && <label>Reviewed by<input autoComplete="name" maxLength={80} value={reviewer} onChange={e=>onReviewer(e.target.value)}/></label>}
          <button className="primary-button" disabled={!available || !!busy || (!example&&!currentUser&&!reviewer.trim())} onClick={()=>{void decide(selected,draft.action as "approve"|"decline");setReply(null);}}>{draft.action==="approve"?"Confirm reservation request":"Confirm decline"}</button></>}
          <button className="link-button" onClick={()=>setReply(null)}>Cancel</button>
        </section>}
      </div>}
    </>}
  </section>;
}
