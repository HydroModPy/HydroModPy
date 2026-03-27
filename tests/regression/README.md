# Regression Tests (Golden References)

## Scope and location

- Canonical non-regression tests are under `tests/regression/`.
- Golden references are under `tests/regression/reference/golden_references/`.
  - `tests/regression/reference/golden_references/fast/`
  - `tests/regression/reference/golden_references/extensive/`
- Two tiers are used:
  - `tests/regression/fast/` for routine checks
  - `tests/regression/extensive/` for deeper end-to-end checks

- Solver-family markers are used across launcher regression variants:
  - `mf6` for MODFLOW 6 / GWT
  - `nwt` for MODFLOW-NWT / MODPATH / MT3DMS

Current non-regression tests:

- `fast/test_launcher_simulation_fast_boussinesq_regression.py`
- `fast/test_launcher_simulation_fast_boussinesq_divide_regression.py`
- `fast/test_launcher_simulation_fast_mf6_regression.py`
- `fast/test_launcher_simulation_fast_nwt_regression.py`
- `extensive/test_launcher_simulation_extensive_mf6_regression.py`
- `extensive/test_launcher_simulation_extensive_nwt_regression.py`
- `extensive/test_launcher_data_overview_regression.py`
- `extensive/test_run_geographic_case_metrics_regression.py`

Notes:

- Analytical and physical benchmark cases now live under `tests/validation/`
  and `validation_cases/`.
- Golden references are no longer meant to be shared between tiers when
  signatures differ.
- Legacy folders `test/` and `test-old/` are no longer part of the active
  test workflow.

## Run tests

Run all regression tests:

```powershell
python -m pytest -m regression -q -n auto
```

Run only fast tier:

```powershell
python -m pytest tests/regression/fast -q -n auto
```

Run only extensive tier:

```powershell
python -m pytest tests/regression/extensive -q -n auto
```

Run only fast tests:

```powershell
python -m pytest -m "regression and fast" -q -n auto
```

Run only extensive tests with marker:

```powershell
python -m pytest -m "regression and extensive" -q -n auto
```

Run only slow tests:

```powershell
python -m pytest -m slow -q -n auto
```

Run only NWT or MF6 launcher regressions:

```powershell
python -m pytest -m "regression and nwt" -q -n auto
python -m pytest -m "regression and mf6" -q -n auto
```

Run one specific test:

```powershell
python -m pytest tests/regression/fast/test_launcher_simulation_fast_boussinesq_regression.py -q -n 1
python -m pytest tests/regression/fast/test_launcher_simulation_fast_boussinesq_divide_regression.py -q -n 1
python -m pytest tests/regression/fast/test_launcher_simulation_fast_mf6_regression.py -q -n 1
python -m pytest tests/regression/fast/test_launcher_simulation_fast_nwt_regression.py -q -n 1
python -m pytest tests/regression/extensive/test_launcher_simulation_extensive_mf6_regression.py -q -n 1
python -m pytest tests/regression/extensive/test_launcher_simulation_extensive_nwt_regression.py -q -n 1
```

Run via the `hmp` CLI:

```powershell
hmp test regression
```

```powershell
hmp test regression --extensive
```

```powershell
hmp test regression --fast
```

```powershell
hmp test regression --slow
```

```powershell
hmp test regression --list
```

```powershell
hmp test regression launcher_simulation_fast_mf6 --fast --mf6 -j 1
```

```powershell
hmp test regression launcher_simulation_fast_nwt --fast --nwt -j 1
```

```powershell
hmp test regression launcher_simulation_extensive_mf6 --extensive --mf6 -j 1
```

```powershell
hmp test regression launcher_simulation_extensive_nwt --extensive --nwt -j 1
```

## Parallel execution (`-n`)

`-n` is provided by `pytest-xdist` and controls how many worker processes run
tests in parallel.

- `-n auto`: use all available CPU cores.
- `-n 4`: force 4 workers.
- `-n 1`: effectively serial execution with the xdist runner.

Examples:

```powershell
python -m pytest -m regression -q -n auto
python -m pytest -m fast -q -n 4
python -m pytest tests/regression/extensive/test_launcher_simulation_extensive_nwt_regression.py -q -n 1
```

## Marker selection (`-m`)

`-m` accepts a boolean expression on test markers.

Operators:

- `and`
- `or`
- `not`
- parentheses `(...)`

Examples:

```powershell
python -m pytest -m "regression and fast" -q
python -m pytest -m "regression and slow" -q
python -m pytest -m extensive -q
python -m pytest -m "regression and fast and mf6" -q
python -m pytest -m "regression and extensive and nwt" -q
python -m pytest -m "regression and not slow" -q
python -m pytest -m "(regression and fast) or slow" -q
```

## Update golden references

Update all golden references:

```powershell
python -m pytest -m regression -q -n auto --update-goldens
```

Update one golden file from one test:

```powershell
python -m pytest tests/regression/fast/test_launcher_simulation_fast_boussinesq_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_launcher_simulation_fast_boussinesq_divide_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_launcher_simulation_fast_mf6_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_launcher_simulation_fast_nwt_regression.py -q --update-goldens
python -m pytest tests/regression/extensive/test_launcher_simulation_extensive_mf6_regression.py -q --update-goldens
python -m pytest tests/regression/extensive/test_launcher_simulation_extensive_nwt_regression.py -q --update-goldens
```

## Notes

- `--update-goldens` is a custom pytest option declared in `tests/conftest.py`.
- Parallel execution requires `pytest-xdist` (`-n auto`).
- MODPATH regression checks rely on `.dbf` snapshots, mainly the `time`
  column statistics.
- CI should execute regression tests without `--update-goldens`.
