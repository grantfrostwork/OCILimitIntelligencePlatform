# OCI Ampere A1 Deployment

OCI LIP runs natively on `linux/arm64` without emulating x86. The ARM Compose override pins every
runtime service to ARM64 so a deployment fails during image resolution instead of silently using
emulation.

## Recommended Shape

Use `VM.Standard.A1.Flex` with 2 OCPUs and 12 GB memory.

One x86 OCPU provides two vCPUs, while one A1 OCPU provides one ARM core. Use two A1 OCPUs to keep
roughly the same worker parallelism as the original one-OCPU E4 deployment. Confirm the current
Always Free allocation and available host capacity before creating the instance.

## Host Requirements

- Oracle Linux 9 ARM64 image.
- Public subnet with an Internet Gateway, or private subnet with NAT Gateway egress.
- Inbound TCP 80 from approved clients and TCP 22 from an operator network.
- Outbound TCP 443 to OCI regional service endpoints and container registries.
- Instance principal dynamic-group membership and the policies in `docs/iam.md`.

The supplied `deploy/arm64/cloud-init.yaml` installs native ARM64 Docker CE, Buildx, Docker Compose,
and Git, then prepares `/home/opc/oci-lip/app` for the deployment.

## Configure

Copy the repository to `/home/opc/oci-lip/app`, then create `.env` from `.env.example`. Use the same
long alphanumeric value for `POSTGRES_PASSWORD` and the password component of `DATABASE_URL`. Set
`GRAFANA_ROOT_URL` to the instance URL and provide a long random `GRAFANA_ADMIN_PASSWORD`.

Do not put URL-reserved characters in `POSTGRES_PASSWORD` unless the password in `DATABASE_URL` is
percent encoded.

## Build And Start

Run from `/home/opc/oci-lip/app`:

```bash
docker compose -f docker-compose.yml -f docker-compose.arm64.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.arm64.yml up -d postgres
docker compose -f docker-compose.yml -f docker-compose.arm64.yml run --rm api alembic upgrade head
sudo ./deploy/arm64/install-systemd-service.sh
```

Verify the architecture and health checks:

```bash
./deploy/arm64/verify-host.sh
```

Open `http://<public-ip>/` and `http://<public-ip>/grafana/`.

## Restart And Interruption Recovery

The deployment has two recovery layers:

- Every container uses `restart: unless-stopped`, so Docker restarts a crashed process.
- `oci-lip.service` is enabled at boot and reconstructs the Compose stack after Docker and the
  network are available. It waits for PostgreSQL, the API, worker, Prometheus, Grafana, and frontend
  health checks before reporting success, and retries a failed startup every 15 seconds.

PostgreSQL data, uploads, Prometheus history, and Grafana state remain in named Docker volumes. The
scan schedule and regional allowlist remain in PostgreSQL. When the worker starts, a request that
was running during an interruption is returned to the queue, while the interrupted scan attempt is
retained as failed for auditability. The retried scan creates a new attempt.

The worker receives up to five minutes to finish active work during a controlled shutdown. A sudden
power loss may interrupt the current attempt, but the queue recovery path resumes it after startup.
Container JSON logs rotate at 10 MB with five files per service to prevent log growth from filling
the boot volume.

An explicit `docker stop` or `docker kill` is treated by Docker as an operator action and suppresses
the `unless-stopped` policy. Use `sudo systemctl restart oci-lip.service` to restore an intentionally
stopped container and revalidate the complete stack.

Useful host commands:

```bash
sudo systemctl status oci-lip.service
sudo systemctl restart oci-lip.service
sudo journalctl -u oci-lip.service -n 100 --no-pager
docker compose -f docker-compose.yml -f docker-compose.arm64.yml ps
```

## Validated Configuration

The ARM deployment was validated in `us-ashburn-1` on `VM.Standard.A1.Flex` with 2 OCPUs and 12 GB
memory using `Oracle-Linux-9.7-aarch64-2026.06.15-0`. All six containers reported `aarch64`. A
full instance-principal scan completed successfully across 123 services and 1,814 limits, and the
resulting metrics were published to the bundled ARM64 Prometheus service. Recovery validation
included an unexpected worker-process exit during a scan and a full VM reboot. The worker restarted,
the interrupted request resumed as the next numbered attempt, and the reboot preserved the scan
history, four-hour schedule, Grafana state, and Prometheus time series without manual intervention.

## Migrate From X86

Do not copy the PostgreSQL data directory between CPU architectures. Create a logical backup on the
x86 deployment and restore it into PostgreSQL on A1:

```bash
docker compose exec -T postgres pg_dump -U lip -Fc lip > lip.dump
docker compose exec -T postgres pg_restore -U lip -d lip --clean --if-exists < lip.dump
```

Copy the uploads volume separately. Grafana dashboards are provisioned from the repository, so a new
Grafana volume is sufficient unless local users or settings must be retained. Prometheus history can
start clean; preserve it only when the existing time series are operationally required.

## Multi-Architecture Images

The GitHub workflow builds the backend and frontend for both `linux/amd64` and `linux/arm64`. For a
registry deployment, publish a multi-platform manifest to OCIR and keep the Compose override so the
A1 host selects only ARM64 images.
