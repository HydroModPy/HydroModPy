"""Play project.toml in the lab to watch the model take shape: look at its objects, load
the mesh in a variable, read its parameters and try another K. Then keep the model as a
run. HydroModPy draws every figure: the mesh on the relief before the solve, the figures
project.toml lists, and two more asked from Python. The files of [[export]] are then listed,
the particle tracks for QGIS among them.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time.
lab = hmp.Lab(HERE / "project.toml")

# %% Look at the objects

# `lab.state` keeps the objects of the engine by name. Each one prints a short summary,
# so its name typed at the prompt says what it is and where its arrays are.
state = lab.advance("prepare_solver")
print(state)

# %% The mesh in a variable

# The mesh says its cells, its area and its extent. The mesh of a lab and the mesh of a run
# answer the same calls, on a regular grid and on triangles or polygons alike, and every
# array has one row per cell.
mesh = state.mesh
print(mesh)
centres, areas = mesh.cell_centers(), mesh.cell_areas()
# Only a regular grid has a shape. It folds a value per cell into rows and columns.
if mesh.structured_shape is not None:
    ground = state.model.geometry.column.top.reshape(mesh.structured_shape)
    print(f"ground in {ground.shape} rows and columns, {ground.min():.1f} to {ground.max():.1f} m")

# %% The model and its parameters

# `prepare_solver` freezes the model the solver reads. It prints its size, its periods,
# its properties and its terms, and `properties` gives the value of each parameter.
model = state.model
print(model)
print(model.properties)
print("K written in the file:", lab.config.flow.param["K"].field.value, "m/s")
# The wells map a name to a position and a rate.
for name, well in model.wells.items():
    peak = -min(well.flux) * 86400
    print(f"{name}: x = {well.location.x:.0f} m, y = {well.location.y:.0f} m, {peak:.0f} m³/day")

# %% The mesh on the relief, before the solve

# A run stopped at `prepare_solver` already stores the ground of every cell, so it draws
# the relief under the mesh. It has no seal yet: `lab.run` finishes it further down.
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography", overlays=["mesh", "network", "outlet"], save=FIGURES / "mesh_on_relief.png"
    )
)

# %% Solve and read the head

# `lab.read` solves what is stale, then reads a variable of the solve: one row per period,
# one column per cell. Nothing is written to runs/.
head = lab.read("head", time="first")
print(f"mean head in January, K = 1e-5 m/s: {float(head.mean()):.3f} m")
print(lab.read("discharge").to_series().round(4).to_string())

# %% Change K

# A new K makes the model stale, and only the two solver steps play again.
lab.set(K=5e-5)
print(lab.steps[["step", "status"]].query("status != 'built'").to_string(index=False))
head = lab.read("head", time="first")
print(f"mean head in January, K = 5e-5 m/s: {float(head.mean()):.3f} m")

# %% Keep the run

# Back to the K of the file: the lab forgets changes that bring it back to the
# file, so the run kept is the run of project.toml.
# The test with K = 5e-5 m/s stays in the lab and leaves no trace.
lab.set(K=1e-5)
run = lab.run()
print(run.name)
lab.close()

# %% Read the run

# A sealed run gives the same things back from disk: its mesh, its parameters as a table,
# and each stored variable as an array with named axes.
print(run.mesh)
print(run.parameters)
depth = run.read("watertable_depth", time=0)
print(f"water-table depth in January: {dict(depth.sizes)}, mean {float(depth.mean()):.2f} m")

# %% The figures of the run

# The [display] list of project.toml is drawn when the run is sealed: the catchment card,
# the maps, the section through the two wells, the particle tracks and the water budget.
for path in run.figures:
    print(path)

# %% Two more figures, asked from Python

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run,
# so nothing is solved again. Without `save` it gives back the matplotlib figure.
# The section through the two wells again, in September.
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[152700.0, 6858862.5], [152700.0, 6856762.5]],
        time="2017-09-15",
        save=FIGURES / "section_through_wells_september.png",
    )
)
# The water-table depth of January with the well cells and the seepage cells,
# its colours bounded at 10 m.
print(
    run.figure(
        "watertable_depth",
        time="2017-01-15",
        overlays=["outline", "network", "wells", "seepage"],
        limits=[0.0, 10.0],
        save=FIGURES / "watertable_depth_wells_and_seepage.png",
    )
)

# %% The numbers behind a figure

# With `data=True` a figure gives its tables and draws nothing. Table `a` of the water
# budget holds one row per month and per term, in mm per day over the catchment.
budget = run.figure("water_budget", data=True)["a"]
print(budget.pivot(index="time", columns="variable", values="simulated").round(3).to_string())

# %% The files for QGIS

# The [[export]] blocks of project.toml wrote these files when the run was sealed. The
# particle tracks are among them: one line per particle, from the cell it was released
# in to where it leaves the aquifer, with its travel time in years.
for path in run.exports:
    print(path)
# `run.export` takes the words of an [[export]] block. The tracks again, in longitude
# and latitude.
print(run.export("pathlines", file="pathlines_wgs84.gpkg", crs="EPSG:4326"))
