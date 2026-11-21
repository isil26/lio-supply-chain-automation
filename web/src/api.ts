/// <reference types="vite/client" />
import mockData from "./mock/dashboard.json";

export type Source = {
  file?: string;
  source_file?: string;
  page?: number | null;
  quote?: string;
  row?: number | null;
  confidence?: number;
};

export type Readiness = {
  edition: "STD" | "CE";
  percent: number;
  packed: number;
  target: number;
  probability: number;
  p10: number;
  p50: number;
  p90: number;
  firstStop?: string;
  status: string;
  tone: "amber" | "red";
};

export type Risk = {
  rank: number;
  id?: string;
  component: string;
  supplier: string;
  shortfall: string;
  gap?: number;
  required?: number;
  onHand?: number;
  inbound?: number;
  severity: "Critical" | "High" | "Watch";
  detail?: string[];
  evidence: string[];
  sources?: Source[];
};

export type Activity = {
  id: string;
  agent: string;
  action: string;
  time: string;
  type: "analysis" | "sent" | "warning";
};

export type SupplierMessage = {
  sender: string;
  side: "in" | "out";
  text: string;
  time: string;
};

export type SupplierThread = {
  id: string;
  supplier: string;
  subject: string;
  status: string;
  initials: string;
  material?: string;
  qty?: number;
  messages: SupplierMessage[];
};

export type Approval = {
  id: string;
  title: string;
  kind?: string;
  recommendation: string;
  price: number | null;
  currency: string;
  owner: string;
  threshold: string;
  impact: string;
  risk: string;
  deadline: string;
  evidence?: string[];
  status?: string;
  supplier_timing?: { eta_p50: string; eta_p90: string; p_on_time: number; basis: string; sample_count: number } | null;
  expedite?: {
    status: string;
    q_missing: number;
    readiness_scope: string;
    thresholds: { break_even_loss_eur: number | null }[];
    sensitivity: {
      probability_gains: number[];
      break_even_loss_eur: (number | null)[];
      grid: { loss_per_copy_eur: number; net_benefit_eur: number[] }[];
    }[];
  };
};

export type Network = {
  hub: { id: string; name: string; lat: number; lon: number } | null;
  suppliers: { id: string; name: string; city: string; country: string; lat: number; lon: number; atRisk: boolean }[];
  shipments: { id: string; supplier: string; mode: string; status: string; lat: number; lon: number; eta: string; atRisk: boolean }[];
};

export type DashboardData = {
  launch: { name: string; deadline: string; location: string };
  readiness: Readiness[];
  risks: Risk[];
  activity: Activity[];
  threads: SupplierThread[];
  approval: Approval | null;
  options?: Approval[];
  drop: { title: string; detail: string; time: string } | null;
  sync?: { error?: string | null; warnings?: SourceReview[]; pendingDrop?: number; lastSync?: string; detail?: string; mode?: string };
  documentReviews?: SourceReview[];
  dataHealth?: { filesSeen: number; filesParsed: number; needsReview: number; errors: number; lastSyncAgeSeconds: number | null };
  model?: string;
  dataQuality?: { documents?: number; extractionErrors?: number; [key: string]: unknown };
  network?: Network;
};

type SourceReview = { file: string; reason: string };

export type AgentRun = {
  id: string;
  event: string;
  status: string;
  cost: number;
  started?: string;
  finished?: string;
  harness: { ok: boolean; violations: { rule: string; detail: string }[] };
};

export type AgentTraceStep = {
  agent: string;
  tool: string;
  args_summary?: string;
  result_summary?: string;
  reason: string;
  cost: number;
  latency: number;
  citations?: Source[];
  status: string;
};

export type AgentTraceData = {
  steps: AgentTraceStep[];
  approvals_pending: { id: string; title?: string; detail?: string; [key: string]: unknown }[];
};

export interface DashboardApi {
  getDashboard(): Promise<DashboardData>;
  approveDecision(id: string): Promise<{ ok: boolean; status?: string }>;
  reviewDecision(id: string): Promise<{ ok: boolean; status?: string }>;
  sendThread(id: string): Promise<{ ok: boolean }>;
  replyThread(id: string, text: string): Promise<{ ok: boolean }>;
  sync(): Promise<{ ok: boolean }>;
  getSource(path: string): Promise<string>;
  dismissDrop(): Promise<{ ok: true }>;
  resetDemo(): Promise<{ ok: true }>;
  getMeta(): Promise<{ exported?: string; mode?: string }>;
  getAgentRuns(): Promise<AgentRun[]>;
  getAgentTrace(run?: string): Promise<AgentTraceData>;
  runAgent(event?: string): Promise<{ id: string }>;
  stopAgent(id: string): Promise<{ ok: boolean }>;
}

