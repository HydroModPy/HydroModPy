# Validation Tests

Scientific validation tests of HydroModPy. They answer a different question
than the other tiers:

- unit tests: is one local behavior implemented correctly,
- regression tests: did a workflow change unexpectedly,
- validation tests: does a numerical result stay consistent with a reference
  that HydroModPy did not produce (a closed-form solution, a published
  MODFLOW 6 example, a manufactured solution, or a parameter that a
  calibration must find again).

A validation test may change internally as long as the model reproduces the
benchmark within explicit tolerances.

## Where to look first

Do not look for inventories in this file. They are generated or live in one
place each:

- results, references, thresholds and the last measured values:
  the docs page Theory > Validation (`docs/source/theory/validation.md`),
  rendered from `docs/source/theory/validation_results.json`;
- the analytical cases, their solvers and regime:
  `python -m validation_cases.run_cases --solver <solver> --regime both --list`
  (the solver names accepted are in `--help`);
- the solver variants of one case: the `[config_files]` table of its
  `metadata.toml`;
- every threshold and the reason for it: `tests/TOLERANCES.md` and the
  `tolerances*.toml` files of the case;
- what a case validates and assumes: the `README.md` of the case directory.

## Layout

- `tests/validation/analytical/`: closed-form references, `steady/` and
  `transient/`.
- `tests/validation/numerical/`: solver-to-solver or published-example checks
  (LAK, SFR, MVR, PETSc Boussinesq stress cases).
- `tests/validation/mms/`: manufactured-solution convergence tests.
- `tests/validation/calibration/`: twin experiments that recover known
  parameters.
- `tests/validation/helpers/`: threshold assertions and the recorder that
  feeds the docs page (`results.py`).
- `validation_cases/`: the benchmark logic, reusable outside pytest. See
  `validation_cases/README.md`.

Case physics lives in `validation_cases/`. Pytest files stay thin: they call
one comparison function and assert a few scalar metrics.

## Execution model

A launcher-backed test:

1. imports one `run_*_comparison(...)` function from a case,
2. checks the external executables with
   `tests.regression.golden_utils.assert_required_executables(...)`,
3. runs the case configuration through the production `hmp run` path
   (`validation_cases.shared.runtime.run_launcher_validation_case`),
4. loads the result arrays and evaluates the reference,
5. asserts the metrics against the case `tolerances*.toml`.

Validation runs store their fields at full precision
(`[simulation.results.persistence] field_precision = "exact"`, set by
`validation_cases/shared/runtime.py`). The default compact storage rounds
heads and would add noise larger than some thresholds.

Pytest runs with `MPLBACKEND=Agg` and the non-interactive `[display]`
defaults.

## Environment

Use the project environment (`micromamba activate hmp_dev`) and run from the
repository root. MODFLOW-NWT and MODFLOW 6 executables must be reachable.
The `boussinesq_local` engine needs nothing more.

The PETSc Boussinesq engine needs `petsc4py` from conda-forge, on Linux only.
Without it, tests marked `petsc` are skipped, not failed
(`pytest_runtest_setup` in `tests/conftest.py`).

## Running

```bash
python -m pytest tests/validation -q
python -m pytest -m "validation and fast" -q
python -m pytest -m "validation and analytical and steady" -q
python -m pytest tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py -q
python -m pytest tests/validation -m "not petsc" -n 8 --dist loadgroup -q
python -m pytest tests/validation -m petsc -q
```

Use `--dist loadgroup`: some tests share an `xdist_group`.

Use `--collect-only -q` to see what a selection contains without running it.

Run one case outside pytest, with a figure and the printed metrics. This is
the fastest way to diagnose a failure:

```bash
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --no-show
```

Run every compatible case for one solver: see `validation_cases/README.md`.

## Markers

The markers are declared in `pytest.ini` (`--strict-markers` is on). The ones
used here:

- `validation`, `analytical`, `steady`, `transient`: what the test is,
- `fast`, `slow`: speed class,
- `petsc`: needs the PETSc runtime.

