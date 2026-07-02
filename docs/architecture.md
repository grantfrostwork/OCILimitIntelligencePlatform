# OCI LIP Architecture

OCI Limit Intelligence Platform is built as a production web application with a UI, API, scanner worker, relational database, direct OCI Python SDK integration, and a Prometheus exporter.

## Runtime Components

- React frontend served by NGINX.
- FastAPI backend for dashboard, limits, alert, scan, and BOM APIs.
- Worker process that runs scans on a fixed interval.
- PostgreSQL for normalized current state, historical snapshots, alerts, audit logs, and BOM analysis.
- OCI Python SDK clients for Limits, Identity, and Notifications.
- Prometheus exposition endpoint backed by persisted limit state.
- Internal Prometheus time-series storage and rule evaluation.
- Grafana Enterprise with provisioned datasource and dashboard definitions.
- OCI Notifications for email alert delivery.

## Data Flow

1. Worker discovers configured regions through `IdentityClient.list_region_subscriptions`.
2. Worker calls `LimitsClient.list_services` in the root tenancy compartment.
3. Worker calls `LimitsClient.list_limit_values` concurrently across services.
4. Worker calls `LimitsClient.get_resource_availability` concurrently across individual limits.
5. Rows are normalized by service, limit, region, scope type, and availability domain.
6. Snapshots are stored, trends are calculated, and alert rules are evaluated.
7. UI reads dashboard aggregates and matrix rows from the API.
8. BOM uploads are parsed, extracted resources are mapped to scanned limits, and recommendations are persisted.

## SDK Concurrency and Reliability

Each worker thread receives its own regional OCI SDK client and connection pool. The instance-principal
signer is shared and refreshed by the SDK. OCI SDK pagination and default retry behavior are enabled,
with configurable connection and read timeouts.

The collector bounds queued work to twice the worker count. SQLAlchemy writes stay on the scan thread,
and progress is committed in configurable batches. Existing `LimitItem` rows are cached once per scan
to avoid a database query for every OCI response.

Default concurrency is six service-value requests and ten resource-availability requests. These values
should be tuned conservatively if the tenancy encounters service throttling.

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

Prometheus scrapes the API over the private Compose network every five minutes and retains no more than
30 days or 5 GB of samples. It is intentionally not published on a host port. Grafana queries Prometheus
over that same network and is reverse-proxied by the frontend NGINX container under `/grafana/`.

Dashboard and datasource provisioning are stored under `deploy/grafana`, while scrape and rule files
are stored under `deploy/prometheus`. This keeps the operational view reproducible and reviewable.
Grafana uses a persistent named volume for its database, but the provisioned dashboard remains the
source of truth after container replacement.

## Trend Method

The first implementation uses a linear slope over recent snapshots. It calculates usage velocity per day, estimated time to the configured warning threshold, and a confidence label based on sample count and current threshold state. This is intentionally explainable for operations users.
