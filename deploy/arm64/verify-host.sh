#!/usr/bin/env bash
set -euo pipefail

compose_files=(-f docker-compose.yml -f docker-compose.arm64.yml)

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected an aarch64 host, found $(uname -m)." >&2
  exit 1
fi

docker compose "${compose_files[@]}" config --quiet

for service in api worker frontend postgres prometheus grafana; do
  container_id="$(docker compose "${compose_files[@]}" ps -q "$service")"
  architecture="$(docker compose "${compose_files[@]}" exec -T "$service" uname -m)"
  if [[ "$architecture" != "aarch64" ]]; then
    echo "$service is running as $architecture instead of aarch64." >&2
    exit 1
  fi
  restart_policy="$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$container_id")"
  if [[ "$restart_policy" != "unless-stopped" ]]; then
    echo "$service uses restart policy $restart_policy instead of unless-stopped." >&2
    exit 1
  fi
done

curl --fail --silent --show-error http://127.0.0.1/healthz >/dev/null
curl --fail --silent --show-error http://127.0.0.1/readyz >/dev/null
curl --fail --silent --show-error http://127.0.0.1/api/dashboard >/dev/null

if systemctl list-unit-files oci-lip.service --no-legend 2>/dev/null | grep -q oci-lip.service; then
  systemctl is-enabled --quiet oci-lip.service
  systemctl is-active --quiet oci-lip.service
fi

echo "OCI LIP is healthy and every runtime service is running on aarch64."
