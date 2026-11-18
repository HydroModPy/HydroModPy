"""Play project.toml in the lab, one step at a time, then give Sy three values and keep a run
for each. The recharge and the runoff are drawn after `load_data`, the mesh on the relief after
`prepare_solver`. For each Sy the script finds the months when the catchment seeps the least
and the most, and HydroModPy draws the seepage cells and the water table of these two months,
the share of the run each cell seeps, and the discharge against the gauge.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
# South to north through the outlet, across the valley.
SECTION = [[389175.0, 6815000.0], [389175.0, 6826000.0]]

# %% Open the lab

lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The catchment and its forcing

state = lab.advance("load_data")
print(state.geographic)
print(state.data)

# The recharge and the runoff of the gauge, one value per month in mm/day. The model takes
# the recharge, and the runoff is added to the drain flow to give the discharge.
forcing = pd.DataFrame(
    {
        name: getattr(state.data, name).points[0].data.set_index("datetime")["value"]
        for name in ("recharge", "runoff")
    }
)
print(forcing.describe().round(2).to_string())
fig, ax = plt.subplots(figsize=(7, 3))
ax.plot(forcing.index, forcing["recharge"], color="dodgerblue", lw=2, label="recharge")
ax.plot(forcing.index, forcing["runoff"], color="navy", lw=2, label="runoff")
ax.set_ylabel("mm/day")
ax.legend()
fig.savefig(FIGURES / "recharge_and_runoff.png", dpi=150, bbox_inches="tight")

# %% The mesh on the relief, before the solve

# A run stopped at `prepare_solver` stores the ground of every cell, so it draws the mesh.
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

# %% Three values of Sy, one run each

# Sy sets how much water the aquifer stores for a metre of water table. Each run writes the
# figures and the files of project.toml. Sy = 0.05 is the value of the file, so its run is
# the run of project.toml.
SY = {"small": 0.001, "file": 0.05, "large": 0.3}
runs = {}
for label, sy in SY.items():
    # With Sy = 0.001 the water table moves by metres in a month, and MODFLOW 6 needs four
    # time steps per month to converge. That run takes about three minutes.
    steps = 4 if label == "small" else 1
    lab.set({"Sy": sy, "simulation.time.substeps_per_period": steps})
    runs[label] = lab.run(None if label == "file" else f"nancon_sy_{label}")
lab.close()

# %% The months of least and most seepage

# The fields are stored by month. Each month is named by its first day, and the figures take
# the middle of the month. Only the cells of the catchment are counted.
rows = []
for label, run in runs.items():
    months = run.periods.edges[:-1]
    seeps = run.read("seepage_mask").to_numpy()[:, run.catchment_mask.ravel()] > 0
    share = pd.Series(seeps.mean(axis=1) * 100, index=months)
    scores = run.metrics.set_index("metric")["value"]
    rows.append(
        {
            "Sy": SY[label],
            "least (%)": share.min(),
            "in": share.idxmin().strftime("%Y-%m"),
            "most (%)": share.max(),
            "in ": share.idxmax().strftime("%Y-%m"),
            "NSE": scores["nse"],
            "NSE log": scores["nse_log"],
        }
    )
    for word, month in (("least", share.idxmin()), ("most", share.idxmax())):
        middle = (month + pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        print(
            run.figure(
                "seepage_mask",
                time=middle,
                overlays=["outline"],
                save=FIGURES / f"seepage_sy_{label}_{word}.png",
            )
        )
        print(
            run.figure(
                "watertable_elevation",
                type="section",
                time=middle,
                line=SECTION,
                save=FIGURES / f"section_sy_{label}_{word}.png",
            )
        )
# A small Sy lets the water table follow each month, so the network swells in winter and
# nearly dries in summer. A large Sy smooths the year.
print(pd.DataFrame(rows).set_index("Sy").round(2).to_string())

# %% How long each cell seeps, and the discharge

# The share of the 36 months each cell seeps, then the simulated discharge against the gauge
# on a log axis, then the seepage share of the catchment over time beside the discharge.
for label, run in runs.items():
    print(
        run.figure(
            "simulated_active_network",
            reduce="frequency",
            overlays=["outline", "network"],
            save=FIGURES / f"persistence_sy_{label}.png",
        )
    )
    print(run.figure("hydrograph", scale="log", save=FIGURES / f"discharge_sy_{label}.png"))
    print(run.figure("network_expansion", save=FIGURES / f"network_expansion_sy_{label}.png"))

# %% The files for QGIS

for path in runs["file"].exports:
    print(path)
