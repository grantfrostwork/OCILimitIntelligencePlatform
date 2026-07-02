import {
  Activity,
  AlertTriangle,
  ArrowDownAZ,
  ArrowUpAZ,
  Bell,
  Download,
  ExternalLink,
  FileSearch,
  Filter,
  Play,
  RefreshCw,
  Search,
  Server,
  Timer,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  exportUrl,
  getAlerts,
  getDashboard,
  getLimits,
  getScanRuns,
  getServices,
  triggerScan,
  uploadBom,
} from "./api";
import type { Alert, BomDocument, Dashboard, LimitItem, ScanRun } from "./types";

const PAGE_SIZE = 30;
const AUTO_REFRESH_OPTIONS = [
  { label: "5 sec", value: 5_000 },
  { label: "15 sec", value: 15_000 },
  { label: "30 sec", value: 30_000 },
  { label: "1 min", value: 60_000 },
  { label: "5 min", value: 300_000 },
];

function storedAutoRefreshEnabled() {
  try {
    return window.localStorage.getItem("lip:autoRefreshEnabled") === "true";
  } catch {
    return false;
  }
}

function storedAutoRefreshInterval() {
  try {
    const stored = Number(window.localStorage.getItem("lip:autoRefreshIntervalMs"));
    return AUTO_REFRESH_OPTIONS.some((option) => option.value === stored) ? stored : 15_000;
  } catch {
    return 15_000;
  }
}

function fmtNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function fmtPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(1)}%`;
}

function fmtDate(value: string | null | undefined) {
  if (!value) return "n/a";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function stageLabel(value: string | null | undefined) {
  if (!value) return "Queued";
  return value
    .split("_")
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function scanProgress(scan: ScanRun | null) {
  if (!scan) return 0;
  return Math.max(0, Math.min(100, scan.progress_percent ?? 0));
}

function statusLabel(value: Dashboard["overall_status"] | undefined) {
  return (value ?? "green").toUpperCase();
}

function CriticalityBadge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{value}</span>;
}

function StatCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Server size={32} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [limits, setLimits] = useState<LimitItem[]>([]);
  const [totalLimits, setTotalLimits] = useState(0);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [scanRuns, setScanRuns] = useState<ScanRun[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [service, setService] = useState("");
  const [region, setRegion] = useState("");
  const [level, setLevel] = useState("");
  const [query, setQuery] = useState("");
  const [nearLimit, setNearLimit] = useState(false);
  const [sortBy, setSortBy] = useState("last_percent_used");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [scanMessage, setScanMessage] = useState("");
  const [bomDocument, setBomDocument] = useState<BomDocument | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(storedAutoRefreshEnabled);
  const [autoRefreshIntervalMs, setAutoRefreshIntervalMs] = useState(storedAutoRefreshInterval);

  const queryParams = useMemo(
    () => ({
      service,
      region,
      q: query,
      level,
      near_limit: nearLimit,
      sort_by: sortBy,
      sort_dir: sortDir,
      page,
      page_size: PAGE_SIZE,
    }),
    [service, region, query, level, nearLimit, sortBy, sortDir, page]
  );

  const latestScan = scanRuns[0] ?? dashboard?.last_scan ?? null;
  const scanRunning = latestScan?.status === "running";
  const progress = scanProgress(latestScan);

  async function refresh(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setError("");
    try {
      const [dashboardData, limitData, alertData, scanData, serviceData] = await Promise.all([
        getDashboard(),
        getLimits(queryParams),
        getAlerts(),
        getScanRuns(),
        getServices(),
      ]);
      setDashboard(dashboardData);
      setLimits(limitData.items);
      setTotalLimits(limitData.total);
      setAlerts(alertData);
      setScanRuns(scanData);
      setServices(serviceData.services);
      setRegions(serviceData.regions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load LIP data.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [queryParams]);

  useEffect(() => {
    try {
      window.localStorage.setItem("lip:autoRefreshEnabled", String(autoRefreshEnabled));
      window.localStorage.setItem("lip:autoRefreshIntervalMs", String(autoRefreshIntervalMs));
    } catch {
      // Local storage can be disabled; the controls still work for the current session.
    }
  }, [autoRefreshEnabled, autoRefreshIntervalMs]);

  useEffect(() => {
    if (!autoRefreshEnabled) return;
    const timer = window.setInterval(() => {
      refresh(false);
    }, autoRefreshIntervalMs);
    return () => window.clearInterval(timer);
  }, [autoRefreshEnabled, autoRefreshIntervalMs, queryParams]);

  function changeSort(field: string) {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
  }

  async function runScan() {
    if (scanRunning) {
      setScanMessage(`Scan already running in ${latestScan.region}.`);
      return;
    }
    setScanMessage("Queuing scan...");
    try {
      const result = await triggerScan(region || undefined);
      setScanMessage(
        result.status === "already_running"
          ? `Scan already running in ${result.region}.`
          : autoRefreshEnabled
            ? `Scan queued for ${result.region}. Progress will update on the selected interval.`
            : `Scan queued for ${result.region}. Use Refresh or enable auto-refresh to update progress.`
      );
      setTimeout(() => refresh(false), 1000);
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : "Failed to queue scan.");
    }
  }

  async function handleUpload(file: File | null) {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const result = await uploadBom(file);
      setBomDocument(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "BOM analysis failed.");
    } finally {
      setUploading(false);
    }
  }

  const chartData =
    dashboard?.top_usage.map((item) => ({
      name: item.limit_name.length > 22 ? `${item.limit_name.slice(0, 22)}...` : item.limit_name,
      usage: Number((item.last_percent_used ?? 0).toFixed(1)),
      service: item.service_name,
    })) ?? [];

  const pageCount = Math.max(1, Math.ceil(totalLimits / PAGE_SIZE));
  const activeFilters = [service, region, level, query, nearLimit ? "near limit" : ""].filter(Boolean);

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>OCI Limit Intelligence Platform</h1>
          <p>Service limits, usage, trends, alerts, and BOM readiness for OCI operations.</p>
        </div>
        <div className="topbar-actions">
          <a className="button secondary" href="/grafana/" target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            Grafana
          </a>
          <button className="button secondary" onClick={() => refresh()} disabled={loading}>
            <RefreshCw size={16} />
            Refresh
          </button>
          <button
            className={`button toggle ${autoRefreshEnabled ? "toggle-active" : ""}`}
            onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)}
          >
            <Timer size={16} />
            {autoRefreshEnabled ? "Auto refresh on" : "Auto refresh off"}
          </button>
          <label className="refresh-interval">
            <span>Interval</span>
            <select
              value={autoRefreshIntervalMs}
              disabled={!autoRefreshEnabled}
              onChange={(event) => setAutoRefreshIntervalMs(Number(event.target.value))}
            >
              {AUTO_REFRESH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button className="button primary" onClick={runScan} disabled={scanRunning}>
            <Play size={16} />
            {scanRunning ? "Scan running" : "Run scan"}
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {scanMessage && <div className="info-banner">{scanMessage}</div>}

      <section className={`status-banner status-${dashboard?.overall_status ?? "green"}`}>
        <div>
          <span>Tenancy Limit Status</span>
          <strong>{statusLabel(dashboard?.overall_status)}</strong>
        </div>
        <p>{dashboard?.status_reason ?? "No persisted limit risk has been loaded yet."}</p>
        <div className="status-counts">
          <span>{fmtNumber(dashboard?.limits_at_capacity ?? 0)} at capacity</span>
          <span>{fmtNumber(dashboard?.limits_near_capacity ?? 0)} near limit</span>
        </div>
      </section>

      {latestScan && (
        <section className="scan-progress-panel">
          <div className="scan-progress-heading">
            <div>
              <h2>{scanRunning ? "Scan In Progress" : "Latest Scan"}</h2>
              <p>
                {stageLabel(latestScan.current_stage)} in {latestScan.region}
                {latestScan.current_service ? ` · ${latestScan.current_service}` : ""}
              </p>
            </div>
            <strong>{Math.round(progress)}%</strong>
          </div>
          <div className="scan-progress-track">
            <div style={{ width: `${progress}%` }} />
          </div>
          <div className="scan-progress-meta">
            <span>
              {fmtNumber(latestScan.limits_scanned)} /{" "}
              {latestScan.total_limits_discovered
                ? fmtNumber(latestScan.total_limits_discovered)
                : "discovering"}{" "}
              limits
            </span>
            <span>
              {fmtNumber(latestScan.services_scanned)} / {fmtNumber(latestScan.services_discovered)} services
            </span>
            <span>
              Started {fmtDate(latestScan.started_at)}
              {latestScan.ended_at ? ` · ended ${fmtDate(latestScan.ended_at)}` : ""}
            </span>
            {latestScan.availability_errors > 0 && (
              <span>{fmtNumber(latestScan.availability_errors)} collection errors</span>
            )}
          </div>
        </section>
      )}

      <section className="stat-grid">
        <StatCard
          icon={<Server size={20} />}
          label="Limits Scanned"
          value={fmtNumber(dashboard?.total_limits_scanned ?? 0)}
          detail={
            dashboard?.last_scan
              ? `${stageLabel(dashboard.last_scan.current_stage)} ${fmtDate(
                  dashboard.last_scan.ended_at ?? dashboard.last_scan.started_at
                )}`
              : "No scan yet"
          }
        />
        <StatCard
          icon={<AlertTriangle size={20} />}
          label="Warning"
          value={fmtNumber(dashboard?.warning_limits ?? 0)}
          detail="At or above configured warning threshold"
        />
        <StatCard
          icon={<Bell size={20} />}
          label="Critical"
          value={fmtNumber(dashboard?.critical_limits ?? 0)}
          detail="At or above configured critical threshold"
        />
        <StatCard
          icon={<Activity size={20} />}
          label="Open Alerts"
          value={fmtNumber(alerts.length)}
          detail={latestScan ? `${latestScan.status} scan in ${latestScan.region}` : "Awaiting scan history"}
        />
      </section>

      <section className="workspace-grid">
        <div className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h2>Limit Matrix</h2>
              <p>{activeFilters.length ? `Filtered by ${activeFilters.join(", ")}` : "All discovered limit rows"}</p>
            </div>
            <a className="button secondary" href={exportUrl(queryParams)}>
              <Download size={16} />
              Export
            </a>
          </div>

          <div className="filters">
            <label className="search-box">
              <Search size={16} />
              <input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="Search limits or services"
              />
            </label>
            <label>
              <span>Service</span>
              <select
                value={service}
                onChange={(event) => {
                  setService(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">All services</option>
                {services.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Region</span>
              <select
                value={region}
                onChange={(event) => {
                  setRegion(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">All regions</option>
                {regions.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Level</span>
              <select
                value={level}
                onChange={(event) => {
                  setLevel(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">All levels</option>
                <option value="critical">Critical</option>
                <option value="warning">Warning</option>
                <option value="normal">Normal</option>
                <option value="unknown">Unknown</option>
                <option value="error">Error</option>
              </select>
            </label>
            <button
              className={`button toggle ${nearLimit ? "toggle-active" : ""}`}
              onClick={() => {
                setNearLimit(!nearLimit);
                setPage(1);
              }}
            >
              <Filter size={16} />
              Near limit
            </button>
          </div>

          {limits.length === 0 && !loading ? (
            <EmptyState
              title="No limit rows found"
              detail="Run a scan or clear filters to populate the matrix."
            />
          ) : (
            <div className="table-shell">
              <table>
                <thead>
                  <tr>
                    <th onClick={() => changeSort("service_name")}>Service {sortBy === "service_name" && sortDirIcon(sortDir)}</th>
                    <th onClick={() => changeSort("limit_name")}>Limit {sortBy === "limit_name" && sortDirIcon(sortDir)}</th>
                    <th onClick={() => changeSort("last_used")}>Current {sortBy === "last_used" && sortDirIcon(sortDir)}</th>
                    <th onClick={() => changeSort("last_allowed_limit")}>Allowed {sortBy === "last_allowed_limit" && sortDirIcon(sortDir)}</th>
                    <th onClick={() => changeSort("last_percent_used")}>Used {sortBy === "last_percent_used" && sortDirIcon(sortDir)}</th>
                    <th onClick={() => changeSort("last_available")}>Remaining {sortBy === "last_available" && sortDirIcon(sortDir)}</th>
                    <th>Scope</th>
                    <th>Status</th>
                    <th onClick={() => changeSort("last_collected_at")}>Updated {sortBy === "last_collected_at" && sortDirIcon(sortDir)}</th>
                  </tr>
                </thead>
                <tbody>
                  {limits.map((item) => (
                    <tr key={item.id} className={`row-${item.criticality}`}>
                      <td>{item.service_name}</td>
                      <td>
                        <strong>{item.limit_name}</strong>
                        {item.availability_domain && <span>{item.availability_domain}</span>}
                      </td>
                      <td>{fmtNumber(item.last_used)}</td>
                      <td>{fmtNumber(item.last_allowed_limit)}</td>
                      <td>
                        <div className="usage-cell">
                          <span>{fmtPercent(item.last_percent_used)}</span>
                          <div className="usage-bar">
                            <div style={{ width: `${Math.min(item.last_percent_used ?? 0, 100)}%` }} />
                          </div>
                        </div>
                      </td>
                      <td>{fmtNumber(item.last_available)}</td>
                      <td>
                        {item.region}
                        <span>{item.scope_type}</span>
                      </td>
                      <td>
                        <CriticalityBadge value={item.criticality} />
                      </td>
                      <td>{fmtDate(item.last_collected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="pagination">
            <span>
              Page {page} of {pageCount} · {fmtNumber(totalLimits)} rows
            </span>
            <div>
              <button className="button secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <button
                className="button secondary"
                disabled={page >= pageCount}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </div>

        <aside className="side-stack">
          <div className="panel">
            <div className="panel-header compact">
              <div>
                <h2>Top Usage</h2>
                <p>Highest percent used</p>
              </div>
            </div>
            {chartData.length ? (
              <div className="chart">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => `${value}%`} />
                    <YAxis dataKey="name" type="category" width={132} />
                    <Tooltip />
                    <Bar dataKey="usage" fill="#2f7f6f" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState title="No chart data" detail="Scanned rows with usage percentages appear here." />
            )}
          </div>

          <div className="panel">
            <div className="panel-header compact">
              <div>
                <h2>Alerts</h2>
                <p>Open operational signals</p>
              </div>
            </div>
            <div className="alert-list">
              {alerts.length ? (
                alerts.slice(0, 6).map((alert) => (
                  <div className={`alert-item alert-${alert.severity}`} key={alert.id}>
                    <strong>{alert.title}</strong>
                    <p>{alert.message}</p>
                    <span>{fmtDate(alert.last_seen_at)} · {alert.occurrences}x</span>
                  </div>
                ))
              ) : (
                <EmptyState title="No open alerts" detail="Threshold, trend, and scan failures appear here." />
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header compact">
              <div>
                <h2>Services Near Capacity</h2>
                <p>Grouped by service</p>
              </div>
            </div>
            <div className="service-risk-list">
              {dashboard?.services_near_capacity.length ? (
                dashboard.services_near_capacity.map((item) => (
                  <button key={item.service_name} onClick={() => setService(item.service_name)}>
                    <span>{item.service_name}</span>
                    <strong>{item.count}</strong>
                  </button>
                ))
              ) : (
                <EmptyState title="No service risks" detail="Services above threshold appear here." />
              )}
            </div>
          </div>
        </aside>
      </section>

      <section className="lower-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>BOM Analyzer</h2>
              <p>Upload planned OCI resources and compare them to scanned limits.</p>
            </div>
            <label className="button primary file-button">
              <Upload size={16} />
              {uploading ? "Analyzing" : "Upload"}
              <input
                type="file"
                accept=".pdf,.docx,.xlsx,.csv,.txt,.json,.tfplan"
                onChange={(event) => handleUpload(event.target.files?.[0] ?? null)}
              />
            </label>
          </div>
          {bomDocument ? (
            <div className="bom-results">
              <div>
                <FileSearch size={18} />
                <strong>{bomDocument.filename}</strong>
                <span>{bomDocument.items.length} detected items</span>
              </div>
              <div className="recommendation-list">
                {bomDocument.recommendations.map((item) => (
                  <div key={item.id} className={item.limit_increase_needed ? "recommendation needs-increase" : "recommendation"}>
                    <strong>
                      {item.matching_service ?? "Manual review"} / {item.matching_limit_name ?? "unmapped"}
                    </strong>
                    <p>{item.explanation}</p>
                    <span>
                      Required {fmtNumber(item.required_quantity)}
                      {item.recommended_new_limit
                        ? ` · recommended new limit ${fmtNumber(item.recommended_new_limit)}`
                        : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState
              title="No BOM analyzed"
              detail="Supported files include PDF, DOCX, XLSX, CSV, JSON, text, and Terraform plan JSON."
            />
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Recent Trend Changes</h2>
              <p>Projected movement toward configured threshold.</p>
            </div>
          </div>
          <div className="trend-list">
            {dashboard?.recent_trends.length ? (
              dashboard.recent_trends.map((trend) => (
                <div className="trend-item" key={`${trend.limit_item_id}-${trend.projected_breach_at}`}>
                  <strong>{trend.summary ?? "Trend calculated"}</strong>
                  <span>
                    {trend.eta_days_to_warning === null
                      ? "No projected breach"
                      : `${trend.eta_days_to_warning.toFixed(1)} days to warning`}
                    {" · "}
                    {trend.confidence} confidence
                  </span>
                </div>
              ))
            ) : (
              <EmptyState
                title="No trend projections"
                detail="Trend data appears after several hourly snapshots are collected."
              />
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

function sortDirIcon(direction: "asc" | "desc") {
  return direction === "asc" ? <ArrowUpAZ size={13} /> : <ArrowDownAZ size={13} />;
}
