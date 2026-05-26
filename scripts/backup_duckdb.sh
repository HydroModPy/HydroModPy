#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
TARGET="$1"
if [ -z "$TARGET" ]; then
  echo "Usage: $0 path/to/catalog.duckdb"
  exit 2
fi
if [ -f "$TARGET" ]; then
  cp "$TARGET" "${TARGET}.bak-${TS}"
  echo "Backup created: ${TARGET}.bak-${TS}"
else
  echo "No file to backup: $TARGET"
fi
