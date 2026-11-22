import type { Activity, Source } from "../api";
import { roles } from "./types";

export type Team = "Operations" | "Specialists";
export type Agent = { name: string; role: string; icon: string; tone: string };

const operations: Agent[] = [
  { name: "Data Bridge", role: "Picks up new and changed files from the supplier portal.", icon: "bridge", tone: "sky" },
  { name: "Document Agent", role: "Reads supplier documents and ties findings to their source.", icon: "document", tone: "sky" },
  { name: "Readiness Engine", role: "Forecasts packing capacity from usable stock and expected arrivals.", icon: "pulse", tone: "sage" },
  { name: "Decision Copilot", role: "Compares recovery options and checks who can approve them.", icon: "branch", tone: "lilac" },
  { name: "Approvals", role: "Checks delegations and routes decisions for sign-off.", icon: "shield", tone: "lilac" },
  { name: "Supplier Recovery", role: "Finds alternative supply when a delivery falls short.", icon: "recover", tone: "amber" },
  { name: "Supplier Loop", role: "Tracks supplier commitments through the next decision.", icon: "loop", tone: "amber" },
  { name: "Supplier Chaser", role: "Requests evidence and follows up on outstanding replies.", icon: "signal", tone: "sage" },
  { name: "Mail Agent", role: "Prepares supplier replies and dispatches eligible messages.", icon: "mail", tone: "sage" },
];

const specialistDetails: Record<typeof roles[number], [string, string, string]> = {
  Triage: ["Routes each launch exception to the right specialists.", "branch", "lilac"],
  Analyst: ["Finds stock gaps and contradictions in the evidence.", "pulse", "sky"],
  Verifier: ["Checks claims against independent source documents.", "shield", "sage"],
  Planner: ["Models recovery options and their break-even points.", "plan", "lilac"],
  Chaser: ["Drafts the next supplier request for a launch exception.", "signal", "sage"],
  Reader: ["Extracts cited facts from supplier documents.", "document", "sky"],
  Interpreter: ["Turns supplier replies into structured commitments.", "interpret", "amber"],
  Briefer: ["Summarises the evidence and open decisions for review.", "brief", "amber"],
};

export const teams: Record<Team, Agent[]> = {
  Operations: operations,
  Specialists: roles.map(name => {
    const [role, icon, tone] = specialistDetails[name];
    return { name, role, icon, tone };
  }),
};

const aliases: Record<string, string> = {
  "truth agent": "Readiness Engine", "auto approve": "Approvals", "simulated approval": "Approvals",
  "reply interpreter": "Interpreter", "document reader": "Reader", "supplier chaser agent": "Supplier Chaser",
};
const catalog = new Map(Object.values(teams).flat().map(agent => [agent.name.toLowerCase(), agent]));

export function findAgent(name: string) {
  const key = name.toLowerCase().replace(/[_-]/g, " ").trim();
  return catalog.get(aliases[key]?.toLowerCase() ?? key);
}

export type Signal = { id: string; agent: Agent; message: string; time: string; at: number; sources?: Source[] };

export function activitySignals(activity: Activity[]): Signal[] {
  const unique = new Map<string, Signal>();
  for (const item of activity) {
    const agent = findAgent(item.agent);
    if (!agent) continue;
    const at = Date.parse(item.timestamp ?? "");
    const message = item.action === "model: final" ? "Completed the task." : item.action;
    const citation = typeof item.citation === "string" ? {quote: item.citation} : item.citation;
    unique.set(item.id, { id: item.id, agent, message, time: item.time,
      at: Number.isFinite(at) ? at : 0,
      sources: citation?.file || citation?.source_file || citation?.quote ? [citation] : undefined });
  }
  return [...unique.values()].sort((a, b) => b.at - a.at);
}
