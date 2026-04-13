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

## Layout

- `shared/`: reusable inverse-validation contracts and runtime helpers.
- `twin/`: standardized same-solver twin-experiment cases.
- `run_benchmarks.py`: run one or several twin benchmarks outside pytest.

## Current Scope

The first V1 inventory focuses on `modflow6` inverse benchmarks:

- one steady scalar `K` case on `dupuit_fixed_head_1d`,
- one steady posterior-oriented scalar `K` case on `dupuit_fixed_head_1d`,
- one steady mesh-perturbed scalar `K` case on `dupuit_fixed_head_1d`,
- one noisy steady scalar `K` variant on `dupuit_fixed_head_1d`,
- one transient multiobservable `K + Sy` case on
  `linearized_unconfined_recharge_step_1d`, including one GP-mapping profile,
- one noisy transient `K + Sy` variant with repeated stochastic seeds,
- one steady zoned `piecewise K` case on
  `boussinesq_fixed_head_piecewise_k_1d`.

Each case produces:

- synthetic truth observations,
- optionally one distinct truth simulation config for perturbed twins,
- one or more calibration runs for standardized methods,
- one case-level configuration figure summarizing parameters, observables,
  objective blocks, methods, noise and the observation layout,
- a JSON benchmark summary with recovery metrics per method,
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

## Runner Notes

`run_benchmarks.py` supports a few suite-level controls:

- `--fast-only` or `--slow-only` to split quick CI coverage from the heavier suite;
- `--evaluation-budget N` to apply one approximate common evaluation budget
  across methods;
- `--artifact-retention {minimal,full}` to control how much each case keeps on
  disk after completion;
- `--no-case-figures` to skip per-case objective plots;
- `--no-figures` to skip suite-level plots when only raw outputs are needed.
