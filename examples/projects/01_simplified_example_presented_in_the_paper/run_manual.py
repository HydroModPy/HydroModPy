"""Example 01 driven from Python: residence times from particle tracks.

Same configuration as ``project.toml`` (Canut, steady, MODFLOW 6 with a
depth-decaying aquifer and PRT tracking). This script runs it, then reads
the particle pathlines to summarize the residence-time distribution, the
theme of the paper example. No figure is built here: ``particle_tracks``
and ``cross_section`` are named registry figures rendered via ``hmp.figure``.

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/01_simplified_example_presented_in_the_paper/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import numpy as np

import hydromodpy as hmp
from hydromodpy.display.figures.particle_tracks import (
    particle_time_to_days,
    read_particle_tracks,
)

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"

# %% ---- RUN

run = hmp.run(CONFIG, force=True)
print(f"sim_id     : {run.sim_id}")
print(f"grid       : {run.grid.shape} cells of {run.grid.cell_size:g} m")
print(f"parameters : {run.params}")

# %% ---- READ THE PARTICLE PATHLINES

tracks = read_particle_tracks(run)
to_days = particle_time_to_days(run)
# Travel time = elapsed tracking time along each pathline, converted to years.
travel_years = np.array(
    [abs(t[-1, 3] - t[0, 3]) * to_days / 365.25 for t in tracks if np.isfinite(t[:, 3]).any()]
)
travel_years = travel_years[np.isfinite(travel_years) & (travel_years > 0)]

# %% ---- RESIDENCE-TIME DISTRIBUTION

print(f"\nParticles tracked      : {len(tracks)}")
print(
    f"Travel time (years)    : "
    f"median {np.median(travel_years):.1f}, "
    f"p10 {np.quantile(travel_years, 0.10):.1f}, "
    f"p90 {np.quantile(travel_years, 0.90):.1f}, "
    f"max {travel_years.max():.1f}"
)

# %% ---- RENDER FIGURES

# Figures belong to the run, exactly where `hmp run` puts them:
# <project>/runs/<run>/figures/. The project root stays clean.
with hmp.open(HERE) as catalog:
    OUT = catalog.run_dir_for(run.sim_id) / "figures" / "from_python"

hmp.figure(run, "particle_tracks", save=OUT)
hmp.figure(run, "cross_section", save=OUT, orientation="we")
print(f"\nFigures written under {OUT}")
