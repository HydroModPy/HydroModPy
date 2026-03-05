# Calibration2 Config Reference

This page is generated from Pydantic schemas used by calibration2.

## Core TOML Schema

### `[calibration]`

| Field | Type | Default |
|---|---|---|
| `objective_metric` | `str` | `'kge'` |
| `global_method` | `str` | `'simplex'` |
| `model_name` | `str | NoneType` | `None` |

### Top-level sections

| Field | Type | Default |
|---|---|---|
| `chronicle` | `dict[str, Any]` | `required` |
| `calibration` | `CalibrationSectionSchema` | `required` |
| `bounds` | `dict[str, tuple[float, float] | list[float]]` | `required` |
| `calibration_method` | `dict[str, dict[str, Any]]` | `<factory>` |
| `output` | `OutputSectionSchema` | `<factory>` |
| `objective` | `ObjectiveSectionSchema` | `<factory>` |

### `[output]`

| Field | Type | Default |
|---|---|---|
| `output_dir` | `str` | `'outputs'` |
| `show_plot` | `bool` | `True` |
| `figure_name` | `str | NoneType` | `None` |
| `show_objective_surface` | `bool` | `False` |
| `objective_surface_n_evaluations` | `int` | `300` |
| `objective_surface_seed` | `int` | `42` |

### `[objective]`

| Field | Type | Default |
|---|---|---|
| `transform` | `str` | `'identity'` |
| `transform_params` | `dict[str, float]` | `<factory>` |

## Built-in Method Kwargs

### `[calibration_method.da_mh_gp]`

| Field | Type | Default |
|---|---|---|
| `sigma_noise` | `float | NoneType` | `None` |
| `logprior_fn` | `Any | NoneType` | `None` |
| `prior_mean` | `float | int | list[float | int] | tuple[float | int, Ellipsis] | dict[str, float | int] | NoneType` | `None` |
| `prior_std` | `float | int | list[float | int] | tuple[float | int, Ellipsis] | dict[str, float | int] | NoneType` | `None` |
| `n_init` | `int | NoneType` | `None` |
| `n_samples` | `int | NoneType` | `None` |
| `burn_in` | `int | NoneType` | `None` |
| `thin` | `int | NoneType` | `None` |
| `proposal_scale` | `float | int | list[float | int] | tuple[float | int, Ellipsis] | dict[str, float | int] | NoneType` | `None` |
| `proposal_cov` | `list[list[float]] | NoneType` | `None` |
| `retrain_interval` | `int | NoneType` | `None` |
| `gp_length_scale` | `float | int | list[float | int] | tuple[float | int, Ellipsis] | dict[str, float | int] | NoneType` | `None` |
| `gp_noise` | `float | NoneType` | `None` |
| `full_mh_prob` | `float | NoneType` | `None` |
| `seed` | `int | NoneType` | `None` |
| `cache_decimals` | `int | NoneType` | `None` |

### `[calibration_method.gp_mapping]`

| Field | Type | Default |
|---|---|---|
| `seed` | `int` | `required` |
| `n_init` | `int` | `required` |
| `n_refine` | `int` | `required` |
| `batch_size` | `int` | `required` |
| `n_candidates` | `int` | `required` |
| `kappa` | `float` | `required` |
| `alpha` | `float` | `required` |
| `jitter` | `float` | `required` |
| `n_posterior_pool` | `int` | `required` |
| `n_posterior_samples` | `int` | `required` |
| `log_transform` | `bool` | `required` |

### `[calibration_method.grid_search]`

| Field | Type | Default |
|---|---|---|
| `n_per_dim` | `int | list[int]` | `required` |
| `log_scale_indices` | `list[int]` | `<factory>` |

### `[calibration_method.nelder_mead]`

| Field | Type | Default |
|---|---|---|
| `x0` | `list[float] | NoneType` | `None` |
| `max_iter` | `int` | `required` |

### `[calibration_method.random_search]`

| Field | Type | Default |
|---|---|---|
| `n_samples` | `int` | `required` |
| `seed` | `int` | `required` |
| `log_scale_indices` | `list[int]` | `<factory>` |

### `[calibration_method.simplex]`

| Field | Type | Default |
|---|---|---|
| `x0` | `list[float] | NoneType` | `None` |
| `max_iter` | `int` | `required` |
| `max_fun` | `int | NoneType` | `None` |
| `xtol` | `float | NoneType` | `None` |
| `ftol` | `float | NoneType` | `None` |
| `disp` | `bool | NoneType` | `None` |

## Case Chronicle Schemas

### `cases/reservoir` chronicle

| Field | Type | Default |
|---|---|---|
| `n_days` | `int` | `365` |
| `start_year` | `int` | `2000` |
| `target_annual_precip_mm` | `float` | `800.0` |
| `precip_seed` | `int` | `42` |
| `runoff_coeff` | `float` | `0.15` |
| `losses_mm_day` | `float` | `1.5` |
| `losses_months` | `list[int]` | `<factory>` |
| `error_fraction` | `float` | `0.05` |
| `error_seed` | `int` | `12345` |
| `solver_backend` | `str` | `'analytic'` |
| `capacity_mm_true` | `float | NoneType` | `None` |
| `k_per_day_true` | `float | NoneType` | `None` |
| `s0_mm` | `float` | `0.0` |
| `a_true` | `float | NoneType` | `None` |
| `kq_days_true` | `float | NoneType` | `None` |
| `ks_days_true` | `float | NoneType` | `None` |
| `sq0_mm` | `float` | `0.0` |
| `ss0_mm` | `float` | `0.0` |

### `cases/recession_brutsaert` chronicle

| Field | Type | Default |
|---|---|---|
| `Q0` | `float` | `required` |
| `K` | `float` | `required` |
| `Sy` | `float` | `required` |
| `solution` | `str` | `'boussinesq'` |
| `A` | `float | NoneType` | `None` |
| `L` | `float | NoneType` | `None` |
| `b` | `float | NoneType` | `None` |
| `ag` | `float` | `0.7` |
| `p` | `float` | `0.346` |
| `n_points` | `int` | `50` |
| `log_spacing` | `bool` | `True` |
| `t_min_days` | `float` | `0.1` |
| `error_fraction` | `float` | `0.15` |
| `random_seed` | `int | NoneType` | `12345` |

## Notes

- For `da_mh_gp`, per-parameter keys (`proposal_scale`, `prior_mean`, `prior_std`, `gp_length_scale`) accept either:
  - a scalar (same value for all parameters), or
  - a mapping keyed by model parameter names.
- Unknown keys are rejected by all schemas (`extra="forbid"`).
