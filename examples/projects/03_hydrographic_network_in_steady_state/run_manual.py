"""Example 03 driven from Python: a hydraulic-conductivity sweep.

Same configuration as ``project.toml`` (Canut, steady, MODFLOW 6, a 50 m
aquifer in five layers), plus the sweep that is the point of this example.
K sets how deep the water table sits, and with it how much of the stream
network the aquifer keeps flowing: a tight bedrock holds the water table at
the surface and drains almost everywhere, a transmissive one lowers it and
leaves only the main valleys active.

Each K is one simulation obtained with a single parameter override. The
gallery figures declared in ``project.toml`` describe one run at a time, so
the three figures built here are the ones only a script can give, each
putting the whole sweep in a single frame:

- ``sweep_active_network.png``    one map per K, observed network on top
- ``sweep_water_table.png``       one water-table profile per K, one section
- ``sweep_drainage_density.png``  drainage density and baseflow against K

Read it as the Python counterpart of the TOML: every step below has a
``hmp`` command equivalent, and no result is reached through a private
attribute or a hand-built path.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/03_hydrographic_network_in_steady_state/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import hydromodpy as hmp
from hydromodpy.core.state.paths import share_dir_for
from hydromodpy.results.derive import views

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"

# Sweep outputs describe the whole set of runs, not one of them, so they go
# to <project>/share/, the directory the layout reserves for on-demand
# outputs. Per-run figures stay in their own run directory.
OUT = share_dir_for(HERE) / "hydraulic_conductivity_sweep"

# Hydraulic conductivities to explore, m/s, log-spaced over five decades.
K_VALUES = np.geomspace(1e-8, 1e-3, 10)

# Colour per K, dark for the tight aquifers and light for the transmissive
# ones, shared by the three figures.
COLORS = plt.get_cmap("viridis")(np.linspace(0.0, 0.9, len(K_VALUES)))

# One colour per quantity, the same in every figure.
ACTIVE_COLOR = "#a01111"
SEEPAGE_COLOR = "#f4a259"
REFERENCE_COLOR = "navy"


# %% ---- OPEN THE PROJECT

# Project is setup-once, run-many: catchment delineation, data loading and
# meshing happen on the first simulate() and are reused by every following
# one. Display is off because the sweep renders only the figures it needs.
project = hmp.Project(CONFIG, no_display=True)


# %% ---- ONE SIMULATION PER CONDUCTIVITY

# K is a flow parameter, so it is a keyword of simulate(), expressed in the
# unit declared by [flow.param.K.field] in the TOML (here m/s). Everything
# else comes from the config.
runs = {}
for k in K_VALUES:
    runs[k] = project.simulate(name=f"canut_K_{k:.1e}", K=k)
    print(f"K = {k:.1e} m/s -> {runs[k].name} [{runs[k].sim_id[:8]}]")

sample = runs[K_VALUES[0]]
print(
    f"\ngrid: {sample.grid.shape} cells of {sample.grid.cell_size:g} m, "
    f"{sample.n_layers} layers, catchment {sample.grid.catchment_area_m2 / 1e6:.1f} km2"
)


# %% ---- ONE REGISTRY FIGURE PER RUN

# hmp.figure renders the same named figures as [display].figures, so the
# per-K map costs one line. Passing a directory to save= appends
# "<figure name>.png"; the run directory is the one the catalog owns.
for k, run in runs.items():
    hmp.figure(
        run,
        "simulated_active_network_reference_overlay",
        save=project.store.run_dir_for(run.sim_id) / "figures",
    )
print(f"per-run figures written under {project.store.runs_dir}")


# %% ---- COLLECT THE SWEEP

# drainage_density is the share of catchment cells whose routed drain flux
# is positive, that is the network the aquifer keeps flowing.
# saturated_fraction is the share where the water table reaches the surface.
# Both are catchment views over a persisted field, in percent.
records = []
for k, run in runs.items():
    drain = run.budget(component="drain", zone_id="catchment")
    records.append(
        {
            "K_m_per_s": k,
            "drainage_density_pct": float(views.drainage_density(run).iloc[0]),
            "saturated_fraction_pct": float(views.saturated_fraction(run).iloc[0]),
            "baseflow_m3_per_s": float(drain["flux_out"].sum()),
        }
    )

sweep = pd.DataFrame(records)
OUT.mkdir(parents=True, exist_ok=True)
sweep.to_csv(OUT / "sweep_summary.csv", index=False)
print()
print(sweep.to_string(index=False, float_format=lambda v: f"{v:.4g}"))


# %% ---- FIGURE HELPERS

# The three figures below are specific to this example, so they are built
# here rather than registered. They read the run through the public
# accessors only: run.field for a cell field, run.grid for the georeference,
# run.dem and run.catchment_mask for the background, run.hydrographic_network
# for the observed linework.


def raster(run, variable):
    """Reshape one flat cell field of a steady run to the DEM raster."""
    return run.field(variable, timestep=0).reshape(run.grid.shape)


def draw_mask(ax, mask, extent, color, *, alpha, zorder):
    """Paint the true cells of a boolean mask, leaving the rest transparent.

    The alpha is an array rather than a scalar: a scalar one would also apply
    to the cells left out, and they would stop being transparent.
    """
    ax.imshow(
        np.where(mask, 1.0, np.nan),
        extent=extent,
        origin="upper",
        cmap=ListedColormap([color]),
        alpha=np.where(mask, alpha, 0.0),
        zorder=zorder,
    )


def draw_active_network(ax, run, reference):
    """Map one run: relief, catchment outline, observed and simulated network.

    Painted bottom up, from the widest layer to the narrowest: the routed
    drain flux spreads downstream of every draining cell, the seepage areas
    are where the water table actually reaches the surface, and the observed
    linework on top is what both are compared to.
    """
    extent = run.grid.extent
    ax.imshow(run.dem, extent=extent, origin="upper", cmap="Greys", alpha=0.5, zorder=1)
    active = raster(run, "accumulation_flux") > 0.0
    draw_mask(ax, active, extent, ACTIVE_COLOR, alpha=0.85, zorder=2)
    draw_mask(ax, raster(run, "seepage_mask") > 0.0, extent, SEEPAGE_COLOR, alpha=0.7, zorder=3)
    ax.contour(
        run.catchment_mask.astype(float),
        levels=[0.5],
        extent=extent,
        origin="upper",
        colors="black",
        linewidths=0.7,
        zorder=4,
    )
    reference.plot(ax=ax, color=REFERENCE_COLOR, linewidth=0.9, zorder=5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])


def water_table_profile(run):
    """Topography and water table along the west-east row cutting the box."""
    nrow, ncol = run.grid.shape
    row = nrow // 2
    distance = (np.arange(ncol) + 0.5) * run.grid.cell_size
    return distance, raster(run, "topography")[row], raster(run, "watertable_elevation")[row]


# %% ---- FIGURE 1: THE ACTIVE NETWORK ACROSS THE SWEEP

# The observed network is stored with every run under the "reference" role,
# loaded from [data.hydrography]. It is the same linework for all of them.
reference = sample.hydrographic_network("reference")

fig, axes = plt.subplots(2, 5, figsize=(18, 6.4), dpi=150)
for ax, k in zip(axes.ravel(), K_VALUES, strict=True):
    draw_active_network(ax, runs[k], reference)
    ax.set_title(f"K = {k:.1e} m/s", fontsize=9)
fig.suptitle("The active network under a five-decade conductivity sweep", fontsize=12)
fig.legend(
    handles=[
        Patch(facecolor=ACTIVE_COLOR, label="simulated active network"),
        Patch(facecolor=SEEPAGE_COLOR, label="seepage areas"),
        Line2D([], [], color=REFERENCE_COLOR, label="observed network (BD Topage)"),
        Line2D([], [], color="black", label="catchment outline"),
    ],
    loc="lower center",
    ncol=4,
    fontsize=9,
    frameon=False,
)
fig.tight_layout(rect=(0.0, 0.05, 1.0, 1.0))
fig.savefig(OUT / "sweep_active_network.png", bbox_inches="tight")


# %% ---- FIGURE 2: THE WATER TABLE ACROSS THE SWEEP

# One section, one water-table curve per K. Topography is the same for all,
# so it is drawn once as the upper bound the water table cannot cross.
fig, ax = plt.subplots(1, 1, figsize=(10, 4.5), dpi=150)
distance, topography, _ = water_table_profile(sample)
ax.fill_between(distance, topography.min(), topography, color="0.88", lw=0, zorder=1)
for k, color in zip(K_VALUES, COLORS, strict=True):
    _, _, water_table = water_table_profile(runs[k])
    ax.plot(distance, water_table, color=color, lw=1.2, label=f"K = {k:.1e} m/s", zorder=2)
ax.plot(distance, topography, color="saddlebrown", lw=1.8, label="topography", zorder=3)
ax.set_xlabel("Distance along the west-east section (m)")
ax.set_ylabel("Elevation (m)")
ax.set_title("Water table under a five-decade conductivity sweep")
ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
fig.tight_layout()
fig.savefig(OUT / "sweep_water_table.png", bbox_inches="tight")


# %% ---- FIGURE 3: DRAINAGE DENSITY AGAINST CONDUCTIVITY

# The relation the example exists for: the more transmissive the aquifer,
# the lower the water table, and the smaller the network it sustains. The
# legacy example plotted the seepage curve alone under the drainage-density
# label; the two are separate views here, and both are drawn.
fig, ax = plt.subplots(1, 1, figsize=(6.5, 4.5), dpi=150)
ax.plot(
    sweep["K_m_per_s"],
    sweep["drainage_density_pct"],
    marker="o",
    color=ACTIVE_COLOR,
    label="active drainage density",
)
ax.plot(
    sweep["K_m_per_s"],
    sweep["saturated_fraction_pct"],
    marker="s",
    color=SEEPAGE_COLOR,
    label="seepage areas",
)
ax.set_xscale("log")
ax.set_xlabel("K (m/s)")
ax.set_ylabel("Share of catchment cells (%)")
ax.legend(loc="upper right", fontsize=8)
ax.set_title("Drainage density and seepage against K")
fig.tight_layout()
fig.savefig(OUT / "sweep_drainage_density.png", bbox_inches="tight")

print(f"\nsweep figures written under {OUT}")


# %% ---- CLOSE THE PROJECT

# close() releases the catalog and drops the shared preprocessing tree the
# ten runs were built on. The runs themselves stay in the project catalog,
# so a later session reads them back by name without re-running anything:
#
#     catalog = hmp.open(HERE)
#     sweep_runs = catalog.find(project="03_hydrographic_network_in_steady_state")
#     print(sweep_runs.parameters)
project.close()
