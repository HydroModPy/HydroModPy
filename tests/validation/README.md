# Validation Tests

This directory hosts HydroModPy scientific validation tests.

These tests answer a different question than unit or regression tests:

- unit tests ask whether one local behavior is implemented correctly,
- regression tests ask whether a workflow changed unexpectedly,
- validation tests ask whether a numerical result remains consistent with a
  trusted physical or analytical reference.

In practice, a validation test is allowed to evolve internally as long as the
model still reproduces the intended benchmark within explicit tolerances.

## Scope

The current validation suite focuses on analytical groundwater-flow benchmarks:

- steady Dupuit and Boussinesq profiles,
- transient linearized unconfined responses,
- radial 2D island and pumping cases,
- a distributed top-drainage benchmark,
- one steady topographic interception benchmark for the local `boussinesq` backend,
- one transient topographic interception-onset benchmark for the local `boussinesq` backend.

At the moment:

- validation cases are analytical,
- launcher-backed cases run through `tests/regression/fixtures/launcher_simulation`,
- current scientific coverage is centered on `modflownwt`,
- current validation tests do not require `MODPATH` or `MT3DMS`.

## Directory Layout

- `tests/validation/`: pytest entrypoints and test-only assertions.
- `validation_cases/`: reusable benchmark cases, references, metadata, and
  runner scripts.
- `validation_cases/shared/`: shared runtime, loading, metric, and CLI helpers.
- `tests/validation/helpers/`: thin test-oriented wrappers and assertions.

The design intent is:

- case physics and benchmark logic live in `validation_cases/`,
- pytest orchestration lives in `tests/validation/`,
- a case can be run both from pytest and manually through `run_case.py`.

## Execution Model

A typical validation test follows this sequence:

1. import one case-specific `run_*_comparison(...)` function from
   `validation_cases/.../comparison.py`,
2. check required external executables with
   `tests.regression.golden_utils.assert_required_executables(...)`,
3. run the deterministic launcher configuration for that case,
4. locate the generated `_postprocess` outputs,
5. load the relevant arrays,
6. compare them to the analytical reference,
7. assert that selected metrics remain below thresholds from
   `tolerances.toml`.

The launcher execution itself is handled by
`validation_cases.shared.runtime.run_launcher_validation_case(...)`.

## Output Directories

Each validation run writes into a deterministic output directory derived from:

- the pytest file name,
- the case id from `metadata.toml`.

By default, outputs are created under the system temporary directory in
`hydromodpy_validation_outputs/`. If `HYDROMODPY_OUT_PATH` is defined, the run
directory is created under:

```text
<HYDROMODPY_OUT_PATH>/validation/<test_name>/<case_id>
```

Before re-running the same case, the previous validation directory is removed.
The runtime includes a small retry loop to handle transient Windows file locks.

## Prerequisites

Recommended setup:

- activate the HydroModPy environment,
- ensure `mfnwt` or the expected MODFLOW-NWT executable is reachable,
- run validation from the repository root.

Typical environment setup:

```powershell
conda activate hydromodpy
python -m pytest tests/validation -q
```

## Platform-Specific Behavior

The validation suite is intentionally cross-platform where possible, but not
every solver backend is available on every operating system.

- Most validation tests are expected to run on both Windows and Linux when the
  required scientific Python stack and external solver executables are present.
- The PETSc Boussinesq runtime is Linux-only by design. The corresponding
  pytest files explicitly skip on non-Linux platforms instead of failing.
- A Windows run that reports many `passed` tests plus a few PETSc-related
  `skipped` tests is therefore a valid outcome, not a degraded run.

Today, the Linux-only PETSc coverage is concentrated in:

- `tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py`
- `tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py`
- `tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py`
- `tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py`

In practice:

- On Windows, run the full validation suite normally with `pytest`; PETSc-only
  tests will be skipped automatically.
- On Linux, the same `pytest` commands also run the Linux-only PETSc tests if
  `petsc4py` and the PETSc runtime are installed in the active environment.
- If those Linux dependencies are missing, the PETSc tests will skip or fail at
  import/runtime setup rather than indicate a scientific regression.

During pytest execution, validation runs are launched with
`MPLBACKEND=Agg`. Display behaviour is otherwise driven by the
``[display]`` TOML section (defaults are non-interactive and
save-enabled), which keeps the tests deterministic.

