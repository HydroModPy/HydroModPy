# Calibration2 Case Cookbook

This cookbook is a practical onboarding guide to add a new calibration case.

## 1. Generate a case skeleton

Use the devkit scaffold helper:

```python
from hydromodpy.calibration2.devkit import scaffold_case

scaffold_case("my_case")
```

This creates `hydromodpy/calibration2/cases/my_case/` with:

- `case_config.py`
- `workflow.py`
- `case_implementation.py`
- `run_calibration.py`
- `config_calibration.toml`
- `README.md`

## 2. Adapt the chronicle schema

Edit `case_config.py`:

- keep strict validation with `ConfigDict(extra="forbid")`,
- define only `[chronicle]` fields required by your scientific case,
- return normalized Python values from `validate_*_config(...)`.

## 3. Implement the scientific workflow

Edit `workflow.py`:

- define `MODEL_PARAMETER_ORDER`,
- build your chronicle (`observed`, forcing/context, true params),
- implement `make_simulator(...)` with signature
  `simulator(params_dict) -> simulated_series`,
- optionally add a metric helper for case diagnostics.

## 4. Implement the calibration case adapter

Edit `case_implementation.py`:

- inherit `AbstractCalibrationCase`,
- `validate_case_config(...)`: call your chronicle validator,
- `build_case(...)`: return `CalibrationCaseContext`,
- `build_case_outputs(...)`: add case-specific outputs (metrics, series, etc.).

## 5. Configure TOML bounds and method kwargs

Edit one `config_calibration*.toml` file (default scaffold name is
`config_calibration.toml`):

- `[calibration]`: pick `objective_metric` and `global_method`,
- `[bounds]`: define all calibrated parameters,
- `[calibration_method.<method>]`: only keys valid for that method.

Use `docs/config_reference.md` for exact schema keys.

## 6. Validate and run

Validate the case package:

```python
from hydromodpy.calibration2.devkit import check_case

report = check_case("my_case")
print(report["ok"], report["errors"])
```

Run one full calibration:

```bash
python hydromodpy/calibration2/cases/my_case/run_calibration.py
```

## 7. Optional environment diagnosis

Use doctor report when onboarding fails:

```python
from hydromodpy.calibration2.devkit import run_doctor, format_doctor_report

print(format_doctor_report(run_doctor()))
```
