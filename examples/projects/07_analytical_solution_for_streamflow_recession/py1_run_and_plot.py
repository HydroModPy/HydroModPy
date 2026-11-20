"""Play project.toml in the lab, one step at a time, and look at what each step built. Then
solve, keep the model as a run, and draw from the run the water table after the pulse of
recharge and at the end of the recession. The discharge of the falling limb is then read from
the run and set against the late-time solution of the non-linear Boussinesq equation, in a
log-log plot of numbers the script computes.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import NullFormatter

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
# The one row of cells, from the stream at x = 0 to the closed edge at x = 1000 m.
LINE = [[0.0, 10.0], [1000.0, 10.0]]
SECONDS_PER_DAY = 86400.0

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The domain

# The domain is built, not read: 1000 m by 20 m, one row of 50 cells of 20 m, flat at 100 m.
# This example reads no data file, so `load_data` has nothing to load. `advance` plays every
# missing step up to the one named.
state = lab.advance("build_mesh")
print(state.mesh)

# %% The model the solver reads

# `prepare_solver` freezes the model. `solve(build_only=True)` writes the MODFLOW 6 model
# without solving it, so its packages hold what the solver will read.
state = lab.advance("prepare_solver")
print(state.model)
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
k_day = float(mf6.npf.k.array.mean()) * SECONDS_PER_DAY
sy = float(mf6.sto.sy.array.mean())
print(f"K = {k_day:.3f} m/day, Sy = {sy}, aquifer {float(mf6.dis.top.array.mean()):.0f} m thick")

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period, one column per
# cell, from the stream at the west to the closed edge at the east. Nothing is written to
# runs/ yet. The first period is steady under the mean recharge, then each period is a day.
head = lab.read("head").to_numpy()
for day in (0, 30, 90, 500, len(head) - 1):
    print(f"day {day:3d}: water table {head[day, 0]:6.2f} m at the stream cell, {head[day].max():6.2f} m at the top")

# %% Keep the run

# The run takes the solve of the lab, then draws the figures and writes the files that
# project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)
for path in run.exports:
    print(path)

# %% The water table along the hillslope

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run, so
# nothing is solved again. Day 30 ends the pulse, day 90 is where the recession is read,
# and the last day is the end of the record.
for day in (30, 90, 300):
    print(
        run.figure(
            "watertable_elevation",
            type="section",
            time=day,
            line=LINE,
            save=FIGURES / f"section_day_{day}.png",
        )
    )

# %% The discharge of the stream

# The stream is a fixed head on the west edge, so its flow is the budget term `constant_head`,
# in m3/s for the 20 m strip of the row. The series has one value per day.
fixed_head = run.budget(component="constant_head").sort_values("timestep")
recharge = run.budget(component="recharge").sort_values("timestep")
width = float(run.mesh.cell_areas()[0]) ** 0.5
days = np.arange(len(fixed_head))

# The Boussinesq solution is written for a stream of unit length drained from both banks, so
# the discharge is the flow of this strip counted twice, per metre of stream (m3/day/m).
q = 2.0 * fixed_head["flux_out"].to_numpy() * SECONDS_PER_DAY / width
rain = 2.0 * recharge["flux_in"].to_numpy() * SECONDS_PER_DAY / width

# %% The falling limb against the late-time solution

# After the pulse the discharge falls as -dQ/dt = a Q^b. The late-time solution of
# Boussinesq (1904) gives b = 3/2 and
#     a = 4.804 K^(1/2) L / (f A^(3/2))
# for an aquifer of area A drained through a stream of length L, with K in m/day and the
# drainable porosity f equal to Sy. Here L = 1 m and A = 2 x 1000 m2, the two banks.
# The first 90 days are left out, so the pulse has finished acting on the discharge.
L, area = 1.0, 2.0 * 1000.0
a = 4.804 * k_day**0.5 * L / (sy * area**1.5)
start = 90
flow = 0.5 * (q[start:-1] + q[start + 1 :])
rate = -np.diff(q[start:])
falling = rate > 0
flow, rate = flow[falling], rate[falling]
line = a * flow**1.5
residual = np.log10(rate) - np.log10(line)
slope, intercept = np.polyfit(np.log10(flow), np.log10(rate), 1)
print(f"a = {a:.3e} for the solution, {len(flow)} falling days")
print(f"fitted exponent b = {slope:.3f} (solution: 1.5)")
print(
    f"log10 of the simulated rate minus the solution: mean {residual.mean():+.4f}, "
    f"largest {np.abs(residual).max():.4f}, that is {(10 ** residual.mean() - 1) * 100:+.1f} % on a"
)

# %% The recharge and the discharge

fig, ax = plt.subplots(figsize=(7, 4))
ax.plot(days, rain, color="royalblue", lw=2, label="Recharge")
ax.plot(days, q, color="crimson", lw=2, label="Discharge")
ax.set_xlabel("Time (days)")
ax.set_ylabel("Flow per metre of stream (m$^3$/day/m)")
ax.set_title("A pulse of 30 days, then a recession")
ax.legend()
ax.grid(alpha=0.3)
fig.savefig(FIGURES / "recharge_and_discharge.png", dpi=150, bbox_inches="tight")

# %% The recession plane

fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
ax = axes[0]
ax.loglog(flow, rate, color="crimson", lw=2, label="Simulated")
ax.loglog(flow, line, color="black", lw=3, zorder=-1, label="Boussinesq (1904), late time")
ax.set_xlabel("Q (m$^3$/day/m)")
ax.set_ylabel("-dQ/dt (m$^3$/day$^2$/m)")
ax.legend(loc="upper left")
ax.grid(alpha=0.3, which="both")
ax = axes[1]
ax.semilogx(flow, residual, color="darkorange")
for ax_ in axes:
    ax_.xaxis.set_minor_formatter(NullFormatter())
ax.axhline(0.0, color="black", lw=2, zorder=-1)
ax.set_xlabel("Q (m$^3$/day/m)")
ax.set_ylabel("log10 simulated - log10 solution")
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(FIGURES / "recession_against_boussinesq.png", dpi=150, bbox_inches="tight")
