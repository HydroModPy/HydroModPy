#!/usr/bin/env bash
set -euo pipefail

export MPLBACKEND="${MPLBACKEND:-Agg}"

python -m pytest \
  tests/unit/solver/boussinesq/test_boussinesq_method_catalog.py \
  tests/unit/solver/boussinesq/test_boussinesq_smoothing.py \
  tests/unit/solver/boussinesq/test_boussinesq_solver.py \
  tests/unit/solver/boussinesq/test_boussinesq_flow_adapter_build.py \
  tests/unit/solver/boussinesq/test_boussinesq_flow_adapter_run.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/unit/validation/test_hillslope_pulse_overflow_case.py \
  -q

python -m pytest \
  "tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py::test_dupuit_fixed_head_1d_matches_reference_profile[boussinesq]" \
  -q
