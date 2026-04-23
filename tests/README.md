# HydroModPy Test Suite

This directory holds the automated tests for HydroModPy. It is split into
three tiers with different purposes, budgets, and selection rules.

## Layout

```
tests/
├── conftest.py                  # shared scratch root, update-goldens flag, shared fixtures
├── unit/                        # one module under test, < 2 s, no real I/O
├── integration/                 # cross-module workflows with shared fixtures, < 10 s
├── regression/                  # golden-reference tests for full workflows
│   ├── fast/                    # routine non-regression tier
│   ├── extensive/               # deeper end-to-end non-regression tier
│   └── reference/               # committed golden JSON files
├── validation/                  # scientific benchmarks (analytical, MMS)
│   ├── analytical/
│   │   ├── steady/
│   │   └── transient/
│   └── numerical/
└── support/                     # pytest-local helpers (timing tools, etc.)
```

## Tiers

| Tier | Target budget | Purpose | Selection |
|------|---------------|---------|-----------|
| `unit`       | ≤ 1 min total, ≤ 2 s per test | One module under test, pure-Python logic, no external binaries, no real I/O outside `tmp_path`. | `pytest tests/unit/` |
| `integration` | ≤ 10 s per test | Cross-module workflows exercising more than one HydroModPy subpackage via shared fixtures (`tmp_workspace`, `minimal_config`, …). No golden files. | `pytest tests/integration/` or `pytest -m integration` |
| `regression/fast` | ≤ 5 min | Full launcher/pipeline workflows on mini fixtures, compared to committed golden signatures. | `pytest tests/regression/fast/` |
| `regression/extensive` | ≤ 30 min | Deeper end-to-end golden checks with heavier fixtures. | `pytest tests/regression/extensive/` |
| `validation` | ≤ 30 min | Numerical results vs analytical / MMS references with documented tolerances. | `pytest tests/validation/` |

## Markers

Declared in `pyproject.toml`:

| Marker        | Meaning |
|---------------|---------|
| `regression`  | compares output against a committed reference dataset |
| `validation`  | compares output against an analytical/numerical reference |
| `analytical`  | validation against a closed-form solution |
| `steady`      | steady-state case |
| `transient`   | transient case |
| `fast`        | cheap tier (fast regression or quick validation) |
| `slow`        | long-running test, skipped from fast CI |
| `extensive`   | deeper regression tier |
| `nwt`         | MODFLOW-NWT / MODPATH / MT3DMS |
| `mf6`         | MODFLOW 6 / GWT |
| `petsc`       | Linux PETSc Boussinesq runtime |
| `integration` | cross-module workflow test (auto-applied to `tests/integration/`) |
| `coverage`    | long-running coverage-focused test |
| `solver_sanity` | benchmark built directly on the solver SDK (e.g. flopy); validates the external solver against an analytical reference, **not** the hydromodpy pipeline |

The `fast`/`extensive` markers under `tests/regression/` are auto-applied
based on the file's subdirectory (see `tests/conftest.py`).

## Common commands

```bash
# Unit tests (fastest feedback)
pytest tests/unit/ -q                         # all unit tests
pytest tests/unit/solver -q                   # a subpath
pytest tests/unit/ -q -k metrics_nse          # keyword filter

# Regression - fast tier (parallel)
pytest tests/regression/fast/ -q -n auto

# Regression - extensive tier (serial)
pytest tests/regression/extensive/ -q -n 1

# Validation - all analytical cases
pytest tests/validation/ -q

# Marker selection
pytest -m "regression and fast" -q
pytest -m "validation and steady" -q
pytest -m nwt -q
pytest -m "not slow" -q

# Parallel execution (xdist)
pytest tests/unit/ -q -n auto
pytest tests/regression/fast/ -q -n auto
```

The `hmp` CLI wraps the most common invocations:

```bash
hmp test unit                # → pytest tests/unit/
hmp test regression --fast   # → pytest tests/regression/fast/
hmp test regression --extensive
hmp test regression --update-goldens
```

## Environment

