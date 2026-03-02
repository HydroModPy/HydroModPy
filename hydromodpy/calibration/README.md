# Calibration

`hydromodpy/calibration/` centralizes generic calibration code and runnable
scientific cases.

## Directory Map

```text
hydromodpy/calibration/
|-- core/
|   |-- engine.py
|   |-- parameters.py
|   |-- results.py
|   |-- objective_function.py
|   |-- engine_config.py
|   |-- methods_config.py
|   |-- methods_dispatcher.py
|   |-- case_interface.py
|   |-- case_orchestrator.py
|   `-- methods/
|       |-- grid_search.py
|       |-- random_search.py
|       |-- nelder_mead.py
|       |-- simplex.py
|       |-- gp_mapping.py
|       `-- da_mh_gp.py
|-- analysis/
|   |-- diagnostics.py
|   `-- plotting.py
|-- devkit/
|   |-- new_case.py
|   |-- check_case.py
|   |-- doctor.py
|   |-- config_reference.py
|   `-- templates/
|       `-- case/
|           |-- __init__.py.tmpl
|           |-- README.md.tmpl
|           |-- case_config.py.tmpl
|           |-- workflow.py.tmpl
|           |-- case_implementation.py.tmpl
|           |-- run_calibration.py.tmpl
|           `-- config_calibration.toml.tmpl
|-- docs/
|   |-- case_cookbook.md
|   `-- config_reference.md
|-- cases/
|   |-- utils/
|   |   `-- forcing.py
|   |-- reservoir/
|   |   |-- run_forward.py
|   |   |-- run_calibration.py
|   |   |-- case_implementation.py
|   |   |-- workflow.py
|   |   |-- synthetic_data.py
|   |   |-- plotting.py
|   |   |-- case_config.py
|   |   `-- models/
|   |       |-- one_reservoir.py
|   |       `-- two_reservoirs.py
|   |-- groundwater_1d/
|   |   |-- run_forward.py
|   |   |-- run_calibration.py
|   |   |-- case_implementation.py
|   |   |-- workflow.py
|   |   |-- synthetic_data.py
|   |   |-- plotting.py
|   |   |-- case_config.py
|   |   `-- model.py
|   `-- recession_brutsaert/
|       |-- run_profile.py
|       |-- run_metrics.py
|       |-- run_calibration.py
|       |-- case_implementation.py
|       |-- workflow.py
|       `-- case_config.py
`-- uml/
    `-- README.md
```

## Structure (What Goes Where)

- `core/`: generic calibration engine, parameter handling, method dispatch, and canonical result objects.
- `core/methods/`: one file per calibration algorithm.
- `analysis/`: shared diagnostics and plotting helpers reusable across cases.
- `devkit/`: onboarding and maintenance helpers (new case scaffold, checks, doctor report, config-reference generation).
- `docs/`: onboarding cookbook and generated schema reference.
- `cases/`: runnable scientific examples with case-specific data generation and workflows.
- `cases/utils/`: shared case-level helpers reusable across multiple cases (for example forcing generators).
- `cases/reservoir/models/`: hydrological model equations and parameter order per reservoir variant.
- `uml/`: module-local README with links to UML sources in docs.

## Shared API

All cases follow the same flow:

1. Build a case-specific simulator:
   `simulator(params_dict) -> simulated_series`
2. Instantiate `CalibrationEngine(...)` with observed data, parameter bounds
   (`bounds` or `CalibrationParameterSet`), and metric.
3. Run `calibrate(method=..., **method_kwargs)` and consume
   `CalibrationResults`.

## How To Use Calibration

### Option A: Direct Python API

Use this when you already have observed data and a simulator function.

```python
import numpy as np

from hydromodpy.calibration.core.engine import CalibrationEngine
from hydromodpy.calibration.core.parameters import CalibrationParameterSet

observed = np.asarray([...], dtype=float)

def simulator(params):
    # params is a dict keyed by parameter names, for example:
    # {"a": ..., "Kq": ..., "Ks": ...}
    return np.asarray([...], dtype=float)

parameter_set = CalibrationParameterSet.from_bounds(
    {"a": (0.01, 0.99), "Kq": (0.1, 20.0), "Ks": (1.0, 200.0)}
)

engine = CalibrationEngine(
    observed=observed,
    simulator=simulator,
    parameter_set=parameter_set,
    objective_metric="kge",
)

result = engine.calibrate(
    method="simplex",
    maxiter=500,
    seed=42,
)

