import { useState } from "react";
import { MailAmounts } from "./MailAmounts";

type View = "english" | "supplier" | "original";
type Props = {
  original: string;
  english?: string | null;
  supplierText?: string | null;
  supplierLanguage?: string;
  loading?: boolean;
  onRetry?: () => void;
};
const languageCodes: Record<string, string> = { Polish: "pl", Chinese: "zh", Korean: "ko" };

export function EmailBody({ original, english, supplierText, supplierLanguage, loading, onRetry }: Props) {
  const [selected, setSelected] = useState<View | null>(null);
  const choices: [View, string][] = [];
  if (english || loading || onRetry) choices.push(["english", english === original ? "English (as received)" : "English"]);
  if (supplierLanguage) choices.push(["supplier", supplierText === original ? supplierLanguage + " (as received)" : supplierLanguage]);
  if (original !== english && original !== supplierText) choices.push(["original", "As received"]);
  const defaultView = choices.find(([id]) => id === "english" || (id === "supplier" && supplierText))?.[0] ?? "original";
  const view = choices.some(([id]) => id === selected) ? selected : defaultView;
  const body = view === "english" ? english : view === "supplier" ? supplierText : original;
  const lang = view === "english" ? "en" : view === "supplier" && supplierLanguage ? languageCodes[supplierLanguage] : undefined;
  return <section className="email-preview">
    {choices.length > 1 && <div className="email-languages" role="group" aria-label="Email language">
      {choices.map(([id, label]) => <button key={id} className="quiet" aria-pressed={view === id}
        onClick={() => setSelected(id)}>{label}</button>)}
    </div>}
    {body ? <><p className="draft-body" lang={lang}>{body}</p><MailAmounts text={body}/></> :
      <p role="status">{loading ? "Loading translation…" : `${view === "supplier" ? supplierLanguage : "English"} translation unavailable.`}
        {!loading && onRetry && <> <button className="quiet" onClick={onRetry}>Retry</button></>}</p>}
  </section>;
}
