# OCI Limit Intelligence Platform

OCI Limit Intelligence Platform (LIP) is a production-oriented web application for monitoring OCI tenancy service limits, usage, trends, and deployment readiness.

The application is designed to run on an OCI Linux VM with instance principal authentication. Local development defaults to SQLite so the app can be started without provisioning PostgreSQL first.

## Features

- Persistent region allowlist populated from the tenancy's READY region subscriptions.
- Hourly OCI service limit discovery and resource availability scans across selected regions.
- Service, region, scope, and limit-level normalization.
- Warning and critical threshold evaluation.
- Historical snapshots and simple linear trend projections.
- OCI Notifications topic/subscription integration for alerts.
- Operations dashboard with filtering, sorting, pagination, export, service drilldown, alerts, and trend cards.
- Bill of Materials upload and analysis for PDF, DOCX, XLSX, CSV, TXT, JSON, and Terraform plan JSON-style files.
- Direct OCI Python SDK integration with instance-principal authentication, retries, and pagination.
- Bounded regional, service-value, and resource-availability concurrency with staggered starts.
- Exponential backoff with jitter, regional retries, and OCI throttling telemetry.
- Prometheus metrics for every persisted limit plus scanner and alert health.
- Self-hosted Prometheus and Grafana with a provisioned OCI limit operations dashboard.
- Docker Compose deployment with PostgreSQL, API, worker, and frontend services.

## Quick Start

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Bill Comparison Analyzer Tool

The standalone bill comparison analyzer builds an offline OCI service-limit catalog, then maps
AWS bill-comparison rows to OCI limit names without AI calls.

Refresh the offline catalog through the OCI Python SDK using the authenticated `DEFAULT` profile:

```bash
cd "/Users/grafrost/Documents/OCI LIP/backend"
.venv/bin/python -m app.tools.bill_compare_tool refresh-catalog \
  --output app/data/oci_limit_catalog.json
```

Analyze a bill comparison workbook:

```bash
cd "/Users/grafrost/Documents/OCI LIP/backend"
.venv/bin/python -m app.tools.bill_compare_tool analyze \
  --input "/Users/grafrost/Downloads/hackathon bill compare .xlsx" \
  --catalog app/data/oci_limit_catalog.json \
  --output outputs/bill_compare_sample_analysis.json
```

Use `--format csv` when only the mapped requirement rows are needed.

## OCI Runtime Notes

For the deployed VM, set:

```bash
OCI_AUTH_MODE=instance_principal
OCI_TENANCY_OCID=ocid1.tenancy.oc1..aaaaaaaa5trur7whdyytam4nmh3tinrx2yfqnbss6yzz4q6i7gmm2leagnkq
OCI_DEFAULT_REGION=us-ashburn-1
LIP_ENABLE_NOTIFICATIONS=true
LIP_NOTIFICATION_EMAILS=["grant.frost@oracle.com"]
```

The VM uses the OCI Python SDK directly. It does not install or invoke the OCI CLI. Service-value
calls and resource-availability calls are parallelized with `OCI_MAX_SERVICE_WORKERS` and
`OCI_MAX_LIMIT_WORKERS` respectively. Regional scans are controlled by a persistent allowlist in the
**Region Coverage** section of the UI. A new installation enables only `OCI_DEFAULT_REGION`; an
operator must deliberately select and save additional READY regions.

The recommended enterprise defaults are:

```bash
OCI_MAX_REGION_WORKERS=2
OCI_GLOBAL_MAX_CONCURRENT_REQUESTS=12
OCI_REGION_STAGGER_SECONDS=15
OCI_REGION_SCAN_MAX_ATTEMPTS=3
OCI_REGION_RETRY_BASE_SECONDS=30
OCI_REGION_RETRY_MAX_SECONDS=300
```

One VM can scan all subscribed commercial regions by constructing a regional Limits client for each
endpoint. The VM does not need to be deployed in every region. It must have outbound HTTPS access:
use the existing Internet Gateway when it has a public IP in a public subnet, or a NAT Gateway and
`0.0.0.0/0` route when it is private. Keep the allowlist restricted to regions the customer actually
uses to control request volume and scan duration.

Tenancy/global limit rows are collected only from the tenancy home region, which is the canonical
region for those scopes. Region and availability-domain limits remain separate per regional endpoint.

## Prometheus

Prometheus can scrape `http://<vm-ip>/metrics`. The endpoint exports persisted limit state and does
not contact OCI during a scrape. Useful series include:

- `oci_lip_limit_allowed`
- `oci_lip_limit_used`
- `oci_lip_limit_available`
- `oci_lip_limit_usage_percent`
- `oci_lip_limit_collection_status`
- `oci_lip_scan_last_success_timestamp_seconds`
- `oci_lip_scan_last_api_requests`
- `oci_lip_scan_last_api_retries`
- `oci_lip_scan_last_api_throttles`
- `oci_lip_region_enabled`
- `oci_lip_scan_requests`
- `oci_lip_alerts_open`

## Grafana Dashboard

The Docker Compose deployment includes an internal Prometheus server and Grafana Enterprise. Grafana
is exposed through the existing frontend proxy at `http://<vm-ip>/grafana/`; Prometheus is not exposed
on a host port.

The provisioned **OCI Limit Intelligence Platform - Operations** dashboard includes:

- Region, service, scope, availability-domain, and collection-status filters.
- Tenancy risk posture, peak utilization, near-capacity, at-capacity, scan-age, and exporter-health KPIs.
- Highest-utilization limits, per-service risk concentration, historical utilization, and collection health.
- Sorted OCI-reported Compute usage, including usage-only rows whose allowed value is `Dynamic`.
- Scan duration, application alert counts, and Prometheus alert state.

Prometheus scrapes every five minutes and retains up to 30 days or 5 GB of samples. Grafana and Prometheus both use persistent Docker
volumes. Anonymous access is read-only; administrator access requires `GRAFANA_ADMIN_PASSWORD` in
the deployment `.env` file.

Local development uses `DEFAULT` profile by default.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [IAM policies](docs/iam.md)
