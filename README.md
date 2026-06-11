# OCI Limit Intelligence Platform

OCI Limit Intelligence Platform (LIP) is a production-oriented web application for monitoring OCI tenancy service limits, usage, trends, and deployment readiness.

The application is designed to run on an OCI Linux VM with instance principal authentication. Local development defaults to SQLite so the app can be started without provisioning PostgreSQL first.

## Features

- Hourly OCI service limit discovery and resource availability scans.
- Service, region, scope, and limit-level normalization.
- Warning and critical threshold evaluation.
- Historical snapshots and simple linear trend projections.
- OCI Notifications topic/subscription integration for alerts.
- Operations dashboard with filtering, sorting, pagination, export, service drilldown, alerts, and trend cards.
- Bill of Materials upload and analysis for PDF, DOCX, XLSX, CSV, TXT, JSON, and Terraform plan JSON-style files.
- Docker Compose deployment shape with PostgreSQL, Redis, API, worker, and frontend services.

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

Refresh the offline catalog from the authenticated OCI CLI DEFAULT profile:

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
LIP_NOTIFICATION_EMAILS=grant.frost@oracle.com
```

Local development uses `DEFAULT` profile by default.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [IAM policies](docs/iam.md)
