# Roadmap

## Calibration

- **PEST++ / pyemu**: optional adapter via `entry_points`, post-P13. Out of
  scope for the initial calibration work — complexity of onboarding judged
  too high versus the immediate value.

The P09 calibration package (`hydromodpy/calibration/`) ships with the
following optimizer adapters:

| Name                  | Library  | Notes                                |
|-----------------------|----------|--------------------------------------|
| `optuna`              | optuna   | TPE (default), CMA-ES, NSGA-II, Random |
| `scipy_de`            | scipy    | differential evolution               |
| `scipy_nelder_mead`   | scipy    | Nelder-Mead simplex                  |
| `grid`                | built-in | deterministic grid over bounds       |

Third-party optimizers can be plugged in through the
`hydromodpy.optimizer` entry-point group.
