"""Example 03 driven from Python: a hydraulic-conductivity sweep.

Same configuration as ``project.toml`` (Canut, steady, MODFLOW 6), plus the
sweep that is the point of this example: raising or lowering K reshapes the
simulated active network. Each K is a separate simulation obtained with one
parameter override; no figure is built here, they are named registry
figures rendered through ``hmp.figure``.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/03_hydrographic_network_in_steady_state/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"

# Hydraulic conductivities to explore, m/s (log-spaced, low to high).
K_VALUES = [1e-7, 1e-6, 1e-5, 1e-4]

# %% ---- OPEN THE PROJECT

project = hmp.Project(CONFIG)

# %% ---- BASELINE RUN

run = project.simulate(name="canut_steady_mf6")
print(f"baseline sim_id : {run.sim_id}")
print(f"grid            : {run.grid.shape} cells of {run.grid.cell_size:g} m")
print(f"parameters      : {run.params}")

# %% ---- K SWEEP

# One simulation per K, overriding the single homogeneous K field. Each
# figure lands in the run it describes, exactly where `hmp run` puts it:
# <project>/runs/<run>/figures/. The project root stays clean.
catalog = project.store
runs = {}
figure_dirs = {}
for k in K_VALUES:
    name = f"canut_K_{k:.0e}"
    runs[k] = project.simulate(name=name, K=k)
    figure_dirs[k] = catalog.run_dir_for(runs[k].sim_id) / "figures"
    hmp.figure(runs[k], "simulated_active_network", save=figure_dirs[k])
    print(f"K = {k:.0e} m/s -> sim {runs[k].sim_id}")

# %% ---- COMPARE THE ACTIVE NETWORK EXTENT

# The active-cell count grows as K drops (a tighter aquifer keeps the water
# table shallow, so more cells sustain a drain outflow).
print("\nActive drainage cells per K:")
for k in K_VALUES:
    active = hmp.read(runs[k], "accumulation_flux", time=0)
    print(f"  K = {k:.0e} m/s : {int((active > 0).sum())} cells")

print("\nPer-K figures:")
for k in K_VALUES:
    print(f"  K = {k:.0e} m/s : {figure_dirs[k]}")