## Running the Suite

Run all validation tests:

```powershell
python -m pytest tests/validation -q
python -m pytest -m validation -q
```

Run only the quick validation subset:

```powershell
python -m pytest -m "validation and fast" -q
```

Run only steady or transient cases:

```powershell
python -m pytest -m "validation and steady" -q
python -m pytest -m "validation and transient" -q
```

Run a single case:

```powershell
python -m pytest tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py -q
python -m pytest tests/validation/analytical/steady/test_dupuit_circular_island_ocean_2d.py -q
```

### Linux Smoke Commands Used by CI

The repository already exposes the Linux smoke subsets used in CI:

```bash
bash tools/ci/run_boussinesq_linux_smoke.sh
bash tools/ci/run_boussinesq_petsc_smoke.sh
```

These scripts are thin wrappers around `python -m pytest ...` and can be used
locally on Linux as-is.

The PETSc smoke subset can also be launched directly with pytest:

```bash
python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py \
  -q
```

The broader non-PETSc Linux smoke subset is:

```bash
python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/solver/test_boussinesq_smoothing.py \
  tests/unit/solver/test_boussinesq_backend.py \
  tests/unit/simulation/test_boussinesq_flow_adapter.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/unit/validation/test_hillslope_pulse_overflow_case.py \
  "tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py::test_dupuit_fixed_head_1d_matches_reference_profile[boussinesq]" \
  -q
```

The PETSc-focused tests are now tagged with `@pytest.mark.petsc`, so on a
fully provisioned Linux environment you can also use:

```bash
python -m pytest -m petsc -q
```

If you are working in a partial environment and want the narrowest possible
selection, the current recommended approach is still either:

- run the explicit file list above, or
- reuse the `tools/ci/*.sh` smoke scripts.

## Running All Cases Outside Pytest

Use `validation_cases.run_cases` when you want to execute every compatible
`run_case.py` sequentially, print the per-case metrics, and optionally open the
diagnostic figures.

List the selected cases without running them:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --list
python -m validation_cases.run_cases --solver modflow6 --regime both --list
```

Run all steady or transient cases for one solver without interactive figures:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime steady --no-show
python -m validation_cases.run_cases --solver modflownwt --regime transient --no-show
python -m validation_cases.run_cases --solver modflow6 --regime steady --no-show
python -m validation_cases.run_cases --solver modflow6 --regime transient --no-show
```

Run the full analytical inventory for one solver:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --no-show
python -m validation_cases.run_cases --solver modflow6 --regime both --no-show
python -m validation_cases.run_cases --solver boussinesq --regime both --no-show
```

Refresh the committed batch reports used by the documentation gallery:

```powershell
python -m validation_cases.update_reports --no-show
```

Run with diagnostic figures enabled:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime transient --show
python -m validation_cases.run_cases --solver modflow6 --regime steady --show
```

