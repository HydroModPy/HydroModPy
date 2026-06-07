#!/usr/bin/env bash
set -euo pipefail
PROJECT_TOML=${1:-examples/projects/00_getting_started/project.toml}
RUN_ID=${2:-auto_run}
WORKSPACE_DIR=$(dirname "$PROJECT_TOML")
CATALOG="$WORKSPACE_DIR/execution_knowledge/catalog.duckdb"
JSONL="$WORKSPACE_DIR/execution_knowledge/${RUN_ID}/raw/runtime_capture_success.json"

# backup catalog if exists
if [ -f "$CATALOG" ]; then
  ./scripts/backup_duckdb.sh "$CATALOG"
fi

# run capture with logs
PYTHONPATH=. python3 scripts/run_capture_with_logs.py --project-toml "$PROJECT_TOML" --run-id "$RUN_ID" --output-dir "$WORKSPACE_DIR/execution_knowledge/${RUN_ID}/raw"

# validate
python3 scripts/validate_capture.py "$JSONL"

# ingest
PYTHONPATH=. python3 scripts/ingest_runner.py --jsonl "$JSONL" --duckdb "$CATALOG"
echo "Done: ingested $JSONL into $CATALOG"
