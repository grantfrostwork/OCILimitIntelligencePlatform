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
docker compose -f docker-compose.yml -f docker-compose.arm64.yml up -d
```

Verify the architecture and health checks:

```bash
./deploy/arm64/verify-host.sh
```

Open `http://<public-ip>/` and `http://<public-ip>/grafana/`.

## Validated Configuration

The ARM deployment was validated in `us-ashburn-1` on `VM.Standard.A1.Flex` with 2 OCPUs and 12 GB
memory using `Oracle-Linux-9.7-aarch64-2026.06.15-0`. All six containers reported `aarch64`. A
full instance-principal scan completed successfully across 123 services and 1,814 limits, and the
resulting metrics were published to the bundled ARM64 Prometheus service.

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
