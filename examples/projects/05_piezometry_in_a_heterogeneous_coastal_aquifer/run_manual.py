"""Example 05 driven from Python: the coastal water-table gradient.

Same configuration as ``project.toml`` (Gouville coastal strip, steady,
MODFLOW 6 with a sea boundary). This script runs it and reads the
water-table field to report the head gradient from the shore to the inland
edge. No figure is built here: ``cross_section`` and ``piezometric_map`` are
named registry figures rendered via ``hmp.figure``.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/run_manual.py
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

# %% ---- COASTAL WATER-TABLE GRADIENT

# The sea boundary pins the water table to 0 m where the land is below sea
# level; recharge lifts it inland. The spread is the coastal head gradient.
head = np.asarray(hmp.read(run, "watertable_elevation", time=0), dtype="float64")
finite = head[np.isfinite(head)]
print(f"\nWater-table elevation (active cells): {finite.min():.2f} m (shore) to {finite.max():.2f} m (inland)")

seepage = np.asarray(hmp.read(run, "seepage_mask", time=0))
print(f"Seepage/sea cells at surface       : {int(np.nansum(seepage))} / {int(np.isfinite(head).sum())} active")

# %% ---- RENDER FIGURES

# The west-east section cuts from the sea into the aquifer.
hmp.figure(run, "cross_section", save=OUT, orientation="we")
hmp.figure(run, "piezometric_map", save=OUT)
print(f"\nFigures written under {OUT}")
