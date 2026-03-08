# Regression Tests (Golden References)

## Scope and location

- Canonical non-regression tests are under `tests/regression/`.
- Golden references are under `tests/regression/reference/golden_references/`.
  - `tests/regression/reference/golden_references/normal/`
  - `tests/regression/reference/golden_references/extensive/`
- Two tiers are used:
  - `tests/regression/normal/` (tests de routine)
  - `tests/regression/extensive/` (tests exhaustifs)

Current non-regression tests:
- `normal/test_launcher_simulation_normal_regression.py` (runtime-reduced, keeps flow+transport+wells)
- `extensive/test_launcher_simulation_regression.py`
- `extensive/test_example12_npy_regression.py`
- `extensive/test_launcher_data_overview_regression.py`
- Golden references are no longer meant to be shared between tiers when
  signatures differ.
- Legacy folders `test/` and `test-old/` are no longer part of the active test workflow.

## Run tests

Run all regression tests:

```powershell
python -m pytest -m regression -q -n auto
```

Run only normal tier:

```powershell
python -m pytest tests/regression/normal -q -n auto
```

Run only extensive tier:

```powershell
python -m pytest tests/regression/extensive -q -n auto
```

Run only fast tests:

```powershell
python -m pytest -m fast -q -n auto
```

Run only normal tests with marker:

```powershell
python -m pytest -m "regression and normal" -q -n auto
```

Run only extensive tests:

```powershell
python -m pytest -m "regression and extensive" -q -n auto
```

Run only slow tests:

```powershell
python -m pytest -m slow -q -n auto
```

Run one specific test:

```powershell
python -m pytest tests/regression/normal/test_launcher_simulation_normal_regression.py -q -n 1
```

Run via the `hmp` CLI:

```powershell
hmp test regression
```

```powershell
hmp test regression --normal
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
hmp test regression launcher_simulation_normal --normal -j 1
```

## Parallel execution (`-n`)

`-n` is provided by `pytest-xdist` and controls how many worker processes run tests in parallel.

- `-n auto`: use all available CPU cores.
- `-n 4`: force 4 workers.
- `-n 1`: effectively serial execution with the xdist runner (useful for debugging).

Examples:

```powershell
python -m pytest -m regression -q -n auto
python -m pytest -m fast -q -n 4
python -m pytest tests/regression/extensive/test_example12_npy_regression.py -q -n 1
```

## Marker selection (`-m`) with multiple conditions

`-m` accepts a boolean expression on test markers.

Operators:

- `and`
- `or`
- `not`
- parentheses `(...)` for grouping

Common examples:

```powershell
python -m pytest -m "regression and fast" -q
python -m pytest -m "regression and slow" -q
python -m pytest -m extensive -q
python -m pytest -m "regression and not slow" -q
python -m pytest -m "(regression and fast) or slow" -q
```

Notes:

- Put the expression in quotes when it contains spaces/operators.
- `not` > `and` > `or` precedence applies; use parentheses when in doubt.

## Update golden references

Update all golden references:

```powershell
python -m pytest -m regression -q -n auto --update-goldens
```

Update one golden file from one test:

```powershell
python -m pytest tests/regression/extensive/test_example12_npy_regression.py -q --update-goldens
python -m pytest tests/regression/normal/test_launcher_simulation_normal_regression.py -q --update-goldens
```

## Notes

- `--update-goldens` is a custom pytest option declared in `tests/conftest.py`.
- Parallel execution requires `pytest-xdist` (`-n auto`).
- MODPATH regression checks rely on `.dbf` snapshots (mainly the `time` column statistics).
- CI should execute regression tests without `--update-goldens`.

