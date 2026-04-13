#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
OUTPUT_ROOT="${1:-/mnt/c/Users/dreuzy/Documents/HydroModPyOutputs/bouss_multi_linux}"

cd "${REPO_ROOT}"

python3 -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case \
  --solvers boussinesq petsc_partition petsc \
  --forcing-preset strong \
  --output-root "${OUTPUT_ROOT}"
