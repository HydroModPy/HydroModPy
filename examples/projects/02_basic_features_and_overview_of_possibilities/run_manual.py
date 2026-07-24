"""Example 02 driven from Python: the full pipeline on a conceptual domain.

Same configuration as ``project.toml`` (conceptual catchment, steady,
MODFLOW 6). This script runs it and inspects what came out of the pipeline.
No figure is built here: the maps below are named registry figures rendered
via ``hmp.figure``.

To explore the recharge cases (dry / normal / wet), change the ``values``
entry of ``[[data.recharge.sources]]`` in project.toml and re-run: a higher
recharge raises the water table, so more cells outcrop as seepage.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/02_basic_features_and_overview_of_possibilities/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import numpy as np

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"
OUT = HERE / "figures" / "from_python"

# %% ---- RUN

run = hmp.run(CONFIG, force=True)
print(f"sim_id     : {run.sim_id}")
print(f"grid       : {run.grid.shape} cells of {run.grid.cell_size:g} m")
print(f"parameters : {run.params}")

# %% ---- WATER TABLE AND SEEPAGE

# Cells outside the catchment are inactive (NaN), so reduce over finite values.
depth = np.asarray(hmp.read(run, "watertable_depth", time=0), dtype="float64")
seepage = np.asarray(hmp.read(run, "seepage_mask", time=0))
finite = depth[np.isfinite(depth)]
print(
    f"\nWater-table depth (active cells): "
    f"min {finite.min():.2f} m, mean {finite.mean():.2f} m, max {finite.max():.2f} m"
)
print(f"Seepage cells    : {int(np.nansum(seepage))} / {int(np.isfinite(depth).sum())} active")

# %% ---- WATER BALANCE

budget = run.budget().groupby("component")[["flux_in", "flux_out"]].sum()
print("\nSteady budget by component (m3/s):")
print(budget.to_string())
imbalance = float((budget["flux_in"] - budget["flux_out"]).sum())
print(f"closure (in - out) = {imbalance:.2e} m3/s")

# %% ---- RENDER FIGURES

for name in ("mesh_map", "piezometric_map", "seepage_map", "cross_section"):
    hmp.figure(run, name, save=OUT)
print(f"\nFigures written under {OUT}")
