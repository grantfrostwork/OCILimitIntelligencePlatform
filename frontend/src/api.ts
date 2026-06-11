import type { Alert, BomDocument, Dashboard, LimitItem, ScanRun } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export interface LimitQuery {
  service?: string;
  region?: string;
  q?: string;
  level?: string;
  near_limit?: boolean;
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

export function getScanRuns() {
  return request<ScanRun[]>("/api/scan-runs");
}

export function triggerScan(region?: string) {
  return request<{ status: string; region: string; scan_id: string | null }>(
    `/api/scan-runs${queryString({ region })}`,
    { method: "POST" }
  );
}

export function uploadBom(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<BomDocument>("/api/bom/analyze", { method: "POST", body: form });
}

export function exportUrl(params: LimitQuery) {
  return `${API_BASE}/api/limits/export${queryString(params)}`;
}
