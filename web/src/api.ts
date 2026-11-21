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
  sync?: { pendingDrop?: number; lastSync?: string; detail?: string };
  model?: string;
  dataQuality?: { documents?: number; extractionErrors?: number; [key: string]: unknown };
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
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
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
}

const STATIC_STORAGE_KEY = "soony-static-replay-v1";

function clone<T>(value: T): T {
  return structuredClone(value);
}

export class StaticDashboardApi implements DashboardApi {
  private before: DashboardData | null = null;
  private after: DashboardData | null = null;
  private state: DashboardData | null = null;

  private async loadJson(path: string): Promise<DashboardData> {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`Static snapshot unavailable: ${path}`);
    return response.json() as Promise<DashboardData>;
  }

  private async ensureLoaded() {
    if (this.state) return;
    try {
      this.before = await this.loadJson("/snapshot/before.json");
    } catch {
      this.before = clone(mockData) as DashboardData;
    }
    try {
      this.after = await this.loadJson("/snapshot/after.json");
    } catch {
      this.after = clone(mockData) as DashboardData;
      this.after.launch = clone(this.before.launch);
      this.after.drop = {
        title: "Staged data drop",
        detail: "Mock snapshot: staged supplier and receiving evidence is ready.",
        time: "now",
      };
      this.after.activity = [
        { id: "static-drop", agent: "Orchestrator", action: "Applied staged data drop", time: "now", type: "warning" },
        ...this.after.activity,
      ];
    }

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
    try {
      const response = await fetch("/snapshot/meta.json", { cache: "no-store" });
      if (response.ok) return response.json() as Promise<{ exported?: string; mode?: string }>;
    } catch {}
    return { mode: "Static replay snapshot", exported: "frozen mock" };
  }
}

const search = new URLSearchParams(window.location.search);
const forcedMock = search.get("mock") === "1";
const forcedStatic = search.get("static") === "1" || import.meta.env.VITE_STATIC === "1";
const staticApi = new StaticDashboardApi();
const httpApi = new HttpDashboardApi();
let staticMode = forcedStatic || forcedMock;
export function isStaticMode() {
  return staticMode;
}

class HybridDashboardApi implements DashboardApi {
  private get active(): DashboardApi {
    return staticMode ? staticApi : httpApi;
  }
  async getDashboard() {
    if (staticMode) return staticApi.getDashboard();
    try {
      return await httpApi.getDashboard();
    } catch {
      staticMode = true;
      return staticApi.getDashboard();
    }
  }
  approveDecision(id: string) { return this.active.approveDecision(id); }
  reviewDecision(id: string) { return this.active.reviewDecision(id); }
  sendThread(id: string) { return this.active.sendThread(id); }
  replyThread(id: string, text: string) { return this.active.replyThread(id, text); }
  sync() { return this.active.sync(); }
  getSource(path: string) { return this.active.getSource(path); }
  dismissDrop() { return this.active.dismissDrop(); }
  resetDemo() { return staticApi.resetDemo(); }
  getMeta() { return staticMode ? staticApi.getMeta() : httpApi.getMeta(); }
}

export const dashboardApi: DashboardApi = forcedMock
  ? new MockDashboardApi()
  : new HybridDashboardApi();
