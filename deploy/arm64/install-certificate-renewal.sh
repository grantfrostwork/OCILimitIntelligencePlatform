#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

app_dir="${LIP_APP_DIR:-/opt/oci-lip}"

if [[ ! -f "$app_dir/docker-compose.yml" || ! -f "$app_dir/.env" ]]; then
  echo "OCI LIP source and .env must exist in $app_dir." >&2
  exit 1
fi

chmod 0750 "$app_dir/deploy/arm64/request-ip-certificate.sh"
chmod 0750 "$app_dir/deploy/arm64/renew-certificate.sh"
install -m 0644 "$app_dir/deploy/arm64/oci-lip-certificate-renew.service" \
  /etc/systemd/system/oci-lip-certificate-renew.service
install -m 0644 "$app_dir/deploy/arm64/oci-lip-certificate-renew.timer" \
  /etc/systemd/system/oci-lip-certificate-renew.timer

systemctl daemon-reload
systemctl enable --now oci-lip-certificate-renew.timer
systemctl --no-pager --full status oci-lip-certificate-renew.timer
