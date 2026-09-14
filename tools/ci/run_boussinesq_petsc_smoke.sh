#!/usr/bin/env bash
set -euo pipefail

export MPLBACKEND="${MPLBACKEND:-Agg}"

# pytest disarms its own faulthandler at unconfigure, so a native abort raised
# while the interpreter finalizes prints nothing. The variable arms it for the
# whole process and dumps every thread on the way out.
export PYTHONFAULTHANDLER=1

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
  tests/validation/numerical/transient/test_boussinesq_drying_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  -q
