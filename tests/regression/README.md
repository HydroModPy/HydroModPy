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
- Solver intercomparison tests use the `intercomparison` marker. They compare
  the compact profiles two solvers give on one validation case, not figure
  files or full solver workspaces.

Current non-regression tests:

- `fast/test_simulation_regression_fast_boussinesq_regression.py`
- `fast/test_simulation_regression_fast_boussinesq_divide_regression.py`
- `fast/test_simulation_regression_fast_mf6_regression.py`
- `fast/test_simulation_regression_fast_nwt_regression.py`
- `fast/intercomparison/test_mf6_support_intercomparison_fast_regression.py`
- `fast/intercomparison/test_xt3d_irregular_tri_fast_regression.py`
- `extensive/test_simulation_regression_extensive_mf6_regression.py`
- `extensive/test_simulation_regression_extensive_nwt_regression.py`
- `extensive/test_launcher_data_overview_regression.py`
- `extensive/test_run_geographic_case_regression.py`

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

Run only solver intercomparisons:

```powershell
python -m pytest -m "regression and intercomparison" -q -n auto
python -m tools.dev test regression --fast --intercomparison -j 1
```

Run one specific test:

```powershell
python -m pytest tests/regression/fast/test_simulation_regression_fast_boussinesq_regression.py -q -n 1
python -m pytest tests/regression/fast/test_simulation_regression_fast_boussinesq_divide_regression.py -q -n 1
python -m pytest tests/regression/fast/test_simulation_regression_fast_mf6_regression.py -q -n 1
python -m pytest tests/regression/fast/test_simulation_regression_fast_nwt_regression.py -q -n 1
python -m pytest tests/regression/fast/intercomparison/test_mf6_support_intercomparison_fast_regression.py -q -n 1
python -m pytest tests/regression/extensive/test_simulation_regression_extensive_mf6_regression.py -q -n 1
python -m pytest tests/regression/extensive/test_simulation_regression_extensive_nwt_regression.py -q -n 1
```

Run through `tools.dev`:

```powershell
python -m tools.dev test regression
```

```powershell
python -m tools.dev test regression --extensive
```

```powershell
python -m tools.dev test regression --fast
```

```powershell
python -m tools.dev test regression --slow
```

```powershell
python -m tools.dev test regression --list
```

```powershell
python -m tools.dev test regression simulation_regression_fast_mf6 --fast --mf6 -j 1
```

```powershell
python -m tools.dev test regression simulation_regression_fast_nwt --fast --nwt -j 1
```

```powershell
python -m tools.dev test regression simulation_regression_extensive_mf6 --extensive --mf6 -j 1
```

```powershell
python -m tools.dev test regression simulation_regression_extensive_nwt --extensive --nwt -j 1
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
python -m pytest tests/regression/extensive/test_simulation_regression_extensive_nwt_regression.py -q -n 1
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
python -m pytest -m "regression and fast and intercomparison" -q
python -m pytest -m "regression and extensive and nwt" -q
python -m pytest -m "regression and not slow" -q
python -m pytest -m "(regression and fast) or slow" -q
```

## Update golden references

A golden moves only with a stated reason. `--update-goldens` records what the code
does today, so it can record a bug as easily as a fix. Before you run it:

- Know which number moves, and why the new one is right. An unexplained change is a
  regression, and updating the golden hides it.
- Update only the goldens of that change, with the one-file commands below. Use the
  full update only after a change that touches every solver.
- Read the diff of the golden file. Any line you cannot explain stops the update.

A golden that moves because the old number was wrong takes two more things in the
same commit, as `docs/source/contribute/architecture/how-to/cut-a-release.rst` says: a
line under `Numbers` in `CHANGELOG.md` with the quantity and the size of the change, and
an entry in `hydromodpy/results/known_issues.toml`. The tolerances live in
`tests/TOLERANCES.md`, and widening one to avoid a golden update is not allowed.

Update all golden references:

```powershell
python -m pytest -m regression -q -n auto --update-goldens
```

Update one golden file from one test:

```powershell
python -m pytest tests/regression/fast/test_simulation_regression_fast_boussinesq_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_simulation_regression_fast_boussinesq_divide_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_simulation_regression_fast_mf6_regression.py -q --update-goldens
python -m pytest tests/regression/fast/test_simulation_regression_fast_nwt_regression.py -q --update-goldens
python -m pytest tests/regression/fast/intercomparison/test_mf6_support_intercomparison_fast_regression.py -q --update-goldens
python -m pytest tests/regression/extensive/test_simulation_regression_extensive_mf6_regression.py -q --update-goldens
python -m pytest tests/regression/extensive/test_simulation_regression_extensive_nwt_regression.py -q --update-goldens
```

## Frozen runs

`frozen_runs/` keeps a run and a calibration session as 2.0.0 stored them. A golden
compares what the code writes today with a reference, `frozen_runs/` reads old files
with the code of today. It has its own `README.md`, and `--update-goldens` does not
touch it.

## Notes

- `--update-goldens` is a custom pytest option declared in `tests/conftest.py`.
- Parallel execution requires `pytest-xdist` (`-n auto`).
- MODPATH regression checks rely on `.dbf` snapshots, mainly the `time`
  column statistics.
- CI should execute regression tests without `--update-goldens`.
- Intercomparison tests should keep goldens compact: store selected metrics
  from `comparison_metrics.json`, never the figures.
