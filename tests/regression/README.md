# Regression Tests (Golden References)

Run all regression tests:

```powershell
python -m pytest -m regression -q
```

Run a single regression test:

```powershell
python -m pytest tests/regression/test_example_00_npy_regression.py -q
```

Update all golden references (rewrites JSON files):

```powershell
python -m pytest -m regression -q --update-goldens
```

Update one test golden reference:

```powershell
python -m pytest tests/regression/test_example_11_npy_regression.py -q --update-goldens
```

Notes:
- `--update-goldens` is a custom pytest option defined in `tests/conftest.py`.
- Golden files are stored in `tests/regression/reference/golden_references/`.
- CI should run regression tests without `--update-goldens`.

