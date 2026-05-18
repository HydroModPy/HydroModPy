"""Nancon - Python script 03 - Load a TOML, override fields from Python.

This is the most common mixed-mode workflow:

1. Load the canonical TOML (reproducible source of truth).
2. Patch the validated config in Python via `model_copy(update=...)`
   on any nested sub-model.
3. Hand the patched config to `Project(...)`.
4. Optionally pass extra flow-parameter overrides at `project.run(...)`.

Two ways to override are shown here:

* config-level: walk to the nested Pydantic model you want to patch
  and rebuild it. The example below replaces the simulation window
  with a 1-year span and renames the run.
* run-level: keyword arguments to `project.run(...)`. Recognised keys
  are flow parameter ids (`K`, `Sy`, `Ss`), plus `thickness`,
  `first_clim`, `properties`. These do NOT rebuild the config; they
  patch the plan just before execution.

Launch:
    python examples/projects/11_nancon_watershed/python/03_toml_plus_overrides.py
"""

from pathlib import Path

import hydromodpy as hmp
from hydromodpy import HydroModPyConfig, SimulationTimeConfig

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
CONFIG_PATH = PROJECT_DIR / "01_run_simulation_nwt.toml"


# ---------------------------------------------------------------------
# 1. Load the validated config from disk
# ---------------------------------------------------------------------

cfg = HydroModPyConfig.from_toml(CONFIG_PATH)


# ---------------------------------------------------------------------
# 2. Config-level override - shorten the window, rename the run
# ---------------------------------------------------------------------

# Every sub-model is a Pydantic BaseModel, so `model_copy(update=...)`
# rebuilds it with the patched fields. Re-attach the rebuilt sub-models
# on the parent before validating the whole config.
patched_time = SimulationTimeConfig(
    start_datetime="2000-01-01",
    end_datetime="2000-12-31",
    step_value="1 month",
)

patched_simulation = cfg.simulation.model_copy(
    update={
        "name": "nancon_python_overrides",
        "description": "Nancon - TOML + Python overrides (1-year window).",
        "time": patched_time,
    }
)

cfg = cfg.model_copy(update={"simulation": patched_simulation})


# ---------------------------------------------------------------------
# 3. Open the project with the patched config
# ---------------------------------------------------------------------

project = hmp.Project(cfg)


# ---------------------------------------------------------------------
# 4. Run-level override - bump K, keep Sy / Ss / thickness from TOML
# ---------------------------------------------------------------------

run = project.run(K=1e-4)


# ---------------------------------------------------------------------
# 5. Inspect the effective parameters and close
# ---------------------------------------------------------------------

if run is not None:
    print(f"sim_id={run.sim_id} name={run.name} status={run.status}")
    print(f"effective K = {run.params.get('K')} m/s")

project.close()
