# Pytest Timing Distribution

This note documents how to build a runtime distribution for test-duration
analysis.

## 1) Generate a JUnit XML report from pytest

Example:

```powershell
$timingRoot = Join-Path $env:HYDROMODPY_TEST_SCRATCH_ROOT "timing_reports"
python -m pytest tests/unit/solver/utils/mesh/gmsh_grid -q --junitxml "$timingRoot/gmsh_grid_junit.xml" -p no:cacheprovider
```

## 2) Build the timing distribution report

```powershell
python tests/support/pytest_timing_distribution.py `
  --junitxml "$timingRoot/gmsh_grid_junit.xml" `
  --status-filter passed `
  --top-n 20 `
  --out-json "$timingRoot/gmsh_grid_timing_distribution_passed.json" `
  --out-csv "$timingRoot/gmsh_grid_test_durations_passed.csv"
```

## 3) What the tool returns

- Global stats: total/mean/median durations.
- Quantiles: `p50`, `p75`, `p90`, `p95`, `p99`, `max`.
- Histogram by duration bins.
- Top slow tests.
- Top modules by cumulative runtime.

Notes:

- `--status-filter` controls included statuses (`passed`, `failed`, `error`, `skipped`).
- `--include-skipped` can be used to include skipped tests in the distribution.
