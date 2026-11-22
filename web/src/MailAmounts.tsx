import { useContext } from "react";
import { ExchangeContext, nativePrice, rateSource } from "./currency";

const amount = String.raw`\d+(?:[ \u00a0]\d{3}(?!\d))*(?:[.,]\d+)*`;
const currency = String.raw`(?:[A-Z]{3}|US\$|₩)`;
const mention = new RegExp(String.raw`(?<![A-Za-z0-9])(?:(${currency})[ \u00a0]*(${amount})|(${amount})[ \u00a0]*(${currency}))(?![A-Za-z0-9])`, "g");

export function MailAmounts({text}: {text:string}) {
  const rates = useContext(ExchangeContext);
  if (!rates) return null;
  const amounts = new Set<string>();
  for (const match of text.matchAll(mention)) {
    const code = match[1] ?? match[4];
    const iso = code === "US$" ? "USD" : code === "₩" ? "KRW" : code;
    if (iso === "EUR" || !rates.eurPerUnit[iso]) continue;
    const raw = (match[2] ?? match[3]).replace(/[ \u00a0]/g,"");
    const parts = raw.split(/[.,]/);
    const grouped = /^[1-9]\d{0,2}(?:,\d{3})+$/.test(raw) || /^[1-9]\d{0,2}(?:\.\d{3})+$/.test(raw);
    const value = Number(grouped || parts.length === 1 ? parts.join("") : parts.slice(0,-1).join("")+"."+parts[parts.length-1]);
    if (Number.isFinite(value)) amounts.add(nativePrice(value,iso,rates));
  }
  return amounts.size ? <p className="mini" title={rateSource(rates)}>Euro equivalents · {[...amounts].join(" · ")}</p> : null;
}
