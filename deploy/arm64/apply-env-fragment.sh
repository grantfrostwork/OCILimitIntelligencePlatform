#!/usr/bin/env bash
set -euo pipefail

target_file="${1:-/opt/oci-lip/.env}"
fragment_file="${2:-}"

if [[ -z "$fragment_file" || ! -f "$fragment_file" ]]; then
  echo "Usage: $0 [target-env-file] <fragment-env-file>" >&2
  exit 2
fi

if [[ ! -f "$target_file" ]]; then
  echo "Target environment file does not exist: $target_file" >&2
  exit 2
fi

target_dir="$(dirname "$target_file")"
temp_file="$(mktemp "$target_dir/.env.XXXXXX")"
backup_file="${target_file}.backup.$(date -u +%Y%m%dT%H%M%SZ)"

cleanup() {
  rm -f "$temp_file"
}
trap cleanup EXIT

awk '
  NR == FNR {
    if ($0 == "" || $0 ~ /^#/) {
      next
    }
    separator = index($0, "=")
    key = separator > 0 ? substr($0, 1, separator - 1) : $0
    if (separator == 0 || key !~ /^[A-Z_][A-Z0-9_]*$/) {
      print "Invalid environment fragment entry for key: " key > "/dev/stderr"
      invalid = 1
      next
    }
    if (!(key in replacement)) {
      order[++replacement_count] = key
    }
    replacement[key] = $0
    next
  }
  {
    separator = index($0, "=")
    key = separator > 0 ? substr($0, 1, separator - 1) : ""
    if (separator > 0 && key in replacement) {
      print replacement[key]
      applied[key] = 1
    } else {
      print
    }
  }
  END {
    if (invalid) {
      exit 2
    }
    for (i = 1; i <= replacement_count; i++) {
      key = order[i]
      if (!(key in applied)) {
        print replacement[key]
      }
    }
  }
' "$fragment_file" "$target_file" > "$temp_file"

cp -p "$target_file" "$backup_file"
if target_mode="$(stat -c '%a' "$target_file" 2>/dev/null)"; then
  chmod "$target_mode" "$temp_file"
else
  chmod "$(stat -f '%Lp' "$target_file")" "$temp_file"
fi
mv "$temp_file" "$target_file"
trap - EXIT

echo "Updated $target_file; backup stored at $backup_file"
