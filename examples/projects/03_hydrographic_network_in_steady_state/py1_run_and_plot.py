"""Play project.toml in the lab and change K from 1e-8 to 1e-3 m/s, to see how the network
that the water table feeds grows and shrinks. Each K is solved in memory, in a few seconds,
and only the share of the catchment that seeps is kept. Three values are then kept as runs,
and HydroModPy draws their seepage cells under the mapped streams and their water table.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
SECTION = [[323775.0, 6779400.0], [323775.0, 6773850.0]]

# %% Open the lab and build the model

lab = hmp.Lab(HERE / "project.toml")
state = lab.advance("build_geographic")
print(state.geographic)
state = lab.advance("load_data")
print(state.data)

# %% The mesh on the relief, before the solve

# A run stopped at `prepare_solver` stores the ground of every cell, so it draws the mesh
# with the mapped streams.
state = lab.advance("prepare_solver")
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography",
        overlays=["mesh", "outline", "network", "outlet"],
        save=FIGURES / "mesh_on_relief.png",
    )
)

# %% Which cells can seep

# A cell seeps when the water table reaches its ground. The ground of each cell is the top
# of the model, and the catchment is the polygon cut from the DEM.
ground = state.model.geometry.column.top
centres = state.mesh.cell_centers()
polygon = gpd.read_file(state.model.geometry.catchment.watershed_shp).union_all()
inside = shapely.contains_xy(polygon, centres[:, 0], centres[:, 1])
print(f"{inside.sum()} cells in the catchment")

# %% Ten values of K, solved in memory

# `lab.set(K=...)` makes the two solver steps stale, and `lab.read` solves again. Nothing is
# written to runs/.
rows = []
for k in np.geomspace(1e-8, 1e-3, 10):
    lab.set(K=k)
    head = lab.read("head").to_numpy()[0]
    seeps = head >= ground
    rows.append(
        {
            "K (m/s)": k,
            "seepage (% of the catchment)": seeps[inside].mean() * 100,
            "water-table depth (m)": (ground - np.minimum(head, ground))[inside].mean(),
            "discharge (m3/day)": float(lab.read("discharge").squeeze()) * 86400,
        }
    )
sweep = pd.DataFrame(rows).set_index("K (m/s)")
print(sweep.to_string(float_format="{:.3g}".format))

# Under 1e-7 m/s the aquifer cannot carry the recharge and the whole catchment seeps.
# At 1e-3 m/s it carries it all under the ground, and no cell seeps.
fig, ax = plt.subplots(figsize=(5, 4))
ax.plot(sweep.index, sweep["seepage (% of the catchment)"], "o-", color="k")
ax.set_xscale("log")
ax.set_xlabel("K (m/s)")
ax.set_ylabel("seepage (% of the catchment)")
ax.grid(alpha=0.3)
fig.savefig(FIGURES / "seepage_against_k.png", dpi=150, bbox_inches="tight")

# %% Three values kept as runs

# Each run writes the figures and the files of project.toml. The middle one is the K of the
# file, so its run is the run of project.toml.
runs = {}
for label, k in (("low", 4.6e-7), ("file", 1e-5), ("high", 2.8e-4)):
    lab.set(K=k)
    runs[label] = lab.run(None if label == "file" else f"canut_k_{label}")
lab.close()

# %% The seepage cells and the water table of each run

# `run.figure` draws from the sealed run, so nothing is solved again.
for label, run in runs.items():
    print(run.name, run.parameters.loc["K", "value"], "m/s")
    print(
        run.figure(
            "simulated_active_network",
            overlays=["relief", "network", "outline"],
            save=FIGURES / f"seepage_network_{label}.png",
        )
    )
    print(
        run.figure(
            "watertable_elevation",
            type="section",
            line=SECTION,
            save=FIGURES / f"section_{label}.png",
        )
    )

# %% The files for QGIS

for path in runs["file"].exports:
    print(path)