Scratch data lands in a repository-external directory to keep the working
tree clean:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HYDROMODPY_TEST_SCRATCH_ROOT` | `/tmp/hydromodpy_tests/` | Shared scratch root; set this to redirect all test artifacts. |
| `HYDROMODPY_COVERAGE`          | unset | When `1`, enables coverage collection during regression runs. |
| `PYTEST_DEBUG_TEMPROOT`        | `<scratch>/pytest` | Points pytest's `tmp_path` generator inside the scratch root. |

The conftest sets `TMPDIR`/`TMP`/`TEMP` to a subdirectory of the scratch root
so spawned subprocesses inherit the same cleanup policy.

## Golden references

Regression tests compare the output of a pipeline run to a committed
**signature** - a statistical summary of fields stored as JSON under
`tests/regression/reference/golden_references/{fast,extensive}/`.

### Reading a failure

When a regression assertion fails:

1. Identify the golden file referenced by the failing test
   (path is printed in the assertion message).
2. Open the corresponding JSON and compare the stored signature to the
   freshly computed one.
3. Decide whether the difference is:
   - **a legitimate code change** - update the golden (see below),
   - **a numerical drift** - investigate the responsible commit,
   - **a platform difference** - document and, if needed, tighten the
     tolerance or mark the test platform-specific.

### Updating goldens

Never edit a JSON file by hand. Use the dedicated CLI switch, which
regenerates the golden from the current output:

```bash
# Refresh every golden referenced by a test run
pytest tests/regression/ -q -n auto --update-goldens

# Refresh the goldens of a single test module
pytest tests/regression/fast/test_launcher_simulation_fast_mf6_regression.py \
    -q --update-goldens
```

Then commit the updated JSON files in a dedicated commit. The commit
message must state the scientific or code-level reason the signature
changed.

### Tolerances

Numerical comparisons use `numpy.testing.assert_allclose` (or equivalent
`math.isclose`) with an explicit `rtol`/`atol`. Prefer statistical
signatures (min, p25, p50, p75, p95, max, mean, std, sum) over full-array
dumps so goldens stay compact and cross-platform stable.

Validation tolerances live alongside the cases under
`validation_cases/**/tolerances.toml`; see `tests/validation/README.md`
for the per-case workflow.

## Writing new tests

- **unit/** - one importable module under test, one behaviour per test,
  budget ≤ 2 s. No external binaries. Use `tmp_path` for any I/O.
- **integration/** - cross-module test (pipeline + catalog, planner +
  adapters, …) backed by shared fixtures from the root conftest
  (`tmp_workspace`, `minimal_config`). Budget ≤ 10 s, no golden files.
- **regression/** - exercise a full launcher / pipeline on a fixture, then
  compare a committed signature. Tag with `@pytest.mark.regression` and
  (if solver-specific) `@pytest.mark.nwt` or `@pytest.mark.mf6`.
- **validation/** - exercise a physical case against a known analytical
  solution; document the reference and the tolerance rationale.

The shared fixtures come from `tests/conftest.py`:

- `tmp_workspace(tmp_path)` yields an initialized workspace directory
  (standard `data/`, `projects/`, per-variable `*_custom/` seed folders)
  ready to back a `SimulationCatalog`.
- `minimal_config(tmp_path)` returns the smallest valid
  `HydroModPyConfig` (synthetic `geographic` + a `workspace` pointed at
  `tmp_path / "project"`). Extend via `.model_copy(update=...)`.

Prefer `@pytest.mark.parametrize` over copy-pasting N near-identical
tests. Keep test files under ~400 LOC: a file that grows beyond that is
usually hiding several independent suites.

## CI

`.github/workflows/coverage.yml` runs on push to `master`/`dev-refact`/
`dev-data`/`dev-database` and on PRs to `master`:

- **unit job** - `pytest tests/unit/` on Python 3.12 with coverage
  (`unit` flag on Codecov).
- **regression job** - `pytest tests/regression/fast/ tests/regression/extensive/`
  with coverage (`regression` flag on Codecov).

Validation runs are not part of the fast PR-blocking suite; run them
manually before a release with `pytest tests/validation/ -q`.
