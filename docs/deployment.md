# OCI VM Deployment

## Prerequisites

- OCI Linux VM in the target tenancy.
- Instance principal enabled for the VM.
- Docker and Docker Compose installed.
- Security list or NSG allowing HTTPS from approved operator networks.
- Block volume mounted for PostgreSQL data if you do not use the Docker named volume.

## Configure

Create an environment file from `.env.example`:

```bash
cp .env.example .env
```

Use instance principal auth:

```bash
OCI_AUTH_MODE=instance_principal
OCI_TENANCY_OCID=ocid1.tenancy.oc1..aaaaaaaa5trur7whdyytam4nmh3tinrx2yfqnbss6yzz4q6i7gmm2leagnkq
OCI_DEFAULT_REGION=us-ashburn-1
OCI_MAX_SERVICE_WORKERS=6
OCI_MAX_LIMIT_WORKERS=10
OCI_MAX_REGION_WORKERS=2
OCI_GLOBAL_MAX_CONCURRENT_REQUESTS=12
OCI_REGION_STAGGER_SECONDS=15
OCI_REGION_SCAN_MAX_ATTEMPTS=3
OCI_REGION_RETRY_BASE_SECONDS=30
OCI_REGION_RETRY_MAX_SECONDS=300
LIP_ENABLE_NOTIFICATIONS=true
LIP_NOTIFICATION_EMAILS=["grant.frost@oracle.com"]
GRAFANA_ROOT_URL=http://<vm-ip>/grafana/
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<long-random-password>
```

## Start

```bash
docker compose up -d --build
```

Open `http://<vm-ip>`.

On first start, LIP discovers all READY tenancy subscriptions but enables only
`OCI_DEFAULT_REGION`. Use **Region Coverage** in the UI to select the regions that should participate
in scheduled scans, save the allowlist, and then run a manual batch. The allowlist and regional queue
are persisted in PostgreSQL.

Open the provisioned Grafana dashboard at `http://<vm-ip>/grafana/`. Anonymous users receive the
Viewer role. Use the configured administrator account only for datasource troubleshooting or dashboard
development; the version-controlled dashboard is read-only in the UI.

For production, place OCI Load Balancer or NGINX TLS termination in front of the frontend container and restrict inbound access.

The scanner needs outbound TCP 443 access to every selected OCI region. A public-subnet VM with a
public IP should use an Internet Gateway. A private-subnet VM should use a NAT Gateway and a route rule
for `0.0.0.0/0`; a Service Gateway alone does not provide cross-region public endpoint access.

## Backups

Use a cron job or systemd timer:

```bash
docker compose exec -T postgres pg_dump -U lip lip > lip-$(date +%Y%m%d%H%M).sql
oci os object put --namespace idz7dmnfnz71 --bucket-name <backup-bucket> --file lip-*.sql
```

Encrypt the bucket, apply lifecycle retention, and test restore quarterly.

## Health Checks

- API liveness: `/healthz`
- API readiness: `/readyz`
- Prometheus exporter metrics: `/metrics`
- Grafana: `/grafana/`
- Frontend: `/`

## Prometheus and Grafana

The included Prometheus service already scrapes `api:8000/metrics` over the private Compose network.
For an external Prometheus deployment, add the VM as a scrape target:

```yaml
scrape_configs:
  - job_name: oci-lip
    scrape_interval: 5m
    static_configs:
      - targets: ["<vm-ip>:80"]
```

Useful Grafana PromQL queries:

```promql
topk(10, oci_lip_limit_usage_percent)
topk(100, oci_lip_limit_used{service="compute"} > 0)
oci_lip_limit_usage_percent >= on() oci_lip_warning_threshold_percent
time() - oci_lip_scan_last_success_timestamp_seconds
sum by (severity) (oci_lip_alerts_open)
```

Restrict `/metrics` to the Prometheus network at the NSG, load balancer, or reverse proxy when the
application is not intended to expose tenancy metadata publicly.

The bundled Prometheus service has no host port and persists data in `prometheus-data`. Its retention
is bounded to 30 days and 5 GB. Grafana persists its local database in `grafana-data`.

Validate monitoring configuration before deployment:

```bash
docker compose run --rm --no-deps prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose config --quiet
```

## Operations

- Trigger a manual scan from the UI after first deployment.
- Confirm the OCI Notifications email subscription when the email arrives.
- Keep `LIP_ENABLE_NOTIFICATIONS=false` until the topic/subscriber setup is intentional.
- Add only actively used READY regions through the persistent Region Coverage allowlist.
- Rotate `GRAFANA_ADMIN_PASSWORD` through `.env` and recreate only the Grafana container.
- Back up both `prometheus-data` and `grafana-data` with the database backup workflow when dashboard history is operationally important.
