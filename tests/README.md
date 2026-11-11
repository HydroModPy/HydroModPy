# HydroModPy Test Suite

This directory holds the automated tests for HydroModPy. It is split into
five release tiers plus focused auxiliary tiers with different purposes,
budgets, and selection rules.

The tests fall in five families. Kernels in tables live in `unit/<package>/`,
one file per module. Scenarios live in `scenarios/`, port tests in
`ports/test_<port>.py`, refusal tables in `refusals/test_<family>.py`, and the
architecture gates in `unit/architecture/`. `regression/` and `validation/`
stand beside them.

## Layout

```
tests/
├── conftest.py                  # shared scratch root, update-goldens flag, shared fixtures
├── unit/                        # one module under test, 2 s target, no real I/O
├── integration/                 # cross-module workflows with shared fixtures, < 10 s
├── regression/                  # golden-reference tests for full workflows
│   ├── fast/                    # routine non-regression tier
│   ├── extensive/               # deeper end-to-end non-regression tier
│   ├── frozen_runs/             # a run and a session as 2.0.0 stored them, never edited
│   ├── frozen_documents/        # the other documents of 2.0.0, read or refused by name
│   ├── frozen_replay/           # one MODFLOW 6 run that must replay bit for bit
│   └── reference/               # committed golden JSON files
├── validation/                  # scientific benchmarks (analytical, MMS)
│   ├── analytical/
│   │   ├── steady/
│   │   └── transient/
│   └── numerical/
├── characterization/            # what a produced run offers a reader, plus the
│                                # double-execution comparator
├── e2e/                         # subprocess-level command scenarios
├── processes/                   # several processes on one folder, Linux and Windows
├── scenarios/                   # twenty-eight synthetic projects played by the real pipeline
├── performance/                 # pytest-benchmark storage-wrapper benchmarks
├── ports/                       # one file per port registry, parametrized on its names
├── refusals/                    # refusal tables: input, class, code, sentence
└── _helpers/                    # pytest-local helpers and shared builders
```

`validity_frame/` is a separate installable package with its own
`validity_frame/tests/`; it is not part of this suite.

## Tiers

| Tier | Target budget | Purpose | Selection |
|------|---------------|---------|-----------|
| `unit`       | 2 s per test (design target), 60 s hard timeout | One module under test, pure-Python logic, no external binaries, no real I/O outside `tmp_path`. | `pytest tests/unit/` |
| `integration` | ≤ 10 s per test | Cross-module workflows exercising more than one HydroModPy subpackage. Two shared fixtures are available from the root conftest (`tmp_workspace`, `minimal_config`); most tests build their own. No golden files. | `pytest tests/integration/` or `pytest -m integration` |
| `regression/fast` | ≤ 5 min | Full launcher/pipeline workflows on mini fixtures, compared to committed golden signatures. | `pytest tests/regression/fast/` |
| `regression/extensive` | ≤ 30 min | Deeper end-to-end golden checks with heavier fixtures. | `pytest tests/regression/extensive/` |
| `validation` | ≤ 30 min | Numerical results vs analytical / MMS references with documented tolerances. | `pytest tests/validation/` |
| `regression/frozen_replay` | ≤ 1 min | One frozen MODFLOW 6 run on 434 triangles, replayed by `hmp replay` from a copy and classed `bit`, once without gmsh. The weekly job replays it on another processor, and `HMP_REPLAY_REPORT` names the file where the test writes the class and the gaps it measured. | `pytest tests/regression/frozen_replay -q` |
| `processes` | 300 s per test | Tests that start several processes on one project, store, index or data folder. Children start with `spawn` only, so the tier runs on Linux and Windows, and the weekly job plays it on Windows. | `pytest tests/processes -q` |
| `scenarios` | ≤ 10 min under `-n 8` | Twenty-eight small synthetic projects, each played once by the real pipeline in a child process. The list is the `SCENARIOS` tuple of `tests/scenarios/test_harness.py`. | `pytest tests/scenarios/` or `pytest -m scenario` |
| `ports` | 900 s per test | One file per port registry (solver, source, terrain, mesh, optimizer, evaluator, figure, export), parametrized on its names. A missing binary is a skip unless `HMP_REQUIRE_BINARIES` is set. | `pytest tests/ports/` |
| `refusals` | 60 s per test | One row per refused input, with its class, its code and the sentence that names the new form. | `pytest tests/refusals/` |
| `characterization` | ≤ 1 min | One real `hmp run` on a committed example project, read back only through the file formats a stranger would use. Holds exactly five `xfail(strict=True)` cases, one per claim the code makes and does not honour; a strict xfail that starts passing fails the tier, which is how a repaired claim gets noticed. | `pytest tests/characterization/` |

## Markers

Declared in the repository-root `pytest.ini`:

