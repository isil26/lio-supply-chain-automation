import { useEffect, useState } from "react";
import type { Approval, DashboardData, Source } from "./api";

type Review = NonNullable<DashboardData["recoveryApprovals"]>[number];
type Mode = Approval["approvalMode"];
type Props = {
  options: Approval[];
  reviews?: Review[];
  costOf: (productId: string) => number | null;
  busy: boolean;
  readOnly: boolean;
  onDecide: (id: string, review: boolean) => void;
  onEvidence: (source: Source) => void;
  autoLimit: number;
  autoIds: string[];
  autoBy?: string | null;
  onAutoLimit?: (limitEur: number) => void;
  practiceNote?: string;
  onOpenThread?: (threadId: string) => void;
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

const STATUS: Record<string, string> = { approved: "Approved", review: "Under review", blocked: "Blocked", sent: "Sent", replied: "Replied", done: "Done" };

export function ActionList({ options, reviews, costOf, busy, readOnly, onDecide, onEvidence, autoLimit, autoIds, autoBy, onAutoLimit, practiceNote, onOpenThread }: Props) {
  const shortName = (name?: string | null) => name ? name.replace(/^((?:Dr\.|Prof\.)\s+)?.*\s(\S+)$/, (_, title = "", last) => `${title}${last}`) : "";
  const nearest = STOPS.reduce((best, stop, i) => Math.abs(stop - autoLimit) < Math.abs(STOPS[best] - autoLimit) ? i : best, 0);
  const [stop, setStop] = useState(nearest);
  useEffect(() => setStop(nearest), [nearest]);
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<string>("");
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
    });
  }
  cards.sort((a, b) => (b.gain ?? 0) - (a.gain ?? 0) || b.copies - a.copies
    || Number(a.mode?.mode === "NEVER") - Number(b.mode?.mode === "NEVER"));

  const shown = showAll ? cards : cards.slice(0, 4);
  if (!cards.length) return <section className="card actions-card"><h3>Actions</h3><p className="empty">Nothing needs a decision right now.</p></section>;

  return <section className="card actions-card" id="actions" aria-label="Actions">
    <div className="ac-head">
      <h3>Actions</h3>
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
    <ol className="ac-list">
      {shown.map((card, index) => {
        const b = badge(card.mode);
        const decided = card.status !== "pending";
        const automatic = autoIds.includes(card.id);
        const decisionLabel = automatic
          ? card.mode?.simulated ? "Simulated approval" : "Auto-approved"
          : STATUS[card.status] ?? card.status;
        return <li key={card.id} className={`ac-item ${index === 0 ? "top" : ""}`}>
          <div className="ac-main">
            {!decided && b.text && <span className={`ac-badge ${b.cls}`} title={b.hint ?? undefined}>{b.text}</span>}
            <strong className="ac-title">{card.title}</strong>
            <span className="ac-meta">{card.who}{card.due ? ` · by ${when.format(new Date(card.due))}` : ""}</span>
          </div>
          <div className="ac-value">
            {card.copies > 0 ? <><b>+{num(card.copies)}</b><span>copies{card.gain ? ` · ≈ ${euro(card.gain)}` : ""}</span></>
              : card.price ? <><b>{euro(card.price)}</b><span>cost</span></> : card.price === 0 ? <span className="muted">no cost</span> : <span className="muted">no gain modelled</span>}
          </div>
          <div className="ac-buttons">
            {decided ? <span className={`ac-status ${automatic ? "auto" : ""}`}>{decisionLabel}</span>
              : !readOnly && card.option && card.mode?.mode !== "NEVER" && <button className="primary-button small" disabled={busy} onClick={() => onDecide(card.id, false)}>Approve</button>}
            {!decided && !readOnly && card.option && <button className="ghost-button small" disabled={busy} onClick={() => onDecide(card.id, true)}>Review</button>}
            <button className="link-button" onClick={() => setOpen(open === card.id ? "" : card.id)} aria-expanded={open === card.id}>{open === card.id ? "Less" : "Why"}</button>
          </div>
          {open === card.id && <div className="ac-why">
            <p>{card.why}</p>
            {b.hint && <p className="muted">{b.hint}</p>}
            <div className="ac-links">
              {card.evidence && <button className="link-button" onClick={() => onEvidence(card.evidence!)}>Source</button>}
              {card.threadId && onOpenThread && <button className="link-button" onClick={() => onOpenThread(card.threadId!)}>Supplier reply</button>}
            </div>
          </div>}
        </li>;
      })}
    </ol>
    {cards.length > 4 && <button className="link-button ac-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show ${cards.length - 4} more`}</button>}
  </section>;
}
