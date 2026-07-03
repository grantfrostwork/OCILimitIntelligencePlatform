#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

app_dir=/home/opc/oci-lip/app
unit_source="$app_dir/deploy/arm64/oci-lip.service"

if [[ ! -f "$app_dir/docker-compose.yml" || ! -f "$app_dir/.env" ]]; then
  echo "OCI LIP source and .env must exist in $app_dir before installing the service." >&2
  exit 1
fi

install -m 0644 "$unit_source" /etc/systemd/system/oci-lip.service
systemctl daemon-reload
systemctl enable oci-lip.service
systemctl restart oci-lip.service
systemctl --no-pager --full status oci-lip.service