The `petsc` mark is set by the solver parameter or by an explicit
`@pytest.mark.petsc`. `tests/conftest.py` marks the `boussinesq` solver
parameter of an analytical test. The name of a test says nothing about its
engine: `boussinesq_local` runs without PETSc and carries no mark.

## Results and the docs page

Each test records what it measured through `tests/validation/helpers/results.py`
(metrics, profiles, plan-view error maps, space-time error, calibration
landscapes). Set `HMP_VALIDATION_RESULTS` to a directory to keep the records
of a run, then merge them into the snapshot the docs page reads:

```bash
HMP_VALIDATION_RESULTS=$HOME/.cache/hmp-validation pytest tests/validation -m "not petsc" -n 8 --dist loadgroup
python -m tools.docs.validation_results merge $HOME/.cache/hmp-validation
```

A test keeps its newest result. `--replace` drops the older ones.
`python -m tools.docs.validation_results fetch` downloads the nightly
artifacts with `gh`.

## Output directories

Each run writes to a deterministic directory built from the test file and the
case id. By default it is under the system temporary directory, in
`hydromodpy_validation_outputs/`. If `HMP_OUT_PATH` is set, it is
`<HMP_OUT_PATH>/validation/<test_name>/<case_id>`. A previous directory of the
same case is removed first. `run_case.py --output-root` overrides
`HMP_OUT_PATH` for one run.

## Continuous integration

The workflows are in `.github/workflows/`:

- `ci-nightly.yml`: validation without PETSc (`-m "not petsc"`), merges the
  results into an artifact.
- `ci-weekly.yml`: the analytical tests without PETSc.
- `ci-nightly-petsc.yml`: every `petsc` test, in a conda-forge environment with
  `petsc4py`.
- `petsc-smoke.yml`: a small PETSc subset, on changes to the Boussinesq solver.

A scheduled workflow runs from the default branch only. `ci-nightly-petsc.yml`
exists on `dev` but runs once it reaches `main`.

Local smoke scripts: `tools/ci/run_boussinesq_linux_smoke.sh` and
`tools/ci/run_boussinesq_petsc_smoke.sh`.

## Threshold policy

Every threshold is derived, never tuned to pass:

- discretization error: about twice the measured error, with a refinement
  check that the error follows the order of the scheme;
- a documented, explained gap to the reference: about 1.1 times the measured
  value, with the cause written in the `[doc] gap` entry of the
  `tolerances*.toml` file (shown on the docs page).

A threshold is never loosened to make a test pass. A case that fails after a
change is a finding. Each threshold and its rationale go in
`tests/TOLERANCES.md`.

References pose their boundary heads where the model holds them, at the
centres of the boundary cells
(`validation_cases/shared/strip_geometry.py`). A head posed on the face adds a
first-order error in the cell size.

## Adding a case

1. Create a directory under `validation_cases/analytical/...` (see
   `validation_cases/README.md` for the layout).
2. Implement the reference in `reference.py` and the run-and-compare logic in
   `comparison.py`.
3. Write `tolerances.toml` following the threshold policy, with a `[doc]`
   reason, and add the rows to `tests/TOLERANCES.md`.
4. Add a thin pytest file under `tests/validation/...` marked
   `validation`, `analytical`, a regime and a speed class.
5. Record metrics with `tests/validation/helpers/results.py` so the case shows
   on the docs page.

Compare robust metrics, not raw arrays. Keep the configuration deterministic.
State what is and is not validated.

## Interpreting failures

- Executable check fails: the solver binary is missing from the environment.
- Launcher assertion fails: the run did not complete. stdout and stderr are in
  the message.
- Output resolution fails: the paths in `metadata.toml` no longer match the
  launcher output.
- Metric threshold fails: the model ran but the result moved away from the
  reference. Run `run_case.py`, read the metrics and the figure, then decide
  whether the cause is physical, numerical or a stale reference.
