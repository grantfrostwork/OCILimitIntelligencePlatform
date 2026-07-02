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

Open the provisioned Grafana dashboard at `http://<vm-ip>/grafana/`. Anonymous users receive the
Viewer role. Use the configured administrator account only for datasource troubleshooting or dashboard
development; the version-controlled dashboard is read-only in the UI.

For production, place OCI Load Balancer or NGINX TLS termination in front of the frontend container and restrict inbound access.

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
- Expand to all subscribed regions with `OCI_SCAN_ALL_REGIONS=true` after the default-region scan is stable.
- Rotate `GRAFANA_ADMIN_PASSWORD` through `.env` and recreate only the Grafana container.
- Back up both `prometheus-data` and `grafana-data` with the database backup workflow when dashboard history is operationally important.
