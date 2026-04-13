#!/usr/bin/env bash
set -euo pipefail

export HYDROMODPY_NO_DISPLAY="${HYDROMODPY_NO_DISPLAY:-1}"
export HYDROMODPY_NO_SAVE="${HYDROMODPY_NO_SAVE:-1}"
export MPLBACKEND="${MPLBACKEND:-Agg}"

python - <<'PY'
import platform

from petsc4py import PETSc

print(f"Platform: {platform.platform()}")
print(f"PETSc version: {PETSc.Sys.getVersion()}")
PY

python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py \
  -q