export const hostedReplayBuild = import.meta.env.VITE_SOONY_HOSTED_REPLAY === "1";

export function resetHostedReplay() {
  return json<{ ok: boolean }>("/api/replay/reset", { method: "POST", body: "{}" });
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    if (hostedReplayBuild && response.status === 401) window.location.replace("/");
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.error) message = body.error;
    } catch {}
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

class HttpDashboardApi implements DashboardApi {
  async getDashboard() {
    return json<DashboardData>("/api/dashboard", { cache: "no-store" });
  }
  approveDecision(id: string) {
    return json<{ ok: boolean; status?: string }>(`/api/decisions/${id}/approve`, { method: "POST", body: "{}" });
  }
  reviewDecision(id: string) {
    return json<{ ok: boolean; status?: string }>(`/api/decisions/${id}/review`, { method: "POST", body: "{}" });
  }
  sendThread(id: string) {
    return json<{ ok: boolean }>(`/api/threads/${id}/send`, { method: "POST", body: '{"confirm":true}' });
  }
  replyThread(id: string, text: string) {
    return json<{ ok: boolean }>(`/api/threads/${id}/demo-reply`, { method: "POST", body: JSON.stringify({ text }) });
  }
  sync() {
    return json<{ ok: boolean }>("/api/sync", { method: "POST", body: "{}" });
  }
  async getSource(path: string) {
    const response = await fetch(`/api/source/${path.split("/").map(encodeURIComponent).join("/")}`, { cache: "no-store" });
    if (!response.ok) throw new Error("Source evidence is unavailable");
    return response.text();
  }
  async dismissDrop() {
    return { ok: true as const };
  }
  async resetDemo() {
    return { ok: true as const };
  }
  async getMeta() {
    return {};
  }
  getAgentRuns() {
    return json<AgentRun[]>("/api/agents/runs", { cache: "no-store" });
  }
  getAgentTrace(run?: string) {
    const query = run ? `?run=${encodeURIComponent(run)}` : "";
    return json<AgentTraceData>(`/api/agents/trace${query}`, { cache: "no-store" });
  }
  runAgent(event = "data_drop") {
    return json<{ id: string }>("/api/agents/run", { method: "POST", body: JSON.stringify({ event }) });
  }
  stopAgent(id: string) {
    return json<{ ok: boolean }>("/api/agents/stop", { method: "POST", body: JSON.stringify({ id }) });
  }
}

export class MockDashboardApi implements DashboardApi {
  async getDashboard(): Promise<DashboardData> {
    return structuredClone(mockData) as DashboardData;
  }
  async approveDecision(id: string) { return { ok: true, status: "approved", approvalId: id } as never; }
  async reviewDecision(id: string) { return { ok: true, status: "review", approvalId: id } as never; }
  async sendThread() { return { ok: true }; }
  async replyThread() { return { ok: true }; }
  async sync() { return { ok: true }; }
  async getSource() { return "Mock source evidence"; }
  async dismissDrop() { return { ok: true as const }; }
  async resetDemo() { return { ok: true as const }; }
  async getMeta() { return { mode: "static mock snapshot" }; }
  async getAgentRuns() {
    return [{ id: "mock-art-book", event: "art_book_shortfall", status: "completed", cost: 0, harness: { ok: true, violations: [] } }];
  }
  async getAgentTrace() { return { steps: [], approvals_pending: [] }; }
  async runAgent() { return { id: "mock-art-book" }; }
  async stopAgent() { return { ok: true }; }
}

const STATIC_STORAGE_KEY = "soony-static-sample-v2";

function clone<T>(value: T): T {
  return structuredClone(value);
}

export class StaticDashboardApi implements DashboardApi {
  private before: DashboardData | null = null;
  private after: DashboardData | null = null;
  private state: DashboardData | null = null;

