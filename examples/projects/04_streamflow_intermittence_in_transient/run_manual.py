"""Example 04 driven from Python: seasonal seepage intermittence.

Same configuration as ``project.toml`` (Nancon, monthly transient, MODFLOW
6). This script runs it, counts the seepage cells at every month to measure
how much the network breathes, and renders the seepage map at the wettest
and driest months. No figure is built here: ``seepage_map`` and
``hydrograph`` are named registry figures rendered via ``hmp.figure``, the
wet/dry timestep passed as an option.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py
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
print(f"sim_id  : {run.sim_id}")
print(f"periods : {run.n_timesteps} ({run.time_index[0]:%Y-%m} -> {run.time_index[-1]:%Y-%m})")

# %% ---- SEEPAGE INTERMITTENCE

# Seepage cells per month: the size of the wet (perennial + intermittent)
# network. Its swing between months is the intermittence.
counts = np.array(
    [int(np.asarray(run.field("seepage_mask", timestep=t)).sum()) for t in range(run.n_timesteps)]
)
wet = int(counts.argmax())
dry = int(counts.argmin())
index = run.time_index
print(f"\nSeepage cells    : {counts.min()} (dry) to {counts.max()} (wet)")
print(f"wettest month    : {index[wet]:%Y-%m} ({counts[wet]} cells)")
print(f"driest month     : {index[dry]:%Y-%m} ({counts[dry]} cells)")
print(f"intermittent part: {counts.max() - counts.min()} cells switch on/off over the record")

# %% ---- RENDER THE EXTREMES

# Same figure, two timesteps: the network at its widest and its narrowest.
hmp.figure(run, "seepage_map", save=OUT / "wettest", timestep=wet)
hmp.figure(run, "seepage_map", save=OUT / "driest", timestep=dry)
hmp.figure(run, "hydrograph", save=OUT)
print(f"\nFigures written under {OUT}")
