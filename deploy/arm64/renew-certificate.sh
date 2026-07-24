#!/usr/bin/env bash
set -euo pipefail

app_dir="${LIP_APP_DIR:-/opt/oci-lip}"
compose_files=(-f docker-compose.yml -f docker-compose.arm64.yml)
lock_file=/run/lock/oci-lip-certificate-renew.lock
certbot_args=(
  renew
  --non-interactive
  --no-random-sleep-on-renew
)
dry_run=false

if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
  certbot_args+=(--dry-run)
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--dry-run]" >&2
  exit 2
fi

cd "$app_dir"
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${LIP_CERTIFICATE_IP:?Set LIP_CERTIFICATE_IP in .env}"
certbot_args+=(--cert-name "$LIP_CERTIFICATE_IP")

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "Another certificate renewal is already running." >&2
  exit 0
fi

docker compose "${compose_files[@]}" run --rm certbot "${certbot_args[@]}"
if [[ "$dry_run" == "false" ]]; then
  docker compose "${compose_files[@]}" run --rm --entrypoint python certbot \
    /opt/oci-lip/certificate_publish.py \
    --lineage "/etc/letsencrypt/live/$LIP_CERTIFICATE_IP"
fi
