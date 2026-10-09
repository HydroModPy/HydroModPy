#!/usr/bin/env bash
# Delineate a catchment from a DEM with the capability terrain-delineate, as an
# external process: one job directory, one request.json, one JSON document out.
#
#   bash delineate_job.sh dem.tif 389285.910 6816518.749 EPSG:2154
#
# The DEM must be in the projected CRS you name. The outlet is in that CRS.
set -euo pipefail

dem=$(realpath "$1")
x=$2
y=$3
crs=$4
job=$(mktemp -d "${TMPDIR:-/tmp}/hmp-job.XXXXXX")

cat > "$job/request.json" <<JSON
{
  "process": {"id": "terrain-delineate"},
  "inputs": {
    "dem": {"href": "$dem"},
    "outlets": [{"site_id": "outlet", "x": $x, "y": $y}],
    "crs_project": "$crs",
    "snap_distance_m": 150
  }
}
JSON

# stdout is one JSON document, the same as outcome.json. Logs go to stderr.
status=0
hmp process run terrain-delineate --job "$job" > "$job.outcome.json" 2> "$job.log" || status=$?
echo "exit code $status, job directory $job"

# Re-check the sealed directory against its manifest.
hmp process verify --job "$job"
