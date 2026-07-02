# OCI LIP Architecture

OCI Limit Intelligence Platform is built as a production web application with a UI, API, scanner worker, relational database, direct OCI Python SDK integration, and a Prometheus exporter.

## Runtime Components

- React frontend served by NGINX.
- FastAPI backend for dashboard, limits, alert, scan, and BOM APIs.
- Worker process with a durable regional queue, persistent configurable schedule, and bounded regional executor.
- PostgreSQL for normalized current state, historical snapshots, alerts, audit logs, and BOM analysis.
- OCI Python SDK clients for Limits, Identity, and Notifications.
- Prometheus exposition endpoint backed by persisted limit state.
- Internal Prometheus time-series storage and rule evaluation.
- Grafana Enterprise with provisioned datasource and dashboard definitions.
- OCI Notifications for email alert delivery.

## Data Flow

1. Worker discovers READY regions through `IdentityClient.list_region_subscriptions` and reconciles
   them with the persistent operator allowlist.
2. Worker queues the enabled regions with staggered start times and constructs a `LimitsClient` for
   each regional endpoint.
3. Worker calls `LimitsClient.list_services` in the root tenancy compartment.
4. Worker calls `LimitsClient.list_limit_values` concurrently across services.
5. Worker calls `LimitsClient.get_resource_availability` concurrently across individual limits.
6. Rows are normalized by service, limit, region, scope type, and availability domain.
7. Snapshots are stored, trends are calculated, and alert rules are evaluated.
8. The completed regional batch publishes one timestamped OTLP metric snapshot to the bundled Prometheus service.
9. UI reads dashboard aggregates, regional progress, and matrix rows from the API.
10. BOM uploads are parsed, extracted resources are mapped to scanned limits, and recommendations are persisted.

## SDK Concurrency and Reliability

Each worker thread receives its own regional OCI SDK client and connection pool. The instance-principal
signer is shared and refreshed by the SDK. OCI SDK pagination and default retry behavior are enabled,
with configurable connection and read timeouts.

The collector bounds queued work to twice the worker count. SQLAlchemy writes stay on the scan thread,
and progress is committed in configurable batches. Existing `LimitItem` rows are cached once per scan
to avoid a database query for every OCI response.

Default concurrency is six service-value requests and ten resource-availability requests. These values
operate under a process-wide request semaphore. Regional scans default to two workers, with starts
staggered by 15 seconds. OCI SDK retries use exponential backoff with jitter; failed regional scans
also receive a durable retry timestamp and a bounded number of attempts. Request, retry, HTTP 429,
semaphore wait, and retry-sleep metrics are persisted with every scan. These values should be tuned
conservatively if the tenancy encounters service throttling.

The scan request queue is stored in PostgreSQL. On worker restart, interrupted queue rows are returned
to `queued` and interrupted scan runs are finalized as failed, so a process restart cannot leave the
UI permanently reporting a running scan.

The automatic scan schedule is also stored in PostgreSQL. Supported intervals are 10 minutes,
30 minutes, 4 hours, 24 hours, and 48 hours. The worker evaluates that durable schedule and queues the
current region allowlist when due; no open browser session is required.

## Scope Handling

The collector does not collapse a service limit by name alone. It preserves:

- Region
- Compartment OCID
- Service name
- Limit name
- Scope type
- Availability domain
- Subscription ID, when used later

This is required because OCI returns separate rows for AD, region, and global limits.

The tenancy home region is the canonical source for `GLOBAL` and `TENANCY` scope rows. Those rows are
skipped in other regions to avoid duplicates; region and AD rows continue to be stored under the
regional endpoint that returned them.

## Network Topology

A single VM can reach all OCI regional public service endpoints. In a public subnet, assign a public
IP and route `0.0.0.0/0` through an Internet Gateway. In a private subnet, route outbound traffic
through a NAT Gateway. No inbound access is required for SDK calls, and separate scanner VMs in each
region are unnecessary at the expected request volume. If a future installation consistently reaches
throttling or scan-duration objectives cannot be met with safe concurrency, split workers by region
group while retaining the same PostgreSQL queue.

## Availability API Handling

Some OCI limits return null usage or are unsupported by the resource availability API. LIP stores those rows with `collection_status=unsupported` so they remain visible but do not generate false percentage alerts.

Compute limit values whose allowed value is the string `Dynamic` retain OCI-reported usage when it is
available. Their allowed value, remaining capacity, percentage, trend, and threshold-alert fields stay
unset so LIP never treats `Dynamic` as a numeric quota.

## Prometheus Exporter

`GET /metrics` reads current values from PostgreSQL and never starts a scan. Each limit is labeled by
region, service, limit name, scope, and availability domain. The exporter publishes allowed, used,
available, usage percent, collection status, collection timestamp, scan status/duration/progress, and
open-alert metrics. This stable label model is easier to query than dynamically generated metric names.

After all regional requests in a scan batch complete, the worker converts that persisted exposition
into OTLP protobuf and sends one timestamped snapshot to Prometheus's internal receiver. The only
periodic scrape is the small
`/metrics/health` endpoint every five minutes; it contains exporter and schedule health, not capacity
rows. Prometheus retains no more than 30 days or 5 GB and is not published on a host port. Grafana
queries Prometheus over the same network and is reverse-proxied by the frontend NGINX container under
`/grafana/`. Dashboard auto-refresh is disabled by default because capacity data changes only after a
scan; opening or manually refreshing the dashboard retrieves the newest snapshot.

Dashboard and datasource provisioning are stored under `deploy/grafana`, while scrape and rule files
are stored under `deploy/prometheus`. This keeps the operational view reproducible and reviewable.
Grafana uses a persistent named volume for its database, but the provisioned dashboard remains the
source of truth after container replacement.

## Trend Method

The first implementation uses a linear slope over recent snapshots. It calculates usage velocity per day, estimated time to the configured warning threshold, and a confidence label based on sample count and current threshold state. This is intentionally explainable for operations users.
