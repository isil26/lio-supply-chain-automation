import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Approval, DashboardData, DecisionEffect, MailPreview, MailView, PastDecision, Source } from "./api";

type Review = NonNullable<DashboardData["recoveryApprovals"]>[number];
type Mode = Approval["approvalMode"];
type Props = {
  options: Approval[];
  reviews?: Review[];
  costOf: (productId: string) => number | null;
  busy: boolean;
  readOnly: boolean;
  onDecide: (id: string, review: boolean, by?: string) => void;
  onEvidence: (source: Source) => void;
  autoLimit: number;
  autoIds: string[];
  autoBy?: string | null;
  onAutoLimit?: (limitEur: number) => void;
  practiceNote?: string;
  requestedAction?: { id: string } | null;
  onOpenThread?: (threadId: string) => void;
  onPreview?: (id: string) => Promise<MailPreview | null>;
  past?: PastDecision[];
};

// Slider stops for the auto-approve limit (EUR); 0 = off.
const STOPS = [0, 1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000];

const when = new Intl.DateTimeFormat("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
const num = (n: number) => Math.round(n).toLocaleString("en-US");
const euro = (n: number) => n >= 1e6 ? `€${(n / 1e6).toFixed(2).replace(/0$/, "")}M` : n >= 1e4 ? `€${Math.round(n / 1000)}k` : `€${num(n)}`;

// Badge for the approval engine's verdict (src/decide/approvals.py): who may let this action go out.
function badge(mode: Mode) {
  const m = (mode?.mode ?? "ONE_CLICK").toUpperCase();
  const blocked = (mode?.blockedBy ?? []).join(" ");
  if (m === "REVIEW") return { cls: "", text: "", hint: "Confirm in the warehouse or with the supplier." };
  if (m === "AUTO") return { cls: "auto", text: mode?.simulated ? "Simulated" : "Auto", hint: mode?.reason };
  if (m === "ESCALATE") return { cls: "escalate", text: `Escalated${mode?.escalateTo ? ` → ${mode.escalateTo}` : ""}`, hint: mode?.reason };
  if (m === "NEVER" && /value_eur|not grounded/i.test(blocked)) return { cls: "never", text: "Needs a price first", hint: mode?.reason };
  if (m === "NEVER" && /quality/i.test(mode?.reason ?? "")) return { cls: "never", text: "Quality decides", hint: mode?.reason };
  if (m === "NEVER") return { cls: "never", text: "Human only", hint: mode?.reason };
  return { cls: "", text: "", hint: mode?.reason };
}

// The person approving is the decision-maker (Gülşah, 22 Nov): the confirm box shows the message their click sends.
const costLine = (option: Approval | undefined) => option?.price ? `Cost: ${euro(option.price)}.` : "";
// Who is approving: the signed-in user once the login exists ("soony-user"), until then the name given in Offers.

function Email({ mail, label, from }: { mail: MailView; label: string; from?: boolean }) {
  const [full, setFull] = useState(false);
  if (!mail.body) return null;
  return <div className="ac-email">
    <p className="ac-email-head">{label}</p>
    <dl><dt>{from ? "From" : "To"}</dt><dd>{mail.to ?? "supplier"}</dd>{mail.subject && <><dt>Subject</dt><dd>{mail.subject}</dd></>}</dl>
    <pre className={full ? "" : "clamp"}>{mail.body}</pre>
    <button className="link-button" onClick={() => setFull(!full)}>{full ? "Show less" : "Show the whole email"}</button>
  </div>;
}

const replied = (line: string, effect?: DecisionEffect | null) => effect?.reply ? line.replace("Waiting for their reply.", "They replied (below).") : line;
const PAST_STATUS: Record<string, string> = { approved: "Approved", review: "Sent back for review", dismissed: "Declined", done: "Done", reviewed: "Reviewed" };

// Past actions: every decision of the last 7 days with what was decided, by whom, the message and the reply.
export function PastList({ rows, onOpenThread }: { rows: PastDecision[]; onOpenThread?: (threadId: string) => void }) {
  const [open, setOpen] = useState("");
  if (!rows.length) return <p className="empty">No decisions in the last 7 days yet.</p>;
  return <ol className="ac-list ac-past">
    {rows.map((row) => {
      const by = row.effect?.by;
      const expanded = open === row.id;
      return <li key={row.id} className="ac-item">
        <div className="ac-main">
          <strong className="ac-title">{row.title}</strong>
          <span className="ac-meta">{PAST_STATUS[row.status] ?? row.status}{by ? ` by ${by}` : ""}{row.decidedAt ? ` · ${when.format(new Date(row.decidedAt))}` : ""}{row.owner ? ` · ${row.owner}` : ""}</span>
        </div>
        <div className="ac-value">{row.price ? <><b>{euro(row.price)}</b><span>cost</span></> : <span className="muted">{row.effect?.sent ? "message sent" : ""}</span>}</div>
        <div className="ac-buttons">
          <span className={`ac-status ${row.status === "approved" ? "" : "muted"}`}>{PAST_STATUS[row.status] ?? row.status}</span>
          <button className="link-button" onClick={() => setOpen(expanded ? "" : row.id)} aria-expanded={expanded}>{expanded ? "Less" : "Details"}</button>
        </div>
        {expanded && <div className="ac-effect">
          <p className="ac-effect-head">What happened</p>
          <ul>{(row.effect?.lines ?? [`${PAST_STATUS[row.status] ?? row.status}.`]).map((line, i) => <li key={i}>{replied(line, row.effect)}</li>)}</ul>
          {(row.recommendation || row.impact) && <><p className="ac-effect-head">What was decided</p>
            <p className="ac-past-text">{row.recommendation}{row.impact ? ` ${row.impact}` : ""}</p></>}
          {row.effect?.email && <Email mail={row.effect.email} label={row.effect.email.status === "ongoing" ? "The ongoing email with the supplier" : "The message that went out"}/>}
          {row.effect?.reply ? <Email mail={{ to: row.effect.reply.from, body: row.effect.reply.body }} label={`Reply · ${when.format(new Date(row.effect.reply.at))}`} from/>
            : row.effect?.email && <p className="muted">No reply yet.</p>}
          {row.effect?.threadId && onOpenThread && <button className="link-button" onClick={() => onOpenThread(row.effect!.threadId!)}>Open the email conversation</button>}
        </div>}
      </li>;
    })}
  </ol>;
}

const STATUS: Record<string, string> = { approved: "Approved", review: "Under review", blocked: "Blocked", sent: "Sent", replied: "Replied", done: "Done" };

export function ActionList({ requestedAction, options, reviews, costOf, busy, readOnly, onDecide, onEvidence, autoLimit, autoIds, autoBy, onAutoLimit, practiceNote, onOpenThread, onPreview, past }: Props) {
  const shortName = (name?: string | null) => name ? name.replace(/^((?:Dr\.|Prof\.)\s+)?.*\s(\S+)$/, (_, title = "", last) => `${title}${last}`) : "";
  const nearest = STOPS.reduce((best, stop, i) => Math.abs(stop - autoLimit) < Math.abs(STOPS[best] - autoLimit) ? i : best, 0);
  const [stop, setStop] = useState(nearest);
  useEffect(() => setStop(nearest), [nearest]);
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<string>("");
  const [confirming, setConfirming] = useState<string>("");
  const [tab, setTab] = useState<"open" | "past">("open");
  const focusDecision = useRef(false);
  useEffect(() => {
    if (!requestedAction) return;
    focusDecision.current = true;
    setTab("open");
    setShowAll(true);
    setOpen(requestedAction.id);
    const visible = document.getElementById(`decision-${requestedAction.id}`);
    if (visible) {
      visible.focus();
      focusDecision.current = false;
    }
  }, [requestedAction]);
  useLayoutEffect(() => {
    if (focusDecision.current && open && tab === "open" && showAll) {
      document.getElementById(`decision-${open}`)?.focus();
      focusDecision.current = false;
    }
  }, [open, tab, showAll]);
  // Live approval needs a successful preview: nobody confirms a message they could not see (codex-deploy, 22 Nov).
  const [preview, setPreview] = useState<MailPreview | null | "loading" | "failed">(null);
  const ask = (id: string) => {
    if (confirming === id) { setConfirming(""); return; }
    setConfirming(id); setPreview(onPreview ? "loading" : null);
    onPreview?.(id).then((value) => setPreview(value ?? "failed")).catch(() => setPreview("failed"));
  };
  const byId = new Map((reviews ?? []).map((review) => [review.id, review]));

  const cards = options.map((option) => {
    const review = byId.get(option.id);
    const impact = Object.entries(option.modeled_impact ?? {});
    const copies = impact.reduce((sum, [, e]) => sum + Math.max(0, e.expectedDelta ?? e.medianDelta ?? 0), 0);
    const known = impact.every(([pid]) => costOf(pid) != null);
    const gain = known ? impact.reduce((sum, [pid, e]) => sum + Math.max(0, e.expectedDelta ?? e.medianDelta ?? 0) * (costOf(pid) ?? 0), 0) : null;
    const mode = (option as Approval & { approvalMode?: Mode }).approvalMode;
    const evidence = (option.evidence ?? []).find((e): e is never => typeof e === "object" && e !== null) as Source | undefined;
    return {
      id: option.id, option, mode, copies, gain,
      title: review?.title ?? option.title,
      who: review?.approver ?? mode?.approver ?? option.owner,
      due: review?.dueAt ?? (option as Approval & { latest_action?: string }).latest_action ?? null,
      price: review?.price ?? option.price,
      why: review?.detail ?? option.recommendation,
      evidence: review?.evidence ?? evidence,
      threadId: review?.threadId ?? null,
      thread: review?.threadId ? `?thread=${encodeURIComponent(review.threadId)}${review.replyId == null ? "" : `#message-${review.replyId}`}` : null,
      status: option.status ?? "pending",
      effect: option.effect ?? null as DecisionEffect | null,
    };
  });
  // Live reviews that are not one of the options (e.g. receiving checks) join the same list, without an approve button.
  const optionIds = new Set(options.map((option) => option.id));
  for (const review of reviews ?? []) {
    if (optionIds.has(review.id)) continue;
    cards.push({
      id: review.id, option: undefined as unknown as Approval, mode: { mode: "REVIEW", approver: review.approver }, copies: 0, gain: null,
      title: review.title, who: review.approver, due: review.dueAt ?? null, price: review.price ?? null, why: review.detail,
      evidence: review.evidence ?? undefined,
      threadId: review.threadId ?? null,
      thread: review.threadId ? `?thread=${encodeURIComponent(review.threadId)}${review.replyId == null ? "" : `#message-${review.replyId}`}` : null,
      status: "pending",
      effect: null,
    });
  }
  cards.sort((a, b) => (b.gain ?? 0) - (a.gain ?? 0) || b.copies - a.copies
    || Number(a.mode?.mode === "NEVER") - Number(b.mode?.mode === "NEVER"));

  // Decided cards stay on the open list for 10 minutes (so "What happened" is seen), then live under Past actions.
  const RECENT_MS = 10 * 60 * 1000;
  const decidedAt = (card: typeof cards[number]) => card.option?.decidedAt ?? card.effect?.at ?? null;
  const fresh = (card: typeof cards[number]) => card.status === "pending" || card.status === "blocked"
    || !decidedAt(card) || Date.now() - new Date(decidedAt(card)!).getTime() < RECENT_MS;
  const openCards = cards.filter(fresh);
  const pastRows: PastDecision[] = past ?? cards.filter((card) => card.status !== "pending" && card.status !== "blocked").map((card) => ({
    id: card.id, status: card.status, decidedAt: decidedAt(card) ?? "", title: card.title, owner: card.who,
    recommendation: card.why, price: card.price ?? null, effect: card.effect }));
  const shown = showAll ? openCards : openCards.slice(0, 4);

  return <section className="card actions-card" id="actions" aria-label="Actions">
    <div className="ac-head">
      <div className="ac-tabs" role="tablist" aria-label="Actions">
        <button role="tab" aria-selected={tab === "open"} className={tab === "open" ? "on" : ""} onClick={() => setTab("open")}>Actions{openCards.length ? ` (${openCards.length})` : ""}</button>
        <button role="tab" aria-selected={tab === "past"} className={tab === "past" ? "on" : ""} onClick={() => setTab("past")}>Past actions{pastRows.length ? ` (${pastRows.length})` : ""}</button>
      </div>
      {!readOnly && onAutoLimit && <label className="ac-auto">
        <span>{autoBy ? `${shortName(autoBy)} auto-approves routine actions up to` : "Auto-approve routine actions up to"}</span>
        <input type="range" min={0} max={STOPS.length - 1} step={1} value={stop}
          onChange={(event) => setStop(Number(event.target.value))}
          onPointerUp={() => onAutoLimit(STOPS[stop])} onKeyUp={() => onAutoLimit(STOPS[stop])}
          aria-valuetext={STOPS[stop] ? euro(STOPS[stop]) : "Off"}/>
        <b>{STOPS[stop] ? euro(STOPS[stop]) : "Off"}</b>
      </label>}
    </div>
    {practiceNote && <p className="ac-practice" role="note">{practiceNote}</p>}
    {tab === "past" ? <PastList rows={pastRows} onOpenThread={onOpenThread}/> : !openCards.length
      ? <p className="empty">Nothing needs a decision right now.</p> : <>
    <ol className="ac-list">
      {shown.map((card, index) => {
        const b = badge(card.mode);
        const decided = card.status !== "pending";
        const automatic = autoIds.includes(card.id);
        const decisionLabel = automatic
          ? card.mode?.simulated ? "Simulated approval" : "Auto-approved"
          : STATUS[card.status] ?? card.status;
        return <li key={card.id} id={`decision-${card.id}`} tabIndex={-1} className={`ac-item ${index === 0 ? "top" : ""}`}>
          <div className="ac-main">
            {!decided && b.text && <span className={`ac-badge ${b.cls}`} title={b.hint ?? undefined}>{b.text}</span>}
            <strong className="ac-title">{card.title}</strong>
            <span className="ac-meta">{card.who}{card.due ? ` · by ${when.format(new Date(card.due))}` : ""}</span>
          </div>
          <div className="ac-value">
            {card.copies > 0 ? <><b>+{num(card.copies)}</b><span>copies{card.gain ? ` · ≈ ${euro(card.gain)}` : ""}</span></>
              : card.price ? <><b>{euro(card.price)}</b><span>cost</span></> : card.price === 0 ? <span className="muted">no cost</span> : <span className="muted">packing impact not estimated</span>}
          </div>
          <div className="ac-buttons">
            {decided ? <span className={`ac-status ${automatic ? "auto" : ""}`}>{decisionLabel}</span>
              : !readOnly && card.option && card.mode?.mode !== "NEVER" && <button className="primary-button small" disabled={busy}
                  onClick={() => onPreview ? ask(card.id) : onDecide(card.id, false)}>Approve</button>}
            {!decided && !readOnly && card.option && <button className="ghost-button small" disabled={busy} onClick={() => onDecide(card.id, true)}>Review</button>}
            <button className="link-button" onClick={() => setOpen(open === card.id ? "" : card.id)} aria-expanded={open === card.id}>{open === card.id ? "Less" : "Why"}</button>
          </div>
          {confirming === card.id && !decided && <div className="ac-confirm" role="alertdialog" aria-label={`Confirm: ${card.title}`}>
            <strong>Approve this action?</strong>
            {preview === "loading" ? <p className="muted">Loading the approval preview…</p>
              : preview === "failed" ? <p role="alert">The approval preview is unavailable. Refresh the page to try again.</p>
              : preview ? <>
                <p>{preview.note} {costLine(card.option)}</p>
                {preview.mode !== "none" && <Email mail={preview.mode === "internal" ? { ...preview, to: `${preview.recipientName} (via ${preview.to})` } : preview}
                  label={preview.mode === "conversation" ? "The ongoing email with the supplier" : "This message goes out when you approve"}/>}
              </> : <p>{costLine(card.option)}</p>}
            <div className="ac-confirm-buttons">
              <button className="primary-button small" disabled={busy || preview === "loading" || preview === "failed"} autoFocus
                onClick={() => { setConfirming(""); onDecide(card.id, false); }}>
                {preview && typeof preview === "object" && (preview.mode === "send" || preview.mode === "internal") ? "Yes, approve and send" : "Yes, approve"}</button>
              <button className="ghost-button small" onClick={() => setConfirming("")}>Cancel</button>
            </div>
          </div>}
          {decided && <div className="ac-effect" aria-live="polite">
            <p className="ac-effect-head">What happened</p>
            <ul>{(card.effect?.lines ?? [automatic
              ? "Approved automatically under a written delegation."
              : card.status === "blocked" ? (card.mode?.reason || "This action is blocked.")
              : card.status === "review" ? "Sent back for review." : decisionLabel])
              .map((line, i) => <li key={i}>{replied(line, card.effect)}</li>)}</ul>
            {card.effect?.email && <Email mail={card.effect.email} label={card.effect.email.status === "ongoing" ? "The ongoing email with the supplier" : card.effect.email.status === "sent" ? "The message that went out" : "The message"}/>}
            {card.effect?.reply && <Email mail={{ to: card.effect.reply.from, body: card.effect.reply.body }} label={`Reply · ${when.format(new Date(card.effect.reply.at))}`} from/>}
            {card.effect?.threadId && onOpenThread && <button className="link-button" onClick={() => onOpenThread(card.effect!.threadId!)}>Open the email conversation</button>}
          </div>}
          {open === card.id && <div className="ac-why">
            <p>{card.why}</p>
            {b.hint && <p className="muted">{b.hint}</p>}
            <div className="ac-links">
              {card.evidence && <button className="link-button" onClick={() => onEvidence(card.evidence!)}>View source</button>}
              {card.threadId && onOpenThread && <button className="link-button" onClick={() => onOpenThread(card.threadId!)}>Supplier reply</button>}
            </div>
          </div>}
        </li>;
      })}
    </ol>
    {openCards.length > 4 && <button className="link-button ac-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show ${openCards.length - 4} more`}</button>}
    </>}
  </section>;
}