print(result.params_best)
print(result.score_best, result.cost_best, result.n_evaluations)
```

What you get from `CalibrationResults`:
- `x_best` and `params_best`: best calibrated parameters (vector and named mapping).
- `score_best`: value of the selected metric (`nse`, `nse_log`, `kge`, `rmse`, `mae`).
- `cost_best`: minimization cost used internally by optimizers.
- `n_evaluations`: number of expensive forward-model evaluations.
- `samples` (optional): posterior/chain samples for sampling-based methods.

### Option B: TOML-Driven Workflow

Use this for reproducible runs in scripts/cases:
- define `[chronicle]`, `[calibration]`, `[bounds]`, and `[calibration_method.<method>]`;
- optional `[output]` controls figures (including objective-surface panel);
- implement one case class inheriting `AbstractCalibrationCase`;
- execute through `run_calibration_case_from_toml(...)` in
  `core/case_orchestrator.py`.

This is the pattern used in `cases/reservoir/` and `cases/recession_brutsaert/`.

### Option C: Devkit Helpers (No CLI)

Use these helpers from Python to speed up onboarding:

```python
from hydromodpy.calibration.devkit import (
    scaffold_case,
    check_case,
    run_doctor,
    format_doctor_report,
    write_config_reference_markdown,
)

scaffold_case("my_new_case")
print(check_case("my_new_case"))
print(format_doctor_report(run_doctor()))
write_config_reference_markdown()
```

## Calibration Convention

- `[bounds]` must define all parameters of the selected model.
- Config validation is strict:
  - unknown top-level sections are rejected,
  - unknown keys in `[calibration]` are rejected,
  - `objective_metric` and `global_method` must use canonical names.
- Unknown keys in `[calibration_method.<method>]` are rejected for built-in
  methods.
- Per-parameter method settings can be passed as explicit mappings, e.g.
  `proposal_scale = {a=0.05, Kq=0.5, Ks=5.0}`.
- Optional objective-surface plotting:
  - `output.show_objective_surface`
  - `output.objective_surface_n_evaluations`
  - auto-disabled by schema when calibrated parameter count is >= 3.
  - sampling/interpolation defaults:
    - 1D: regular sampling + GP interpolation (linear fallback),
    - 2D: Sobol sampling + GP interpolation (IDW fallback),
    - log-space sampling is auto-enabled per parameter when bounds span
      multiple orders of magnitude.

## Available Methods

- `grid_search`
- `random_search`
- `nelder_mead`
- `simplex`
- `gp_mapping`
- `da_mh_gp`

For `da_mh_gp`, `objective_metric = "rmse"` must be used.

## How To Adapt Calibration2 To A New Case

Minimal checklist:

1. Create a new case folder under `hydromodpy/calibration/cases/<your_case>/`.
2. Implement your forward model wrapper:
   `simulator(params_dict) -> simulated_series` with output shape matching `observed`.
3. Add case configuration validation in `case_config.py` (Pydantic model).
4. Add a `case_implementation.py` class inheriting `AbstractCalibrationCase`
   with:
   - `validate_case_config(...)`
   - `build_case(...)` returning `CalibrationCaseContext`
   - optional `build_case_outputs(...)`
5. Add a `workflow.py` that:
   - builds the simulator adapter,
   - computes case-specific diagnostics and plotting payloads.
6. Add a short `run_calibration.py` script that only orchestrates:
   config loading, `run_calibration_case_from_toml(...)`, summary, and plotting.
7. Add one `README.md` and at least one `config_calibration*.toml` file in the case folder.

Shortcut:
- `scaffold_case("<your_case>")` auto-generates this skeleton from templates.
- `check_case("<your_case>")` validates required files + case contract.

What usually stays unchanged:
- `core/engine.py`, `core/parameters.py`, `core/results.py`, `core/objective_function.py`.
- existing calibration methods in `core/methods/`.

When you need a new calibration algorithm:
1. add one file in `core/methods/<new_method>.py`,
2. register it in `core/methods_dispatcher.py`,
3. define/validate its kwargs in `core/methods_config.py`.

## Case Readmes

- `hydromodpy/calibration/cases/reservoir/README.md`
- `hydromodpy/calibration/cases/groundwater_1d/README.md`
- `hydromodpy/calibration/cases/recession_brutsaert/README.md`

## Onboarding Docs

- Case cookbook: `hydromodpy/calibration/docs/case_cookbook.md`
- Config reference: `hydromodpy/calibration/docs/config_reference.md`

## UML

- Local pointer README: `hydromodpy/calibration/uml/README.md`
- Canonical UML sources: `docs/readthedocs/source/architecture/calibration/diagrams/`
- Architecture page: `docs/readthedocs/source/architecture/calibration/calibration-uml-diagrams.rst`
