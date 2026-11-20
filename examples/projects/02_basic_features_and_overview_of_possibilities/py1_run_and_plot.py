"""Play project.toml in the lab, one step at a time, and try other inputs before keeping a
run. The domain is the whole DEM, the recharge changes from cell to cell, the base of the
aquifer mirrors the relief and K falls in three bands of depth. From Python the script then
spreads the same recharge evenly, and gives the aquifer one K, and says how the water table
answers. Nothing of these trials is written. The run kept is the run of project.toml.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The domain and the data

# With kind = "dem" the domain is the DEM itself: each pixel with an elevation is a cell.
state = lab.advance("build_geographic")
print(state.geographic)

# `load_data` reads the DEM, the base of the aquifer and the recharge, one value per pixel.
state = lab.advance("load_data")
print(state.data)
recharge = state.data.recharge.fields[0].data["recharge"]
print(f"recharge from {float(recharge.min()):.2f} to {float(recharge.max()):.2f} mm/day")

# %% The mesh on the relief, before the solve

# A run stopped at `prepare_solver` stores the ground of every cell, so it draws the mesh.
state = lab.advance("prepare_solver")
print(state.mesh)
before = lab.run(until_step="prepare_solver")
print(before.figure("topography", overlays=["mesh", "outline"], save=FIGURES / "mesh.png"))

# %% The ten layers and their K

# The MODFLOW 6 model is written, not solved. Each layer takes the band of K of its base,
# and a layer of one rank is thicker under the hills, so it may hold two values of K.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
active = mf6.dis.idomain.array[0] > 0
ground = mf6.dis.top.array[active]
bases = mf6.dis.botm.array[:, active]
tops = np.vstack([ground, bases[:-1]])
k = mf6.npf.k.array[:, active]
layers = pd.DataFrame(
    {
        "thickness (m)": (tops - bases).mean(axis=1),
        "base depth (m)": (ground - bases).mean(axis=1),
        "K 1e-5 (%)": (np.isclose(k, 1e-5) * 100).mean(axis=1),
        "K 1e-7 (%)": (np.isclose(k, 1e-7) * 100).mean(axis=1),
        "K 1e-8 (%)": (np.isclose(k, 1e-8) * 100).mean(axis=1),
    },
    index=pd.RangeIndex(1, len(bases) + 1, name="layer"),
)
print(layers.round(1).to_string())

# %% Solve, then try two other inputs


# `lab.read` solves what is stale and reads the solve. Each `lab.set` makes stale only the
# steps that read what changed, so the domain and the mesh are not built again.
def water_table() -> str:
    head = lab.read("head").to_numpy()[0, active.ravel()]
    discharge = float(lab.read("discharge").squeeze()) * 86400
    return f"water table {head.mean():.2f} m on average, discharge {discharge:.0f} m3/day"


print("project.toml:", water_table())

# The values of the file, to come back to them.
file_recharge = lab.config.data.recharge.sources
file_profile = lab.config.flow.param["K"].field_vertical_profile

# The mean of the recharge map in every cell.
mean = round(float(recharge.mean()), 3)
lab.set({"data.recharge.sources": [{"source": "synthetic", "values": [mean]}]})
print(f"{mean} mm/day everywhere:", water_table())

# Back to the recharge map, and one K over the whole depth.
lab.set({"data.recharge.sources": file_recharge})
lab.set({"flow.param.K.field_vertical_profile": {"kind": "none"}})
print("one K:", water_table())

# %% Keep the run of project.toml

# Back to the file: the lab forgets changes that bring it back, so the run kept is the run
# of project.toml. The figures and the files of project.toml are written with it.
lab.set({"flow.param.K.field_vertical_profile": file_profile})
print(lab.steps[["step", "status"]].to_string(index=False))
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% One more figure, asked from Python

# The water table from north to south through the middle of the relief.
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[142537.0, 6849100.0], [142537.0, 6844900.0]],
        save=FIGURES / "section_north_south.png",
    )
)

# %% The files for QGIS

for path in run.exports:
    print(path)