Stop the batch on the first failing case:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --no-show --stop-on-error
```

## Running One Case Outside Pytest

Every launcher-backed case also exposes a direct runner under
`validation_cases/.../run_case.py`.

Examples:

```powershell
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case
python -m validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.run_case --no-show
```

The runner:

- executes the case,
- generates a comparison figure,
- prints the output directory and main metrics.

This is the recommended path when a pytest validation fails and you want a
human-readable diagnostic first.

## Current Analytical Inventory

For the full case inventory and case-directory contract, see
`validation_cases/README.md`.

For a case-by-case description of numerical setup, analytical target, metrics,
and scientific scope, use the "Detailed Case Sheets" section in
`validation_cases/README.md`.

Current pytest coverage is:

| Test | Regime | Main reference |
| --- | --- | --- |
| `analytical/steady/test_dupuit_fixed_head_1d.py` | steady | Dupuit fixed-head profile |
| `analytical/steady/test_dupuit_uniform_recharge_1d.py` | steady | Dupuit recharge profile |
| `analytical/steady/test_dupuit_divide_river_1d.py` | steady | Dupuit divide-river profile |
| `analytical/steady/test_dupuit_circular_island_ocean_2d.py` | steady | radial Dupuit-Boussinesq island |
| `analytical/steady/test_boussinesq_fixed_head_piecewise_k_1d.py` | steady | piecewise-`K` Boussinesq |
| `analytical/steady/test_boussinesq_uniform_recharge_piecewise_k_1d.py` | steady | piecewise-`K` recharge |
| `analytical/steady/test_boussinesq_divide_fixed_head_piecewise_k_1d.py` | steady | piecewise-`K` divide |
| `analytical/steady/test_boussinesq_hillslope_interception_1d.py` | steady | Boussinesq hillslope interception |
| `analytical/steady/test_boussinesq_circular_island_piecewise_k_2d.py` | steady | radial piecewise-`K` island |
| `analytical/steady/test_linearized_unconfined_drainage_1d.py` | steady | linearized distributed drainage |
| `analytical/steady/test_linearized_unconfined_hillslope_drainage_1d.py` | steady | linearized hillslope drainage |
| `analytical/transient/test_linearized_unconfined_recharge_step_1d.py` | transient | linearized recharge step |
| `analytical/transient/test_boussinesq_hillslope_recharge_step_interception_1d.py` | transient | hillslope interception onset |
| `analytical/transient/test_linearized_unconfined_boundary_step_1d.py` | transient | linearized boundary step |
| `analytical/transient/test_linearized_unconfined_recharge_step_deep_1d.py` | transient | linearized recharge step, deep aquifer |
| `analytical/transient/test_linearized_unconfined_boundary_piecewise_1d.py` | transient | linearized piecewise boundary forcing |
| `analytical/transient/test_linearized_unconfined_recharge_periodic_1d.py` | transient | linearized periodic recharge |
| `analytical/transient/test_late_time_unconfined_pumping_2d.py` | transient | late-time radial pumping |

## Pytest Markers

Validation tests use the marker set declared in `pyproject.toml`:

- `validation`: scientific benchmark test,
- `analytical`: comparison against an analytical reference,
- `steady`: steady-state case,
- `transient`: transient case,
- `fast`: quick validation case,
- `slow`: longer-running validation case.
- `petsc`: Linux PETSc-backed Boussinesq runtime test.

Examples:

```powershell
python -m pytest -m "validation and analytical and steady" -q
python -m pytest -m "validation and slow" -q
python -m pytest -m petsc -q
```

## Anatomy of One Validation Case

Each launcher-backed case in `validation_cases/` typically contains:

- `config_modflownwt.toml`: deterministic launcher configuration,
- `reference.py`: analytical solution and literature references,
- `comparison.py`: run-and-compare workflow,
- `metadata.toml`: case metadata used to find outputs and define reference
  parameters,
- `tolerances.toml`: acceptance thresholds checked by pytest,
- `plotting.py`: optional diagnostic figure builder,
- `run_case.py`: manual runner.

The corresponding pytest file should stay intentionally thin: it should call
the comparison function and assert a small number of clear metrics.

## Adding a New Validation Test

Recommended workflow:

1. create a new case directory under `validation_cases/`,
2. implement the analytical reference in `reference.py`,
3. implement the launcher execution and metric computation in `comparison.py`,
4. document assumptions and references in the case `README.md`,
5. define explicit thresholds in `tolerances.toml`,
6. add one pytest file under `tests/validation/...`,
7. tag it with `@pytest.mark.validation`, `@pytest.mark.analytical`, and the
   relevant regime/speed markers.

Good practice:

- compare robust metrics, not just raw arrays,
- keep the launcher configuration deterministic,
- state clearly what is and is not validated,
- use `run_case.py` as a debugging aid, not as the primary test harness.

## Interpreting Failures

Common failure modes:

- executable check fails:
  the external groundwater solver is not available in the environment;
- launcher assertion fails:
  the case did not run to completion, and stdout/stderr are included in the
  assertion message;
- output resolution fails:
  the paths expected from `metadata.toml` no longer match the launcher output
  structure;
- metric threshold fails:
  the model still ran, but the numerical result drifted away from the accepted
  benchmark.

When a metric failure occurs, the fastest diagnostic path is usually:

1. run the corresponding `run_case.py`,
2. inspect the printed metrics,
3. inspect the generated figure,
4. check whether the issue is physical, numerical, or just a tolerance/update
   problem.
