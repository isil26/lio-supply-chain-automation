import type { AgentRun, AgentTraceData, AgentTraceStep, Source } from "../api";

export type { AgentRun, AgentTraceData, AgentTraceStep, Source };

export const roles = [
  "Triage",
  "Analyst",
  "Verifier",
  "Planner",
  "Chaser",
  "Reader",
  "Interpreter",
  "Briefer",
] as const;
