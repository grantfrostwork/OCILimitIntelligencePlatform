#!/usr/bin/env bash
set -euo pipefail

timeout_seconds="${1:-300}"
deadline=$((SECONDS + timeout_seconds))
compose=(docker compose -f docker-compose.yml -f docker-compose.arm64.yml)
services=(postgres api worker prometheus grafana frontend)

while ((SECONDS < deadline)); do
  pending=()
  for service in "${services[@]}"; do
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      pending+=("$service:missing")
      continue
    fi

    state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    if [[ "$state" != "running" ]]; then
      pending+=("$service:$state/$health")
    elif [[ "$health" != "healthy" && "$health" != "none" ]]; then
      pending+=("$service:$state/$health")
    fi
  done

  if ((${#pending[@]} == 0)) \
    && curl --fail --silent --show-error http://127.0.0.1/healthz >/dev/null \
    && curl --fail --silent --show-error http://127.0.0.1/readyz >/dev/null \
    && curl --fail --silent --show-error http://127.0.0.1/grafana/api/health >/dev/null; then
    echo "OCI LIP stack is healthy."
    exit 0
  fi

  sleep 5
done

echo "OCI LIP did not become healthy within ${timeout_seconds} seconds." >&2
"${compose[@]}" ps >&2
exit 1
