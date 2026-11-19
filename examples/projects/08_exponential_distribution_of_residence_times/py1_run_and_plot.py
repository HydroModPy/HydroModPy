"""Play project.toml in the lab, one step at a time, and look at what each step built: the
domain, the mesh, the six layers MODFLOW 6 will read, and the water table against the Dupuit
parabola. Then keep the model as a run, read its water budget, and set the travel times of the
particles against the exponential law of a single well-mixed store, computed here from the
numbers of the run.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# The numbers of project.toml that the checks below need.
LENGTH = 1000.0  # m, from the stream to the divide
GROUND = 10.0  # m
STREAM = 5.0  # m, the fixed head on the west edge
K = 15.0 / 86400.0  # m/s, which is 15 m/day
RECHARGE = 1.0e-3 / 86400.0  # m/s, which is 1 mm/day
POROSITY = 0.1

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The domain

# No data file and no catchment: the domain is built from the grid of `[geographic.synthetic]`,
# 1000 m by 20 m, and every cell of it belongs to the model.
state = lab.advance("build_geographic")
print(state.geographic)

# %% The mesh

# One cell per pixel of the grid: 100 columns of 10 m and two rows. The ground is flat at
# 10 m, so there is no relief to draw, and the mesh says its cells, its area and its extent.
state = lab.advance("build_mesh")
print(state.mesh)

# %% The six layers

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its packages hold what
# the solver will read. MODFLOW 6 refuses a fixed head under the bottom of its cell, and the
# stream stands at 5 m, so the top layer takes the upper half of the aquifer and five layers of
# 1 m share the half below.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
bases = mf6.dis.botm.array.mean(axis=1).round(6)
tops = np.concatenate([[GROUND], bases[:-1]])
layers = pd.DataFrame(
    {
        "top (m)": tops,
        "base (m)": bases,
        "thickness (m)": tops - bases,
        "K (m/s)": mf6.npf.k.array.mean(axis=1),
    },
    index=pd.RangeIndex(1, len(bases) + 1, name="layer"),
)
print(layers.to_string(float_format="{:.3g}".format))

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period, one column per
# cell. Nothing is written to runs/ yet. The two rows of the grid carry the same flow, so the
# water table is the mean of the two cells of each column.
head = lab.read("head").to_numpy().ravel().reshape(2, 100).mean(axis=0)
x = np.arange(5.0, LENGTH, 10.0)
print(f"water table from {head.min():.2f} m at the stream to {head.max():.2f} m at the divide")

# For a flat aquifer under a uniform recharge R with a fixed head h0 at x = 0 and a closed
# end at x = L, the Dupuit equation gives h(x)^2 = h0^2 + R x (2 L - x) / K, and the flow at
# the stream is R L per metre of width.
parabola = np.sqrt(STREAM**2 + RECHARGE * x * (2.0 * LENGTH - x) / K)
print(
    f"Dupuit parabola: {parabola.max():.2f} m at the divide, "
    f"largest gap with the model {np.abs(parabola - head).max():.2f} m"
)

# %% Keep the run

# The run takes the solve of the lab, tracks the particles, then draws the figures and writes
# the files that project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% The water budget

# The budget of the run is a table with one row per component. The flow that enters with the
# recharge leaves through the stream, the fixed head on the west edge. The recharge falls on 99
# columns of two cells, the column of the stream takes none, so Dupuit's R L is 1 % too large.
budget = pd.read_csv(next(path for path in run.exports if path.name == "budget.csv"))
budget = budget.set_index("component")[["flux_in", "flux_out"]] * 86400.0
print((budget[(budget != 0).any(axis=1)]).to_string(float_format="{:.2f}".format), "(m3/day)")

# %% The travel times

# The [[export]] blocks of project.toml wrote these files when the run was sealed. The tracks
# are one line per particle, with its travel time in years from its cell to the stream.
for path in run.exports:
    print(path)
tracks = gpd.read_file(next(path for path in run.exports if path.name == "pathlines.gpkg"))
years = np.sort(tracks["travel_yr"].to_numpy())
print(
    f"{len(years)} particles, mean travel time {years.mean():.2f} years, "
    f"median {np.median(years):.2f} years, slowest {years.max():.1f} years"
)

# %% The exponential law of a well-mixed store

# A store of volume V that gets a flow Q and lets the same flow leave, with the water mixed at
# once, empties as exp(-t / tau) with tau = V / Q. The travel times of its water have the
# density exp(-t / tau) / tau. For the aquifer, V is the porosity times the saturated volume
# and Q is the recharge over the whole length, so tau = n * mean saturated thickness / R.
tau_store = POROSITY * head.mean() / (RECHARGE * 365.25 * 86400.0)
tau_mean = years.mean()
print(f"tau of the store, n h / R: {tau_store:.2f} years")
print(f"mean travel time of the particles: {tau_mean:.2f} years")
print(
    f"median over mean: {np.median(years) / tau_mean:.3f} for the particles, "
    f"{np.log(2.0):.3f} for an exponential law"
)

# The density of the travel times in bins that are even on a log axis, in units of
# t / tau, next to exp(-t / tau).
scaled = years / tau_mean
edges = np.logspace(np.log10(np.quantile(scaled, 0.01)), np.log10(np.quantile(scaled, 0.99)), 15)
density, _ = np.histogram(scaled, bins=edges, density=True)
middle = np.sqrt(edges[1:] * edges[:-1])
t = np.logspace(-3, 1, 200)

fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4))
left.loglog(t, np.exp(-t), color="grey", lw=2, label="exponential law")
left.loglog(middle[density > 0], density[density > 0], "o", color="crimson", label="particles")
left.set_xlabel(r"$t / \tau$")
left.set_ylabel("Density")
left.set_xlim(1e-2, 1e1)
left.set_ylim(1e-2, 2e0)
left.set_title("Density of the travel times")
left.legend(loc="lower left")
left.grid(alpha=0.3, which="both")

# The share of the particles still in the aquifer after a time t, which is the cumulative
# form of the same comparison.
share = 1.0 - np.arange(len(years)) / len(years)
right.semilogy(years, share, color="navy", lw=2, drawstyle="steps-post", label="particles")
right.semilogy(
    years,
    np.exp(-years / tau_mean),
    color="grey",
    lw=2,
    label=f"exponential, tau {tau_mean:.2f} yr",
)
right.set_xlabel("Travel time (years)")
right.set_ylabel("Share of particles still in the aquifer")
right.set_title("Share still in the aquifer")
right.legend(loc="lower left")
right.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(FIGURES / "residence_times_exponential.png", dpi=150, bbox_inches="tight")
