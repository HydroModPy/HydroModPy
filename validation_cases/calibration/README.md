# Calibration Validation Cases

This package hosts inverse-validation cases for HydroModPy calibration.

These cases answer two related questions:

- can the calibration infrastructure recover a known synthetic truth on a
  controlled problem;
- how do multiple calibration methods compare on the same inverse benchmark.

The current design deliberately uses same-solver twin experiments:

- a reference parameter set is treated as the truth model,
- synthetic observations are generated from one forward run on the selected
  solver,
- the calibration then runs on that same solver against the generated
  observations.

This is a favorable but controlled setting. It is intended to validate the
inverse chain and to provide standardized method benchmarks before moving to
harder perturbed or field-like workflows.

The infrastructure also supports a first tier of `perturbed twin` experiments:

- the truth run may use a dedicated simulation config distinct from calibration,
- synthetic observations still come from the same solver family,
- the perturbation is recorded explicitly in benchmark summaries.

Reference used by the documentation:

- reference: the parameter values that generated the synthetic observations of the twin experiment

## Layout

- `shared/`: reusable inverse-validation contracts and runtime helpers.
- `twin/`: standardized same-solver twin-experiment cases.
- `run_benchmarks.py`: run one or several twin benchmarks outside pytest.
- `groundwater_1d/`, `recession_brutsaert/` and `reservoir/`: standalone experiments with a
  forward model of a few lines and a command line, both written once in
  `shared/standalone.py`.
- `unconfined_interface_1d/` and `recession_hillslope_aquifer/`: two analytical cases driven
  from Python, a two-material unconfined aquifer and the recession of a hillslope aquifer.
- `network_transient_b0/`: the B0 case, a natural drainage network and a transient discharge, with
  its observations, costs, HTML page and two scripts.
- `objective_mapping.py`: the objective mapping used by `plotting.py`.

## Solver columns

Four twins run on every column that can host them: `modflow_nwt`, `modflow6`
(structured grid), `modflow6_irregular_tri` (triangle mesh),
`modflow6_voronoi` (Voronoi dual of that mesh), and the in-house Boussinesq
solver on the same triangles with its PETSc engine (`boussinesq`) and its
default local engine (`boussinesq_local`). They are the mesh-perturbed
scalar `K` twin, the zoned `piecewise K` twin, the transient `K + Sy` twin and
its flux-only noisy variant. Each experiment module holds one definition per
column in a dict keyed by the column (`PIECEWISE_K_TWIN_CASES`, ...), built with
`dataclasses.replace` on the `modflow6` definition and the config builders of
`shared/solver_variants.py`. Another column is one more entry in
`solver_variants.VARIANTS`.

The Boussinesq solver writes no MODFLOW files. A trial reads the head and the
outflow of its `_boussinesq_state_history.npz` (`runtime.py`,
`_extract_outputs_from_boussinesq_dir`). The outlet discharge is the first of
`drain` and `constant_head` that carries a flux, on both routes, because a
Boussinesq budget lists a drain row of zeros when the case has no drain. The
PETSc leg of a test runs without CMA-ES when `cma` is missing from its
environment (`solver_variants.runnable_method_names`). The default local engine
leg of the transient twin runs two methods, Nelder-Mead and Optuna, because its
dense solver takes several seconds per candidate.

The truth is read from the catalog Run and the trial costs from the solver
files. Both routes locate an observation point with the same point-in-polygon
lookup on the mesh cells and read a field stored at full precision
(`field_precision = "exact"`), so a twin without noise is closed: a search that
starts at the truth costs zero on every column. `shared/zero_return.py` is that
check.

