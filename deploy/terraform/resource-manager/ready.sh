#!/usr/bin/env bash
set -euo pipefail
compose=(docker compose -f docker-compose.yml -f docker-compose.arm64.yml)
for attempt in {1..120}; do
  healthy=true
  for service in postgres api worker prometheus grafana frontend; do
    id=$("${compose[@]}" ps -q "$service")
    if [[ -z "$id" ]] || [[ $(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id") != healthy ]]; then
      healthy=false
    fi
  done
  if $healthy && curl -fsS http://127.0.0.1/readyz >/dev/null; then
    echo 'Containers healthy. Complete public TLS, real SSO and email acceptance checks.'
    exit 0
  fi
  sleep 5
done
echo 'Application readiness failed. Inspect docker compose ps and logs.' >&2
exit 1
