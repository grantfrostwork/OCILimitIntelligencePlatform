#!/usr/bin/env bash
set -euo pipefail

compose_files=(-f docker-compose.yml -f docker-compose.arm64.yml)

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected an aarch64 host, found $(uname -m)." >&2
  exit 1
fi

docker compose "${compose_files[@]}" config --quiet

for service in api worker frontend postgres prometheus grafana; do
  architecture="$(docker compose "${compose_files[@]}" exec -T "$service" uname -m)"
  if [[ "$architecture" != "aarch64" ]]; then
    echo "$service is running as $architecture instead of aarch64." >&2
    exit 1
  fi
done

curl --fail --silent --show-error http://127.0.0.1/healthz >/dev/null
curl --fail --silent --show-error http://127.0.0.1/readyz >/dev/null
curl --fail --silent --show-error http://127.0.0.1/api/dashboard >/dev/null

echo "OCI LIP is healthy and every runtime service is running on aarch64."
