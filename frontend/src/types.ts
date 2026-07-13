export type Criticality = "normal" | "warning" | "critical" | "error" | "unknown" | "muted";

export interface ScanRun {
  id: string;
  region: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  current_stage: string;
  current_service: string | null;
  services_discovered: number;
  services_scanned: number;
  total_limits_discovered: number;
  limits_scanned: number;
  availability_errors: number;
  trigger: string;
  batch_id: string | null;
  attempt: number;
  max_attempts: number;
  api_request_count: number;
  api_retry_count: number;
  api_throttle_count: number;
  api_concurrency_wait_seconds: number;
  api_retry_sleep_seconds: number;
  global_limits_skipped: number;
  progress_percent: number;
  error_summary: string | null;
  metrics_publish_status: string;
  metrics_published_at: string | null;
  metrics_publish_error: string | null;
}

export interface ScanSchedule {
  is_enabled: boolean;
  interval_minutes: number;
  next_scan_at: string | null;
  last_enqueued_at: string | null;
  allowed_intervals: number[];
  updated_at: string;
}

export interface MonitoredRegion {
  region_name: string;
  region_key: string | null;
  subscription_status: string;
  is_home_region: boolean;
  is_enabled: boolean;
  stagger_order: number;
  latest_scan: ScanRun | null;
  request_status: string | null;
  request_id: string | null;
  next_attempt_at: string | null;
}

export interface ScanEnqueueResult {
  status: string;
  batch_id: string | null;
  regions: string[];
  queued_regions: string[];
  skipped_regions: string[];
}

export interface LimitItem {
  id: string;
  region: string;
  service_name: string;
  limit_name: string;
  resource_name: string | null;
  scope_type: string;
  availability_domain: string | null;
  compartment_ocid: string;
  last_allowed_limit: number | null;
  last_used: number | null;
  last_available: number | null;
  last_percent_used: number | null;
  last_collection_status: string;
  last_collected_at: string | null;
  is_muted: boolean;
  muted_at: string | null;
  mute_reason: string | null;
  criticality: Criticality;
}

export interface Dashboard {
  overall_status: "red" | "yellow" | "green";
  status_reason: string;
  limits_at_capacity: number;
  limits_near_capacity: number;
  total_limits_scanned: number;
  warning_limits: number;
  critical_limits: number;
  muted_limits: number;
  services_near_capacity: { service_name: string; count: number }[];
  top_usage: LimitItem[];
  recent_trends: {
    limit_item_id: string;
    slope_used_per_day: number | null;
    eta_days_to_warning: number | null;
    projected_breach_at: string | null;
    confidence: string;
    summary: string | null;
  }[];
  last_scan: ScanRun | null;
}

export interface Alert {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  message: string;
  status: string;
  service_name: string | null;
  limit_name: string | null;
  region: string | null;
  first_seen_at: string;
  last_seen_at: string;
  occurrences: number;
  limit_item_id: string | null;
}

export interface BomDocument {
  id: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256: string;
  status: string;
  created_at: string;
  items: {
    id: string;
    resource_type: string;
    display_name: string;
    quantity: number;
    unit: string;
    region: string | null;
    service_name: string | null;
    confidence: string;
    assumptions: string[] | null;
  }[];
  recommendations: {
    id: string;
    matching_service: string | null;
    matching_limit_name: string | null;
    current_usage: number | null;
    allowed_limit: number | null;
    available_capacity: number | null;
    required_quantity: number;
    limit_increase_needed: boolean;
    recommended_new_limit: number | null;
    confidence: string;
    explanation: string;
    assumptions: string[] | null;
  }[];
}
