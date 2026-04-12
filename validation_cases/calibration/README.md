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

## Layout

- `shared/`: reusable inverse-validation contracts and runtime helpers.
- `twin/`: standardized same-solver twin-experiment cases.
- `run_benchmarks.py`: run one or several twin benchmarks outside pytest.

## Current Scope

The first V1 inventory focuses on `modflow6` inverse benchmarks:

- one steady scalar `K` case on `dupuit_fixed_head_1d`,
- one noisy steady scalar `K` variant on `dupuit_fixed_head_1d`,
- one transient multiobservable `K + Sy` case on
  `linearized_unconfined_recharge_step_1d`,
- one noisy transient `K + Sy` variant with repeated stochastic seeds,
- one steady zoned `piecewise K` case on
  `boussinesq_fixed_head_piecewise_k_1d`.

Each case produces:

- synthetic truth observations,
- one or more calibration runs for standardized methods,
- a JSON benchmark summary with recovery metrics per method.

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