  private async ensureLoaded() {
    if (this.state) return;
    this.before = clone(mockData) as DashboardData;
    this.normalize(this.before);
    this.after = clone(this.before);
    this.after.drop = {
      title: "Staged data drop",
      detail: "Sample replay: staged supplier and receiving evidence is ready.",
      time: "now",
    };
    this.after.activity = [
      { id: "static-drop", agent: "Orchestrator", action: "Applied staged data drop", time: "now", type: "warning" },
      ...this.after.activity,
    ];

    this.normalize(this.after);

    const saved = window.localStorage.getItem(STATIC_STORAGE_KEY);
    if (saved) {
      try {
        this.state = JSON.parse(saved) as DashboardData;
      } catch {
        window.localStorage.removeItem(STATIC_STORAGE_KEY);
      }
    }
    this.state ??= clone(this.before);
  }

  private normalize(data: DashboardData) {
    if (data.approval && !data.approval.id) data.approval.id = "static-plan-b";
    data.threads.forEach((thread, index) => {
      if (index === 0 && /awaiting reply/i.test(thread.status ?? "")) thread.status = "draft";
      if (!thread.status) thread.status = index === 0 ? "draft" : "awaiting reply";
    });
  }

  private persist() {
    if (this.state) window.localStorage.setItem(STATIC_STORAGE_KEY, JSON.stringify(this.state));
  }

  async getDashboard(): Promise<DashboardData> {
    await this.ensureLoaded();
    return clone(this.state!);
  }

  async approveDecision(id: string) {
    await this.ensureLoaded();
    if (this.state?.approval?.id === id) this.state.approval.status = "approved";
    this.state?.options?.forEach((option) => {
      if (option.id === id) option.status = "approved";
    });
    this.persist();
    return { ok: true, status: "approved" };
  }

  async reviewDecision(id: string) {
    await this.ensureLoaded();
    if (this.state?.approval?.id === id) this.state.approval.status = "review";
    this.state?.options?.forEach((option) => {
      if (option.id === id) option.status = "review";
    });
    this.persist();
    return { ok: true, status: "review" };
  }

  async sendThread(id: string) {
    await this.ensureLoaded();
    const thread = this.state?.threads.find((item) => item.id === id);
    if (!thread) return { ok: false };
    thread.status = "awaiting reply";
    thread.messages.push({
      sender: "Chaser",
      side: "out",
      text: "Dry-run send: supplier follow-up prepared and awaiting confirmation.",
      time: "now",
    });
    this.persist();
    return { ok: true };
  }

  async replyThread(id: string, text: string) {
    await this.ensureLoaded();
    const thread = this.state?.threads.find((item) => item.id === id);
    if (!thread) return { ok: false };
    thread.status = "replied";
    thread.messages.push({ sender: "Supplier", side: "in", text, time: "now" });
    this.persist();
    return { ok: true };
  }

  async sync() {
    await this.ensureLoaded();
    this.state = clone(this.after!);
    this.persist();
    return { ok: true };
  }

  async getSource() {
    return "";
  }

  async dismissDrop() {
    if (this.state?.drop) this.state.drop = null;
    this.persist();
    return { ok: true as const };
  }

  async resetDemo() {
    await this.ensureLoaded();
    this.state = clone(this.before!);
    this.persist();
    return { ok: true as const };
  }

  async getMeta() {
    return { mode: "Static sample replay" };
  }
  async getAgentRuns() {
    return [{ id: "recorded-art-book", event: "art_book_shortfall", status: "completed", cost: 0.057892, started: "2026-11-21T15:59:00+01:00", finished: "2026-11-21T16:00:12+01:00", harness: { ok: true, violations: [] } }];
  }
  async getAgentTrace() {
    try {
      const response = await fetch("/snapshot/agent_run.json", { cache: "no-store" });
      if (response.ok) return response.json() as Promise<AgentTraceData>;
    } catch {}
    return { steps: [], approvals_pending: [] };
  }
  async runAgent() { return { id: "recorded-art-book" }; }
  async stopAgent() { return { ok: true }; }
}

const search = new URLSearchParams(window.location.search);
const forcedMock = search.get("mock") === "1";
const forcedStatic = search.get("static") === "1" || import.meta.env.VITE_STATIC === "1";

export function isStaticMode() {
  return !hostedReplayBuild && (forcedStatic || forcedMock);
}

export const dashboardApi: DashboardApi = hostedReplayBuild
  ? new HttpDashboardApi()
  : forcedMock
    ? new MockDashboardApi()
    : forcedStatic
      ? new StaticDashboardApi()
      : new HttpDashboardApi();
