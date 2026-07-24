import type {
  Alert,
  AuthUser,
  BomDocument,
  Dashboard,
  LimitItem,
  MonitoredRegion,
  ScanEnqueueResult,
  ScanRun,
  ScanSchedule,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      message = parsed.detail ?? body;
    } catch {
      // Preserve a non-JSON response from the proxy or API.
    }
    throw new ApiError(
      message || `${response.status} ${response.statusText}`,
      response.status
    );
  }
  return response.json() as Promise<T>;
}

export interface LimitQuery {
  service?: string;
  region?: string;
  q?: string;
  level?: string;
  near_limit?: boolean;
  mute_state?: "all" | "active" | "muted";
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

function queryString(params: object) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function getDashboard() {
  return request<Dashboard>("/api/dashboard");
}

export function getCurrentUser() {
  return request<AuthUser>("/api/auth/me");
}

export function signOut() {
  return request<{ status: string }>("/api/auth/logout", { method: "POST" });
}

export function getLimits(params: LimitQuery) {
  return request<{ items: LimitItem[]; total: number; page: number; page_size: number }>(
    `/api/limits${queryString(params)}`
  );
}

export function getServices() {
  return request<{ services: string[]; regions: string[] }>("/api/services");
}

export function getAlerts() {
  return request<Alert[]>("/api/alerts?status=open");
}

export function getMutedLimits() {
  return getLimits({ mute_state: "muted", sort_by: "last_percent_used", page_size: 500 });
}

export function muteLimit(limitItemId: string) {
  return request<LimitItem>(`/api/limits/${encodeURIComponent(limitItemId)}/mute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "Muted from the LIP operations dashboard." }),
  });
}

export function unmuteLimit(limitItemId: string) {
  return request<LimitItem>(`/api/limits/${encodeURIComponent(limitItemId)}/unmute`, {
    method: "POST",
  });
}

export function getScanRuns() {
  return request<ScanRun[]>("/api/scan-runs");
}

export function getScanSchedule() {
  return request<ScanSchedule>("/api/scan-schedule");
}

export function saveScanSchedule(isEnabled: boolean, intervalMinutes: number) {
  return request<ScanSchedule>("/api/scan-schedule", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      is_enabled: isEnabled,
      interval_minutes: intervalMinutes,
    }),
  });
}

export function triggerScan(region?: string) {
  return request<ScanEnqueueResult>(
    `/api/scan-runs${queryString({ region })}`,
    { method: "POST" }
  );
}

export function getMonitoredRegions() {
  return request<MonitoredRegion[]>("/api/regions");
}

export function discoverRegions() {
  return request<MonitoredRegion[]>("/api/regions/discover", { method: "POST" });
}

export function saveRegionAllowlist(regions: string[]) {
  return request<MonitoredRegion[]>("/api/regions/allowlist", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ regions }),
  });
}

export function triggerRegionScan(region: string) {
  return request<ScanEnqueueResult>(`/api/regions/${encodeURIComponent(region)}/scan`, {
    method: "POST",
  });
}

export function uploadBom(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<BomDocument>("/api/bom/analyze", { method: "POST", body: form });
}

export function exportUrl(params: LimitQuery) {
  return `${API_BASE}/api/limits/export${queryString(params)}`;
}
