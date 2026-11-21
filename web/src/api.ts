import mockData from "./mock/dashboard.json";

export type Readiness = {
  edition: "STD" | "CE";
  percent: number;
  packed: number;
  target: number;
  status: string;
  tone: "amber" | "red";
};

export type Risk = {
  rank: number;
  component: string;
  supplier: string;
  shortfall: string;
  severity: "Critical" | "High" | "Watch";
  evidence: string[];
};

export type Activity = {
  id: string;
  agent: string;
  action: string;
  time: string;
  type: "analysis" | "sent" | "warning";
};

export type SupplierThread = {
  id: string;
  supplier: string;
  subject: string;
  status: string;
  initials: string;
  messages: Array<{ sender: string; side: "in" | "out"; text: string; time: string }>;
};

export type Approval = {
  title: string;
  recommendation: string;
  price: number;
  currency: string;
  owner: string;
  threshold: string;
  impact: string;
  risk: string;
  deadline: string;
};

export type DashboardData = {
  launch: { name: string; deadline: string; location: string };
  readiness: Readiness[];
  risks: Risk[];
  activity: Activity[];
  threads: SupplierThread[];
  approval: Approval;
  drop: { title: string; detail: string; time: string };
};

/** Backend contract: replace MockDashboardApi implementation with HTTP calls later. */
export interface DashboardApi {
  getDashboard(): Promise<DashboardData>;
  approveAction(id: string): Promise<{ ok: true; approvalId: string }>;
  dismissDrop(): Promise<{ ok: true }>;
}

export class MockDashboardApi implements DashboardApi {
  async getDashboard(): Promise<DashboardData> {
    return structuredClone(mockData) as DashboardData;
  }

  async approveAction(id: string) {
    return { ok: true as const, approvalId: `approval-${id}-${Date.now()}` };
  }

  async dismissDrop() {
    return { ok: true as const };
  }
}

export const dashboardApi: DashboardApi = new MockDashboardApi();
