# OCI LIP Architecture

OCI Limit Intelligence Platform is built as a small production web application with a UI, API, scanner worker, relational database, and OCI CLI integration layer.

## Runtime Components

- React frontend served by NGINX.
- FastAPI backend for dashboard, limits, alert, scan, and BOM APIs.
- Worker process that runs scans on a fixed interval.
- PostgreSQL for normalized current state, historical snapshots, alerts, audit logs, and BOM analysis.
- OCI CLI invoked by the backend and worker with subprocess timeouts and JSON parsing.
- OCI Notifications for email alert delivery.

## Data Flow

1. Worker discovers configured regions.
2. Worker runs `oci limits service list` in the root tenancy compartment.
3. For each service, worker runs `oci limits value list`.
4. For each limit row, worker runs `oci limits resource-availability get`.
5. Rows are normalized by service, limit, region, scope type, and availability domain.
6. Snapshots are stored, trends are calculated, and alert rules are evaluated.
7. UI reads dashboard aggregates and matrix rows from the API.
8. BOM uploads are parsed, extracted resources are mapped to scanned limits, and recommendations are persisted.

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

## Trend Method

The first implementation uses a linear slope over recent snapshots. It calculates usage velocity per day, estimated time to the configured warning threshold, and a confidence label based on sample count and current threshold state. This is intentionally explainable for operations users.