| Marker        | Meaning |
|---------------|---------|
| `regression`  | compares output against a committed reference dataset |
| `intercomparison` | solver-to-solver regression based on compact comparison metrics |
| `validation`  | compares output against an analytical/numerical reference |
| `analytical`  | validation against a closed-form solution |
| `steady`      | steady-state case |
| `transient`   | transient case |
| `fast`        | cheap tier (fast regression or quick validation) |
| `slow`        | long-running test; filtered out of the push gate by `-m "not slow"` in `main-ci.yml`, still runs in `ci-weekly.yml` |
| `extensive`   | deeper regression tier |
| `nwt`         | MODFLOW-NWT / MODPATH / MT3DMS |
| `mf6`         | MODFLOW 6 / GWT |
| `petsc`       | Linux PETSc Boussinesq runtime |
| `integration` | cross-module workflow test (auto-applied to `tests/integration/`) |
| `coverage`    | long-running coverage-focused test |
| `solver_sanity` | benchmark built directly on the solver SDK (e.g. flopy); validates the external solver against an analytical reference, **not** the hydromodpy pipeline |
| `e2e`         | end-to-end pipeline scenarios |
| `scenario`    | a synthetic project played by the real pipeline (auto-applied to `tests/scenarios/`) |
| `performance` | performance baseline benchmarks |
| `unit`        | unit-tier tests, auto-applied by path |
| `characterization` | characterization-tier tests, auto-applied by path |
| `processes` | tests that start several processes on one folder, auto-applied to `tests/processes/` |
| `ports` | port tests, auto-applied to `tests/ports/` |
| `refusals` | refusal tables, auto-applied to `tests/refusals/` |
| `boussinesq`  | Boussinesq solver specific test |
| `network`     | requires network access |
| `binary`      | requires a solver binary on `PATH` |
| `allow_subprocess` | permits subprocess calls inside `unit/` |
| `timeout`     | per-test timeout in seconds |
| `xdist_group` | pytest-xdist worker grouping |

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
pytest -m "regression and intercomparison" -q -n 1

# Regression - extensive tier (serial)
pytest tests/regression/extensive/ -q -n 1

# Validation - all analytical cases
pytest tests/validation/ -q

# Characterization - one real run, read back from disk
pytest tests/characterization/ -q

# Several processes on one folder
pytest tests/processes -q

# The frozen MODFLOW 6 run, replayed bit for bit
pytest tests/regression/frozen_replay -q

# Double-execution comparator on the four frozen projects (about one minute)
python -m tests.characterization.comparator --frozen --report ~/hmp-parity.md

# Marker selection
pytest -m "regression and fast" -q
pytest -m "validation and steady" -q
pytest -m nwt -q
pytest -m "not slow" -q

# Parallel execution (xdist)
pytest tests/unit/ -q -n auto
pytest tests/regression/fast/ -q -n auto
```

In a source checkout, `python -m tools.dev test` wraps the most common invocations:

```bash
python -m tools.dev test unit                # → pytest tests/unit/
python -m tools.dev test regression --fast   # → pytest tests/regression/fast/
python -m tools.dev test regression --fast --intercomparison
python -m tools.dev test regression --extensive
python -m tools.dev test regression --update-goldens
```

## Environment

Scratch data lands in a repository-external directory to keep the working
tree clean:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HMP_TEST_SCRATCH_ROOT` | `/tmp/hydromodpy_tests/` | Shared scratch root; set this to redirect all test artifacts. |
| `HMP_COVERAGE`          | unset | When `1`, enables coverage collection during regression runs. |
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
pytest tests/regression/fast/test_simulation_regression_fast_mf6_regression.py \
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

Validation tolerances live in `tests/TOLERANCES.md`, with some
case-local files under `validation_cases/**/tolerances.toml` when the
benchmark owns a named envelope. `tests/_helpers/tolerances.py::tol()`
parses the shared table for tests that need a named tolerance.

## Writing new tests

- **unit/** - one importable module under test, one behavior per test,
  2 s target. The hard limit enforced by `tests/conftest.py` is a 60 s
  per-test timeout; anything that needs more must carry `@pytest.mark.slow`,
  which takes it out of the push gate. No external binaries. Use `tmp_path`
  for any I/O.
- **integration/** - cross-module test (pipeline + catalog, planner +
  adapters, …). Budget ≤ 10 s, no golden files. Two shared fixtures are
  available from the root conftest, `tmp_workspace` and `minimal_config`;
  neither is mandatory.
- **regression/** - exercise a full launcher / pipeline on a fixture, then
  compare a committed signature. Tag with `@pytest.mark.regression` and
  (if solver-specific) `@pytest.mark.nwt` or `@pytest.mark.mf6`.
- **validation/** - exercise a physical case against a known analytical
  solution; document the reference and the tolerance rationale.

The shared fixtures come from `tests/conftest.py`:

- `tmp_workspace(tmp_path)` yields an initialized workspace directory
  (standard `data/`, `projects/`, one `data/<variable>/` folder per variable)
  ready to back a `SimulationCatalog`.
- `minimal_config(tmp_path)` returns the smallest valid
  `HydroModPyConfig` (synthetic `geographic` + a `workspace` pointed at
  `tmp_path / "project"`). Extend via `.model_copy(update=...)`.

Prefer `@pytest.mark.parametrize` over copy-pasting N near-identical
tests. Keep test files under ~400 LOC: a file that grows beyond that is
usually hiding several independent suites.

## CI

The active GitHub Actions gates are split across `.github/workflows/`:

- **main-ci.yml** - PR + push gate: quality (ruff), secrets, architecture,
  a `--collect-only` gate over the whole tree, fast / unit (`-m "not slow"`) /
  ports / refusals / integration / regression-fast tiers, package-smoke, typing.
- **ci-nightly.yml** - nightly extensive regression, validation (not petsc; the
  petsc variants run in ci-nightly-petsc.yml), integration with coverage.
- **ci-nightly-petsc.yml** - nightly PETSc validation variants
  (`tests/validation -m petsc`, conda env with petsc4py), uploads
  `validation-results-petsc-<branch>`.
- **ci-weekly.yml** - cross-OS unit + fast-regression + analytical, serial
  e2e, full regression.
- **perf.yml** - pytest-benchmark drift gate over `tests/performance/`.
- **petsc-smoke.yml** - Linux PETSc Boussinesq smoke subset (conda env).

Validation, extensive regression, and e2e are not part of the fast
PR-blocking suite; run validation manually before a release with
`pytest tests/validation/ -q`.
