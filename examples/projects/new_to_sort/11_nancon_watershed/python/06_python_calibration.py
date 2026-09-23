"""Nancon - Python script 06 - Calibration driven from Python.

Two equivalent ways to run a calibration:

* TOML mode: hand a calibration TOML to `project.calibrate(config_path=...)`.
  This is identical to `hmp run 05_run_calibration_k.toml`.
* Python mode: declare parameters / outputs / objective_blocks as
  Python dicts and pass them directly to `project.calibrate(...)`.
  This is useful for programmatic studies (e.g. driving the same loop
  with several budgets, or wiring the optimiser into a notebook).

Both modes write to the same `calibration_iterations` table.

Launch:
    python examples/projects/11_nancon_watershed/python/06_python_calibration.py
"""

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
PROJECT_TOML = PROJECT_DIR / "project.toml"
CALIBRATION_TOML = PROJECT_DIR / "05_run_calibration_k.toml"


# ---------------------------------------------------------------------
# 1. Calibration from TOML
# ---------------------------------------------------------------------

print("== Calibration from TOML ==")

project = hmp.Project(PROJECT_TOML, no_display=True)

report = project.calibrate(config_path=CALIBRATION_TOML)
print(f"[toml] calibration finished, report type = {type(report).__name__}")

project.close()


# ---------------------------------------------------------------------
# 2. Calibration from Python (declarations as kwargs)
# ---------------------------------------------------------------------

print()
print("== Calibration from Python dicts ==")

project = hmp.Project(PROJECT_TOML, no_display=True)

parameters = {
    "K": {
        "bounds": [1e-6, 1e-3],
        "transform": "log",
        "prior": "log_uniform",
        "path": "flow.param.K.field.value",
        "units": "m/s",
    },
}

# `objective=` in Python mode names a `module.path:callable` entry point, not
# a metric: `Project.calibrate` never puts it in the config payload, so
# `objective="kge"` here was silently ignored and the search scored the
# default (NSE on head) all along. The metric goes in `objective_blocks=`
# instead, which needs a matching declared output to read: NANCON is the
# Nancon gauge this project's `[data.hydrometry]` extent already loads (same
# coordinates as `examples/projects/04_streamflow_intermittence_in_transient`,
# same watershed).
outputs = {
    "discharge": {
        "support": "point",
        "variable": "discharge",
        "observes": "NANCON",
        "x": 389285.910,
        "y": 6816518.749,
    },
}

objective_blocks = [
    {
        "name": "discharge_kge",
        "metric": "kge",
        "uses_outputs": ["discharge"],
    },
]

report = project.calibrate(
    method="optuna",
    max_iter=3,
    seed=42,
    save_runs="best_n",
    save_best_n=1,
    outputs=outputs,
    objective_blocks=objective_blocks,
    parameters=parameters,
)
print(f"[python] calibration finished, report type = {type(report).__name__}")

project.close()
