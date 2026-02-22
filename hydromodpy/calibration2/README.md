# Calibration2

`hydromodpy/calibration2/` centralizes generic calibration code and runnable
scientific cases.

## Directory Map

```text
hydromodpy/calibration2/
|-- core/
|   |-- engine.py
|   |-- parameters.py
|   |-- results.py
|   |-- objective_function.py
|   |-- engine_config.py
|   |-- methods_config.py
|   |-- methods_dispatcher.py
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
|-- cases/
|   |-- reservoir/
|   |   |-- run_forward.py
|   |   |-- run_calibration.py
|   |   |-- workflow.py
|   |   |-- synthetic_data.py
|   |   |-- plotting.py
|   |   |-- case_config.py
|   |   `-- models/
|   |       |-- one_reservoir.py
|   |       `-- two_reservoirs.py
|   `-- recession_brutsaert/
|       |-- run_forward.py
|       |-- run_calibration.py
|       |-- workflow.py
|       `-- case_config.py
`-- uml/
    |-- calibration2_calibration_activity.wsd
    |-- calibration2_calibration_sequence.wsd
    |-- calibration2_reservoir_sequence.wsd
    |-- calibration2_workflow.wsd
    |-- calibration2_core_classes_config.wsd
    `-- calibration2_core_classes_main.wsd
```

## Structure (What Goes Where)

- `core/`: generic calibration engine, parameter handling, method dispatch, and canonical result objects.
- `core/methods/`: one file per calibration algorithm.
- `analysis/`: shared diagnostics and plotting helpers reusable across cases.
- `cases/`: runnable scientific examples with case-specific data generation and workflows.
- `cases/reservoir/models/`: hydrological model equations and parameter order per reservoir variant.
- `uml/`: PlantUML `.wsd` diagrams documenting architecture and execution flows.

## Shared API

All cases follow the same flow:

1. Build a case-specific simulator:
   `simulator(params_dict) -> simulated_series`
2. Instantiate `CalibrationEngine(...)` with observed data, parameter bounds
   (`bounds` or `CalibrationParameterSet`), and metric.
3. Run `calibrate(method=..., **method_kwargs)` and consume
   `CalibrationResults`.

## How To Use Calibration2

### Option A: Direct Python API

Use this when you already have observed data and a simulator function.

```python
import numpy as np

from hydromodpy.calibration2.core.engine import CalibrationEngine
from hydromodpy.calibration2.core.parameters import CalibrationParameterSet

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
- load and validate with `load_calibration_toml(...)`;
- resolve engine-ready settings with `resolve_calibration_settings(...)`;
- run `CalibrationEngine.calibrate(...)`.

This is the pattern used in `cases/reservoir/` and `cases/recession_brutsaert/`.

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

1. Create a new case folder under `hydromodpy/calibration2/cases/<your_case>/`.
2. Implement your forward model wrapper:
   `simulator(params_dict) -> simulated_series` with output shape matching `observed`.
3. Add case configuration validation in `case_config.py` (Pydantic model).
4. Add a `workflow.py` that:
   - builds the simulator adapter,
   - calls `resolve_calibration_settings(...)`,
   - instantiates `CalibrationEngine`,
   - returns a structured payload (`result`, diagnostics, calibrated series).
5. Add a short `run_calibration.py` script that only orchestrates:
   config loading, chronicle/data building, calibration, summary, and plotting.
6. Add one `README.md` and one `config_calibration.toml` in the case folder.

What usually stays unchanged:
- `core/engine.py`, `core/parameters.py`, `core/results.py`, `core/objective_function.py`.
- existing calibration methods in `core/methods/`.

When you need a new calibration algorithm:
1. add one file in `core/methods/<new_method>.py`,
2. register it in `core/methods_dispatcher.py`,
3. define/validate its kwargs in `core/methods_config.py`.

## Case Readmes

- `hydromodpy/calibration2/cases/reservoir/README.md`
- `hydromodpy/calibration2/cases/recession_brutsaert/README.md`

## UML

- Calibration sequence (`.wsd`): `hydromodpy/calibration2/uml/calibration2_calibration_sequence.wsd`
- Calibration activity (`.wsd`): `hydromodpy/calibration2/uml/calibration2_calibration_activity.wsd`
- Reservoir case sequence (`.wsd`): `hydromodpy/calibration2/uml/calibration2_reservoir_sequence.wsd`
- Sequence diagram (`.wsd`): `hydromodpy/calibration2/uml/calibration2_workflow.wsd`
- Class diagram - config (+ key module functions) (`.wsd`): `hydromodpy/calibration2/uml/calibration2_core_classes_config.wsd`
- Class diagram - main runtime (+ key module functions) (`.wsd`): `hydromodpy/calibration2/uml/calibration2_core_classes_main.wsd`
