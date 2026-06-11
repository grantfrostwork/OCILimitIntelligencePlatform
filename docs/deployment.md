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
LIP_ENABLE_NOTIFICATIONS=true
LIP_NOTIFICATION_EMAILS=["grant.frost@oracle.com"]
```

## Start

```bash
docker compose up -d --build
```

Open `http://<vm-ip>:8080`.

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
- Frontend: `/`

## Operations

- Trigger a manual scan from the UI after first deployment.
- Confirm the OCI Notifications email subscription when the email arrives.
- Keep `LIP_ENABLE_NOTIFICATIONS=false` until the topic/subscriber setup is intentional.
- Expand to all subscribed regions with `OCI_SCAN_ALL_REGIONS=true` after the default-region scan is stable.