The mesh-perturbed twin runs its truth on a mesh twice as fine as the
calibration mesh. The refined triangle bundle is under
`twin/steady/dupuit_fixed_head_1d/mesh_bundles/`; `mesh_bundle.py` rebuilds it.
The stream-network twin (`tests/validation/calibration/
test_twin_matching_stream_network_modflow6.py`) runs the same four columns on a
strip of 800 triangles and its 802-cell Voronoi dual, and the Boussinesq PETSc
column on the 800 triangles. The default local engine cannot solve that
hillslope: see the `NOT_APPLICABLE` entry of the test.

## Current Scope

The first V1 inventory focuses on `modflow6` inverse benchmarks, with the
columns above for four of them:

- one steady scalar `K` case on `dupuit_fixed_head_1d`,
- one steady posterior-oriented scalar `K` case on `dupuit_fixed_head_1d`,
- one steady mesh-perturbed scalar `K` case on `dupuit_fixed_head_1d`,
- one noisy steady scalar `K` variant on `dupuit_fixed_head_1d`,
- one transient multiobservable `K + Sy` case on
  `linearized_unconfined_recharge_step_1d`, including `cma_es`,
  `gp_mapping` and `da_mh_gp`,
- one noisy transient `K + Sy` variant with repeated stochastic seeds,
- one noisy transient flux-only `K + Sy` variant on the same recharge-step
  physics, used as a deliberately weakly constrained inverse benchmark,
- one steady zoned `piecewise K` case on
  `boussinesq_fixed_head_piecewise_k_1d`.

The current gallery and validation defaults also use wider initial bounds than
the first V1 tranche so that inverse benchmarks exercise a less local search
region before converging back to the synthetic truth.

Each case produces:

- synthetic truth observations,
- optionally one distinct truth simulation config for perturbed twins,
- one or more calibration runs for standardized methods,
- one case-level configuration figure summarizing parameters, observables,
  objective blocks, methods, noise and the observation layout,
- a JSON benchmark summary with recovery metrics per method,
- one shared non-regular reference-objective exploration for published cases,
  used to reconstruct 1D curves, 2D landscapes, and pairwise projections in
  higher dimensions more faithfully than method-only sample clouds,
- method-level timing diagnostics including total calibration time, one-time
  session preparation time, and mean per-model preparation/simulation/objective
  costs,
- per-method objective figures when iteration history is available.

By default the benchmark runtime keeps a minimal retained footprint:

- calibration summaries, histories, and per-method figures are kept;
- heavy `results_simulations` and `results_stable` trees are pruned after the
  benchmark finishes;
- use `--artifact-retention full` when the full forward-output tree must be
  kept for debugging.

Method-level evaluation distinguishes:

- `best_fit`: the best calibrated parameter set must recover the truth within the
  case tolerance;
- `distribution`: the persisted distribution must contain at least one model
  compatible with the truth within the case tolerance;
- `best_fit_or_distribution`: either of the two previous conditions is accepted.

For noisy or repeated stochastic benchmarks, the suite report is intended to be
read primarily through success rates, distribution coverage, and timing
statistics rather than a strict expectation that every seed or every local
method reaches the truth on every run.

Running multiple cases through `run_benchmarks.py` also produces one aggregate:

- `benchmark_suite_summary.json`
- `benchmark_suite_summary.csv`
- `benchmark_method_stats.json`
- `benchmark_method_stats.csv`
- `benchmark_suite_report.md`
- suite figures such as:
  - `benchmark_target_success_rates.png`
  - `benchmark_cost_vs_budget.png`
  - `benchmark_time_vs_cost.png`
  - `benchmark_parameter_error_ratio.png`
  - `benchmark_candidate_timing_breakdown.png`

## Runner Notes

`run_benchmarks.py` supports a few suite-level controls:

- `--fast-only` or `--slow-only` to split quick CI coverage from the heavier suite;
- `--evaluation-budget N` to apply one approximate common evaluation budget
  across methods;
- `--artifact-retention {minimal,full}` to control how much each case keeps on
  disk after completion;
- `--no-case-figures` to skip per-case objective plots;
- `--no-figures` to skip suite-level plots when only raw outputs are needed.
