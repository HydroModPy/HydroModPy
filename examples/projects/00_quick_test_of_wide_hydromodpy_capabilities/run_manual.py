"""Example 00 driven from Python instead of the CLI.

Same configuration, same results, same figures as ``hmp run project.toml``:
the TOML stays the single source of truth and this script only manipulates
the objects the public API returns.

No figure is built here. Figures are named entries of the HydroModPy
registry, requested either through ``[display].figures`` in the TOML or
through ``hmp.figure(run, name)`` below.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an
IDE::

    python examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"

# %% ---- RUN THE SIMULATION

# The TOML is the source of truth; hmp.run returns the persisted Run.
run = hmp.run(CONFIG, force=True)

# %% ---- DESCRIBE THE RUN

print(f"sim_id      : {run.sim_id}")
print(f"name        : {run.name}")
print(f"solver      : {run.solver}")
print(
    f"periods     : {run.n_timesteps} "
    f"({run.time_index[0]:%Y-%m-%d} -> {run.time_index[-1]:%Y-%m-%d})"
)
print(f"grid        : {run.grid.shape} cells of {run.grid.cell_size:g} m")
print(f"parameters  : {run.params}")

# %% ---- WATER BALANCE

# Budget by component, summed over the periods (m3/s). Names are canonical
# (recharge / drain / well), whatever the solver.
budget = run.budget().groupby("component")[["flux_in", "flux_out"]].sum()
print("\nBudget by component (sum of period rates, m3/s):")
print(budget.to_string())

# %% ---- TIMESERIES

discharge = hmp.read(run, "discharge", sel={"station": "_catchment"})
pumping = hmp.read(run, "well_pumping", sel={"station": "_catchment"})
print("\nCatchment discharge (m3/s), first and last period:")
print(discharge.iloc[[0, -1]].to_string())
print("\nTotal well pumping (m3/s), first and last period:")
print(pumping.iloc[[0, -1]].to_string())

# %% ---- SPATIAL FIELDS

depth = hmp.read(run, "watertable_depth", time=-1)
seepage = hmp.read(run, "seepage_mask", time=-1)
print(
    f"\nWater-table depth at the last period: "
    f"min {depth.min():.2f} m, mean {depth.mean():.2f} m, max {depth.max():.2f} m"
)
print(f"Seepage cells at the last period     : {int(seepage.sum())} / {seepage.size}")

# %% ---- RENDER FIGURES

# hmp.figure is the Python door on the figure registry: same names and
# options as [display].figures / [display.overrides] in the TOML.
out_dir = HERE / "figures" / "from_python"

hmp.figure(run, "mesh_map", save=out_dir)
hmp.figure(run, "piezometric_map", save=out_dir)
hmp.figure(run, "seepage_map", save=out_dir)
hmp.figure(run, "flux_timeseries", save=out_dir)

# Per-figure options, mirroring [display.overrides] in the TOML.
hmp.figure(run, "cross_section", save=out_dir, orientation="sn")
hmp.figure(
    run,
    "watertable_depth_map",
    save=out_dir,
    overlays=["watershed", "seepage", "particles", "wells", "outlet"],
)

print(f"\nFigures written to {out_dir}")
