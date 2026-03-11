# Validation Tests

This directory hosts scientific validation tests.

Validation tests answer a different question than regression tests:

- `tests/regression/`: did the software behavior change unexpectedly?
- `tests/validation/`: does the numerical result remain consistent with a
  trusted physical or analytical reference?

Design rules:

- test orchestration lives under `tests/validation/`,
- physical reference cases live under `validation_cases/`,
- reusable case runtime/load/metric helpers live under `validation_cases/shared/`,
- test-only helpers stay under `tests/validation/helpers/`,
- examples stay under `examples/` and remain user-facing workflows.

Current analytical cases:

- `analytical/steady/test_dupuit_fixed_head_1d.py`
- `analytical/steady/test_dupuit_uniform_recharge_1d.py`
- `analytical/steady/test_dupuit_divide_river_1d.py`
- `analytical/steady/test_dupuit_circular_island_ocean_2d.py`
- `analytical/steady/test_boussinesq_fixed_head_piecewise_k_1d.py`
- `analytical/steady/test_boussinesq_uniform_recharge_piecewise_k_1d.py`
- `analytical/steady/test_boussinesq_divide_fixed_head_piecewise_k_1d.py`
- `analytical/steady/test_boussinesq_circular_island_piecewise_k_2d.py`
- `analytical/steady/test_linearized_unconfined_drainage_1d.py`
- `analytical/transient/test_linearized_unconfined_recharge_step_1d.py`
- `analytical/transient/test_linearized_unconfined_boundary_step_1d.py`
- `analytical/transient/test_linearized_unconfined_boundary_piecewise_1d.py`
- `analytical/transient/test_linearized_unconfined_recharge_periodic_1d.py`
- `analytical/transient/test_late_time_unconfined_pumping_2d.py`

Run examples:

```powershell
python -m pytest tests/validation -q
python -m pytest -m validation -q
python -m pytest tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py -q
```
