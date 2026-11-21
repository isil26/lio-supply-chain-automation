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
}

export const dashboardApi: DashboardApi =
  new URLSearchParams(window.location.search).get("mock") === "1"
    ? new MockDashboardApi()
    : new HttpDashboardApi();
