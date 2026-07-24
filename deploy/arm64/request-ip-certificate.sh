#!/usr/bin/env bash
set -euo pipefail

app_dir="${LIP_APP_DIR:-/opt/oci-lip}"
compose_files=(-f docker-compose.yml -f docker-compose.arm64.yml)
staging=false

if [[ "${1:-}" == "--staging" ]]; then
  staging=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--staging]" >&2
  exit 2
fi

cd "$app_dir"
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${LIP_CERTIFICATE_IP:?Set LIP_CERTIFICATE_IP in .env}"
: "${LETSENCRYPT_EMAIL:?Set LETSENCRYPT_EMAIL in .env}"

cert_name="$LIP_CERTIFICATE_IP"
if [[ "$staging" == "true" ]]; then
  cert_name="${LIP_CERTIFICATE_IP}-staging"
fi
certbot_args=(
  certonly
  --non-interactive
  --agree-tos
  --no-eff-email
  --email "$LETSENCRYPT_EMAIL"
  --preferred-profile shortlived
  --webroot
  --webroot-path /var/www/acme
  --ip-address "$LIP_CERTIFICATE_IP"
  --cert-name "$cert_name"
)

if [[ "$staging" == "true" ]]; then
  certbot_args+=(--staging)
  docker compose "${compose_files[@]}" run --rm certbot "${certbot_args[@]}"
  echo "Staging IP certificate validation succeeded; no certificate was published to OCI."
  exit 0
fi

certbot_args+=(
  --deploy-hook
  "python /opt/oci-lip/certificate_publish.py"
)
docker compose "${compose_files[@]}" run --rm certbot "${certbot_args[@]}"
echo "The trusted IP certificate was issued and published to OCI Certificates."
