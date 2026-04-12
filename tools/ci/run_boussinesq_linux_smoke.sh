#!/usr/bin/env bash
set -euo pipefail

export HYDROMODPY_NO_DISPLAY="${HYDROMODPY_NO_DISPLAY:-1}"
export HYDROMODPY_NO_SAVE="${HYDROMODPY_NO_SAVE:-1}"
export MPLBACKEND="${MPLBACKEND:-Agg}"

python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/solver/test_boussinesq_smoothing.py \
  tests/unit/solver/test_boussinesq_backend.py \
  tests/unit/simulation/test_boussinesq_flow_adapter.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/unit/validation/test_hillslope_pulse_overflow_case.py \
  -q

python -m pytest \
  "tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py::test_dupuit_fixed_head_1d_matches_reference_profile[boussinesq]" \
  -q
