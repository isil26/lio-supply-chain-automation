import { createContext } from "react";

export type ExchangeRates = {source:string; asOf:string|null; url?:string|null; eurPerUnit:Record<string,number>};
export const ExchangeContext = createContext<ExchangeRates | undefined>(undefined);
const unit = new Intl.NumberFormat("en-GB",{minimumFractionDigits:2,maximumFractionDigits:6});
export function equivalent(amount:number, currency:string, rates?:ExchangeRates) {
  const rate = rates?.eurPerUnit[currency];
  if (currency === "EUR" || !rate) return "";
  const value = amount * rate;
  const euro = new Intl.NumberFormat("en-IE",{style:"currency",currency:"EUR",minimumFractionDigits:2,
    maximumFractionDigits:Math.abs(value)<0.01 ? 6 : Math.abs(value)<1 ? 4 : 2});
  return ` (≈ ${euro.format(value)})`;
}
export function nativePrice(amount:number, currency:string, rates?:ExchangeRates) {
  return unit.format(amount)+" "+currency+equivalent(amount,currency,rates);
}
export function rateSource(rates:ExchangeRates) {
  const date = rates.asOf && new Date(rates.asOf+"T12:00:00Z").toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"});
  return rates.source+(date ? " reference rates · "+date : "");
}
