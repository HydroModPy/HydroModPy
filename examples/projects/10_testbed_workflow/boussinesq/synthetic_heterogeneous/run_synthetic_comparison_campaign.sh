#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../../" && pwd)"
PY="${HYDROMODPY_WSL_PYTHON:-/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python}"
CONFIG_DIR="$ROOT/examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous"
OUTPUT_ROOT="$ROOT/examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous"
LOGDIR="$OUTPUT_ROOT/campaign_logs"

mkdir -p "$LOGDIR"

if (($#)); then
  configs=("$@")
else
  configs=(
    compare_synthetic_patchy_mf6_bouss.toml
    compare_synthetic_homogeneous_control_mf6_bouss.toml
    compare_synthetic_patchy_strong_k_mf6_bouss.toml
    compare_synthetic_recharge_pulse_mf6_bouss.toml
    compare_synthetic_small_domain_mf6_bouss.toml
    compare_synthetic_large_domain_mf6_bouss.toml
    compare_synthetic_low_slope_mf6_bouss.toml
    compare_synthetic_high_slope_mf6_bouss.toml
  )
fi

for cfg in "${configs[@]}"; do
  stem="${cfg%.toml}"
  echo "RUN $stem"
  "$PY" -m hydromodpy run "$CONFIG_DIR/$cfg" > "$LOGDIR/$stem.log" 2>&1
  echo "DONE $stem"
done

echo "Logs written under $LOGDIR"
