import {
  Activity,
  AlertTriangle,
  ArrowDownAZ,
  ArrowUpAZ,
  Bell,
  BellOff,
  BellRing,
  CheckSquare,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  FileSearch,
  Filter,
  Globe2,
  Play,
  RefreshCw,
  Save,
  Search,
  Server,
  Timer,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  discoverRegions,
  exportUrl,
  getAlerts,
  getDashboard,
  getLimits,
  getMonitoredRegions,
  getMutedLimits,
  getScanSchedule,
  getScanRuns,
  getServices,
  saveRegionAllowlist,
  saveScanSchedule,
  muteLimit,
  triggerScan,
  triggerRegionScan,
  unmuteLimit,
  uploadBom,
} from "./api";
import type {
  Alert,
  BomDocument,
  Dashboard,
  LimitItem,
  MonitoredRegion,
  ScanEnqueueResult,
  ScanRun,
  ScanSchedule,
} from "./types";

const PAGE_SIZE = 30;
const SCAN_INTERVAL_OPTIONS = [
  { label: "10m", value: 10 },
  { label: "30m", value: 30 },
  { label: "4hr", value: 240 },
  { label: "24hr", value: 1_440 },
  { label: "48hr", value: 2_880 },
];

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

function scanResultMessage(result: ScanEnqueueResult) {
  if (result.queued_regions.length === 0) {
    return `Scans already queued or running for ${result.skipped_regions.join(", ")}.`;
  }
  const queued = `Queued ${result.queued_regions.length} region${result.queued_regions.length === 1 ? "" : "s"}`;
  return result.skipped_regions.length
    ? `${queued}; ${result.skipped_regions.length} already active.`
    : `${queued}.`;
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
  const [mutedLimits, setMutedLimits] = useState<LimitItem[]>([]);
  const [scanRuns, setScanRuns] = useState<ScanRun[]>([]);
  const [scanSchedule, setScanSchedule] = useState<ScanSchedule | null>(null);
  const [monitoredRegions, setMonitoredRegions] = useState<MonitoredRegion[]>([]);
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
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
  const [savingRegions, setSavingRegions] = useState(false);
  const [discoveringRegions, setDiscoveringRegions] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [regionsExpanded, setRegionsExpanded] = useState(false);
  const [alertTab, setAlertTab] = useState<"open" | "muted">("open");
  const [updatingMuteIds, setUpdatingMuteIds] = useState<string[]>([]);
  const [error, setError] = useState("");
  const regionDraftDirty = useRef(false);

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

  const activeScans = scanRuns.filter((item) => item.status === "running");
  const latestScan = activeScans[0] ?? scanRuns[0] ?? dashboard?.last_scan ?? null;
  const queuedRegionCount = monitoredRegions.filter((item) =>
    ["queued", "running"].includes(item.request_status ?? "")
  ).length;
  const scanRunning = activeScans.length > 0 || queuedRegionCount > 0;
  const progress = activeScans.length
    ? activeScans.reduce((total, item) => total + scanProgress(item), 0) / activeScans.length
    : queuedRegionCount > 0
      ? 0
      : scanProgress(latestScan);

  async function refresh(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setError("");
    try {
      const [
        dashboardData,
        limitData,
        alertData,
        mutedData,
        scanData,
        serviceData,
        regionData,
        scheduleData,
      ] = await Promise.all([
        getDashboard(),
        getLimits(queryParams),
        getAlerts(),
        getMutedLimits(),
        getScanRuns(),
        getServices(),
        getMonitoredRegions(),
        getScanSchedule(),
      ]);
      setDashboard(dashboardData);
      setLimits(limitData.items);
      setTotalLimits(limitData.total);
      setAlerts(alertData);
      setMutedLimits(mutedData.items);
      setScanRuns(scanData);
      setServices(serviceData.services);
      setRegions(serviceData.regions);
      setMonitoredRegions(regionData);
      setScanSchedule(scheduleData);
      if (!regionDraftDirty.current) {
        setSelectedRegions(regionData.filter((item) => item.is_enabled).map((item) => item.region_name));
      }
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
    if (!scanRunning) return;
    const timer = window.setInterval(() => {
      refresh(false);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [scanRunning, queryParams]);

  function changeSort(field: string) {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
  }

  async function updateLimitMute(limitItemId: string, shouldMute: boolean) {
    setUpdatingMuteIds((current) => [...current, limitItemId]);
    setError("");
    try {
      if (shouldMute) {
        await muteLimit(limitItemId);
      } else {
        await unmuteLimit(limitItemId);
      }
      await refresh(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update alert mute state.");
    } finally {
      setUpdatingMuteIds((current) => current.filter((item) => item !== limitItemId));
    }
  }

  async function runScan() {
    setScanMessage("Queuing scan...");
    try {
      const result = await triggerScan(region || undefined);
      setScanMessage(scanResultMessage(result));
      setTimeout(() => refresh(false), 1000);
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : "Failed to queue scan.");
    }
  }

  function toggleRegion(regionName: string) {
    regionDraftDirty.current = true;
    setSelectedRegions((current) =>
      current.includes(regionName)
        ? current.filter((item) => item !== regionName)
        : [...current, regionName]
    );
  }

  function selectAllRegions() {
    regionDraftDirty.current = true;
    setSelectedRegions(
      monitoredRegions
        .filter((item) => item.subscription_status === "READY")
        .map((item) => item.region_name)
    );
  }

  async function updateScanSchedule(isEnabled: boolean, intervalMinutes: number) {
    setSavingSchedule(true);
    setError("");
    try {
      const result = await saveScanSchedule(isEnabled, intervalMinutes);
      setScanSchedule(result);
      setScanMessage(
        result.is_enabled
          ? `Automatic scans enabled every ${SCAN_INTERVAL_OPTIONS.find((item) => item.value === result.interval_minutes)?.label ?? `${result.interval_minutes}m`}.`
          : "Automatic scans paused."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update automatic scan schedule.");
    } finally {
      setSavingSchedule(false);
    }
  }

  async function saveRegions() {
    if (selectedRegions.length === 0) {
      setError("Select at least one READY region for scheduled scanning.");
      return;
    }
    setSavingRegions(true);
    setError("");
    try {
      const result = await saveRegionAllowlist(selectedRegions);
      setMonitoredRegions(result);
      setSelectedRegions(result.filter((item) => item.is_enabled).map((item) => item.region_name));
      regionDraftDirty.current = false;
      setScanMessage(`Monitoring ${selectedRegions.length} region${selectedRegions.length === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save region allowlist.");
    } finally {
      setSavingRegions(false);
    }
  }

  async function refreshRegionSubscriptions() {
    setDiscoveringRegions(true);
    setError("");
    try {
      const result = await discoverRegions();
      setMonitoredRegions(result);
      if (!regionDraftDirty.current) {
        setSelectedRegions(result.filter((item) => item.is_enabled).map((item) => item.region_name));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to discover subscribed regions.");
    } finally {
      setDiscoveringRegions(false);
    }
  }

  async function runRegionScan(regionName: string) {
    setScanMessage(`Queuing ${regionName}...`);
    try {
      const result = await triggerRegionScan(regionName);
      setScanMessage(scanResultMessage(result));
      setTimeout(() => refresh(false), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to queue ${regionName}.`);
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
        <div className="brand-block">
          <img
            className="oci-brand-lockup"
            src="/oracle-cloud-infrastructure.png"
            alt="Oracle Cloud Infrastructure"
          />
          <div className="app-identity">
            <h1>OCI Limit Intelligence Platform</h1>
            <p>Service limits, usage, trends, alerts, and BOM readiness for OCI operations.</p>
          </div>
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
            className={`button toggle ${scanSchedule?.is_enabled ? "toggle-active" : ""}`}
            onClick={() =>
              updateScanSchedule(
                !(scanSchedule?.is_enabled ?? false),
                scanSchedule?.interval_minutes ?? 240
              )
            }
            disabled={!scanSchedule || savingSchedule}
          >
            <Timer size={16} />
            {scanSchedule?.is_enabled ? "Auto scan on" : "Auto scan off"}
          </button>
          <label className="refresh-interval">
            <span>Scan interval</span>
            <select
              value={scanSchedule?.interval_minutes ?? 240}
              disabled={!scanSchedule || !scanSchedule.is_enabled || savingSchedule}
              onChange={(event) =>
                updateScanSchedule(true, Number(event.target.value))
              }
            >
              {SCAN_INTERVAL_OPTIONS.map((option) => (
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
          <span>{fmtNumber(dashboard?.muted_limits ?? 0)} muted</span>
        </div>
      </section>

      {latestScan && (
        <section className="scan-progress-panel">
          <div className="scan-progress-heading">
            <div>
              <h2>
                {activeScans.length > 1
                  ? `${activeScans.length} regional scans`
                  : activeScans.length === 1
                    ? "Scan in progress"
                    : queuedRegionCount > 0
                      ? `${queuedRegionCount} regional scan${queuedRegionCount === 1 ? "" : "s"} queued`
                      : "Latest scan"}
              </h2>
              <p>
                {queuedRegionCount > 0 && activeScans.length === 0
                  ? "Waiting for an available regional worker"
                  : `${stageLabel(latestScan.current_stage)} in ${latestScan.region}${
                      latestScan.current_service ? ` · ${latestScan.current_service}` : ""
                    }`}
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
            <span>
              {fmtNumber(latestScan.api_request_count)} API requests · {fmtNumber(latestScan.api_retry_count)} retries
              {latestScan.api_throttle_count > 0
                ? ` · ${fmtNumber(latestScan.api_throttle_count)} throttles`
                : ""}
            </span>
            {latestScan.attempt > 1 && (
              <span>
                Attempt {latestScan.attempt} of {latestScan.max_attempts}
              </span>
            )}
            {latestScan.metrics_publish_status && (
              <span>
                Metrics {stageLabel(latestScan.metrics_publish_status).toLowerCase()}
                {latestScan.metrics_published_at
                  ? ` ${fmtDate(latestScan.metrics_published_at)}`
                  : ""}
              </span>
            )}
          </div>
        </section>
      )}

      <section className="region-panel">
        <div className={`panel-header region-panel-header ${regionsExpanded ? "" : "collapsed"}`}>
          <div>
            <h2>
              <Globe2 size={18} />
              Region coverage
            </h2>
            <p>
              {selectedRegions.length} of{" "}
              {monitoredRegions.filter((item) => item.subscription_status === "READY").length} subscribed regions
              selected for scheduled scans
              {scanSchedule?.is_enabled && scanSchedule.next_scan_at
                ? ` · next scan ${fmtDate(scanSchedule.next_scan_at)}`
                : " · automatic scans paused"}
            </p>
          </div>
          <button
            className="button secondary icon-button region-collapse-button"
            onClick={() => setRegionsExpanded(!regionsExpanded)}
            aria-expanded={regionsExpanded}
            aria-label={regionsExpanded ? "Collapse region coverage" : "Expand region coverage"}
            title={regionsExpanded ? "Collapse region coverage" : "Expand region coverage"}
          >
            {regionsExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
        </div>
        {regionsExpanded && (
          <div className="region-panel-body">
            <div className="region-toolbar">
              <button
                className="button secondary"
                onClick={selectAllRegions}
                disabled={
                  monitoredRegions.filter((item) => item.subscription_status === "READY").length ===
                  selectedRegions.length
                }
              >
                <CheckSquare size={16} />
                Select all
              </button>
              <button
                className="button secondary"
                onClick={refreshRegionSubscriptions}
                disabled={discoveringRegions}
              >
                <RefreshCw size={16} />
                {discoveringRegions ? "Discovering" : "Refresh subscriptions"}
              </button>
              <button className="button primary" onClick={saveRegions} disabled={savingRegions}>
                <Save size={16} />
                {savingRegions ? "Saving" : "Save allowlist"}
              </button>
            </div>
            {monitoredRegions.length ? (
              <div className="region-table-shell">
            <table className="region-table">
              <thead>
                <tr>
                  <th>Monitor</th>
                  <th>Region</th>
                  <th>Subscription</th>
                  <th>Latest scan</th>
                  <th>Progress</th>
                  <th>API activity</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {monitoredRegions.map((item) => {
                  const current = item.latest_scan;
                  const requestActive = ["queued", "running"].includes(item.request_status ?? "");
                  const currentProgress = item.request_status === "queued" ? 0 : scanProgress(current);
                  return (
                    <tr key={item.region_name}>
                      <td>
                        <input
                          className="region-checkbox"
                          type="checkbox"
                          checked={selectedRegions.includes(item.region_name)}
                          disabled={item.subscription_status !== "READY"}
                          aria-label={`Monitor ${item.region_name}`}
                          onChange={() => toggleRegion(item.region_name)}
                        />
                      </td>
                      <td>
                        <strong className="region-name">{item.region_name}</strong>
                        <span>
                          {item.region_key ?? "No region key"}
                          {item.is_home_region ? " · Home / global canonical" : ""}
                        </span>
                      </td>
                      <td>
                        <span className={`region-state state-${item.subscription_status.toLowerCase()}`}>
                          {item.subscription_status}
                        </span>
                        <span>{item.is_enabled ? "Scheduled" : "Not scheduled"}</span>
                      </td>
                      <td>
                        <strong>
                          {item.request_status
                            ? stageLabel(item.request_status)
                            : current
                              ? stageLabel(current.status)
                              : "Never"}
                        </strong>
                        <span>
                          {item.next_attempt_at
                            ? `Next attempt ${fmtDate(item.next_attempt_at)}`
                            : current
                              ? fmtDate(current.ended_at ?? current.started_at)
                              : "No scan history"}
                        </span>
                        {current?.error_summary && <span className="region-error">{current.error_summary}</span>}
                      </td>
                      <td>
                        <div className="region-progress">
                          <span>{Math.round(currentProgress)}%</span>
                          <div>
                            <i style={{ width: `${currentProgress}%` }} />
                          </div>
                        </div>
                      </td>
                      <td>
                        {current ? (
                          <>
                            <strong>{fmtNumber(current.api_request_count)} requests</strong>
                            <span>
                              {fmtNumber(current.api_retry_count)} retries · {fmtNumber(current.api_throttle_count)} throttles
                            </span>
                          </>
                        ) : (
                          <span>No activity</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="button secondary region-scan-button"
                          onClick={() => runRegionScan(item.region_name)}
                          disabled={item.subscription_status !== "READY" || requestActive}
                          title={`Run a scan in ${item.region_name}`}
                        >
                          <Play size={15} />
                          {requestActive
                            ? stageLabel(item.request_status)
                            : current?.status === "failed"
                              ? "Retry"
                              : "Scan"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
              </div>
            ) : (
              <EmptyState title="No regions discovered" detail="Refresh subscriptions to load READY OCI regions." />
            )}
          </div>
        )}
      </section>

      <section className="stat-grid">
        <StatCard
          icon={<Server size={20} />}
          label="Limits scanned"
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
          label="Open alerts"
          value={fmtNumber(alerts.length)}
          detail={latestScan ? `${latestScan.status} scan in ${latestScan.region}` : "Awaiting scan history"}
        />
      </section>

      <section className="workspace-grid">
        <div className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h2>Limit matrix</h2>
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
                    <th className="actions-column">Alerts</th>
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
                      <td className="actions-column">
                        <button
                          className="button secondary icon-button"
                          title={item.is_muted ? "Re-enable alerts for this limit" : "Mute alerts for this limit"}
                          aria-label={item.is_muted ? "Re-enable alerts for this limit" : "Mute alerts for this limit"}
                          disabled={updatingMuteIds.includes(item.id)}
                          onClick={() => updateLimitMute(item.id, !item.is_muted)}
                        >
                          {item.is_muted ? <BellRing size={16} /> : <BellOff size={16} />}
                        </button>
                      </td>
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
                <h2>Top usage</h2>
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
                    <Bar dataKey="usage" fill="#4c825c" radius={[0, 4, 4, 0]} />
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
                <p>Operational signals and exclusions</p>
              </div>
            </div>
            <div className="alert-tabs" role="tablist" aria-label="Alert views">
              <button
                role="tab"
                aria-selected={alertTab === "open"}
                className={alertTab === "open" ? "active" : ""}
                onClick={() => setAlertTab("open")}
              >
                Open <span>{alerts.length}</span>
              </button>
              <button
                role="tab"
                aria-selected={alertTab === "muted"}
                className={alertTab === "muted" ? "active" : ""}
                onClick={() => setAlertTab("muted")}
              >
                Muted <span>{mutedLimits.length}</span>
              </button>
            </div>
            <div className="alert-list">
              {alertTab === "open" && alerts.length ? (
                alerts.slice(0, 6).map((alert) => (
                  <div className={`alert-item alert-${alert.severity}`} key={alert.id}>
                    <div className="alert-item-heading">
                      <strong>{alert.title}</strong>
                      {alert.limit_item_id && (
                        <button
                          className="button secondary icon-button alert-mute-button"
                          title="Mute alerts for this limit"
                          aria-label="Mute alerts for this limit"
                          disabled={updatingMuteIds.includes(alert.limit_item_id)}
                          onClick={() => updateLimitMute(alert.limit_item_id as string, true)}
                        >
                          <BellOff size={15} />
                        </button>
                      )}
                    </div>
                    <p>{alert.message}</p>
                    <span>{fmtDate(alert.last_seen_at)} · {alert.occurrences}x</span>
                  </div>
                ))
              ) : alertTab === "muted" && mutedLimits.length ? (
                mutedLimits.map((item) => (
                  <div className="alert-item alert-muted" key={item.id}>
                    <div className="alert-item-heading">
                      <strong>{item.service_name} / {item.limit_name}</strong>
                      <button
                        className="button secondary restore-alert-button"
                        disabled={updatingMuteIds.includes(item.id)}
                        onClick={() => updateLimitMute(item.id, false)}
                      >
                        <BellRing size={15} />
                        Re-enable
                      </button>
                    </div>
                    <p>
                      {item.region} · {item.scope_type} · {fmtPercent(item.last_percent_used)} used
                    </p>
                    <span>
                      Muted {fmtDate(item.muted_at)}
                      {item.mute_reason ? ` · ${item.mute_reason}` : ""}
                    </span>
                  </div>
                ))
              ) : (
                <EmptyState
                  title={alertTab === "open" ? "No open alerts" : "No muted alerts"}
                  detail={
                    alertTab === "open"
                      ? "Threshold, trend, and scan failures appear here."
                      : "Muted limit alerts can be restored from this tab."
                  }
                />
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header compact">
              <div>
                <h2>Services near capacity</h2>
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
              <h2>BOM analyzer</h2>
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
              <h2>Recent trend changes</h2>
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
                detail="Trend data appears after several scheduled snapshots are collected."
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
