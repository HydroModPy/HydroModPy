"""Nançon - specific yield (Sy) sensitivity prototype.

Drives HydroModPy from Python: open the project once, run three
simulations with different Sy values, then read each run from the
catalog (DuckDB + Zarr) to build comparison figures. Use this script
as a template for your own sensitivity / sweep workflows.
"""

# --- Imports ---------------------------------------------------------

# Path API. Lets us anchor everything relative to this script.
from pathlib import Path

# Matplotlib date helpers (year ticks, year-only formatter).
import matplotlib.dates as mdates

# Plot driver.
import matplotlib.pyplot as plt

# Numeric helpers used by the analytics below.
import numpy as np

# Pandas time-series for monthly aggregations.
import pandas as pd

# One-colour colormap used for the saturation overlay.
from matplotlib.colors import ListedColormap

# Public façade.
import hydromodpy as hmp

# ---------------------------------------------------------------------
# Configuration - edit these to fit your project
# ---------------------------------------------------------------------

# Folder of this script.
HERE = Path(__file__).resolve().parent
# Base TOML used for every run. Each call to `project.run(**overrides)`
# only patches the values we want to vary.
PROJECT_TOML = HERE / "project.toml"
# Folder where comparison figures are written.
FIG_DIR = HERE / "figures"

# Parameter swept across runs. Must match a known flow parameter id.
SWEEP_PARAM = "Sy"
# Three contrasted values. 0.001 is dry, 0.05 is the baseline, 0.30 is wet.
SWEEP_VALUES = [0.001, 0.05, 0.30]

# Other flow parameters held constant. They override the values from
# project.toml during the run.
FIXED_PARAMS = {"K": 5e-5, "Ss": 1e-5}

# Variable label used to read the observed discharge from the catalog.
# The "_obs" suffix distinguishes observed series from simulated ones.
OBS_VARIABLE = "discharge_obs"


# ---------------------------------------------------------------------
# 1. Run the sweep
# ---------------------------------------------------------------------

# Open the project once. The geographic / data / mesh phases run on
# instantiation, so the three runs reuse the same prepared context.
project = hmp.Project(PROJECT_TOML)

# Map of {Sy value -> Run handle} populated by the loop below.
runs = {}
for value in SWEEP_VALUES:
    # `project.run` chains prepare + execute + ingest + render + cleanup.
    # The run name embeds the swept value to keep the catalog readable.
    runs[value] = project.run(
        name=f"{SWEEP_PARAM.lower()}_{value:.4f}",
        # Inject the swept parameter as a keyword argument. The name
        # must match an entry of `flow.param_list`.
        **{SWEEP_PARAM: value},
        # Frozen parameters applied at the same time.
        **FIXED_PARAMS,
    )


# ---------------------------------------------------------------------
# 2. Geometric context (shared across runs) from the catalog
# ---------------------------------------------------------------------

# Pick the first run; geometry does not change across the sweep.
first_run = next(iter(runs.values()))

# Aquifer thickness recorded with the run parameters.
thickness = first_run.params["thickness"]

# Grid metadata: cell size in metres, raster shape, georeferenced extent.
grid = first_run.grid
cell_size = grid.cell_size
grid_shape = grid.shape
crs_extent = grid.extent
catchment_area_m2 = grid.catchment_area_m2

# Boolean mask of active catchment cells.
catchment_mask = first_run.catchment_mask
n_active_cells = int(catchment_mask.sum())

# DEM raster as a NumPy array (project CRS, project resolution).
dem = first_run.dem
# Watershed contour as a GeoDataFrame for vector overlays.
contour_gdf = first_run.geographic("watershed_contour")

# Stress-period datetimes recorded for the run.
dates = first_run.time_index
n_periods = len(dates)
sim_start, sim_end = dates[0], dates[-1]

# Make sure the figure folder exists before any savefig call.
FIG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# 3. Catchment-level series: lazy views from the catalog
# ---------------------------------------------------------------------

# % of catchment cells with positive seepage at each stress period.
saturated_fraction = {v: run.saturated_fraction().values for v, run in runs.items()}
# % of catchment cells with positive routed drain flux at each step.
drainage_density = {v: run.drainage_density().values for v, run in runs.items()}
# Stack of accumulation flux rasters (one per stress period).
accumulation_flux = {v: run.fields("accumulation_flux") for v, run in runs.items()}


# ---------------------------------------------------------------------
# 4. Cross-sections (driest vs wettest months)
# ---------------------------------------------------------------------

# One row per swept value. `dpi=200` gives publication-ready figures.
fig, axes = plt.subplots(len(runs), 1, figsize=(7, 3.5 * len(runs)), dpi=200)
# Force a 1-D array even when `len(runs) == 1`.
axes = np.atleast_1d(axes)

# Use the middle row of the grid as the cross-section line.
mid_row = grid_shape[0] // 2
# Distance along the cross-section in metres.
distance = np.arange(grid_shape[1]) * cell_size
# DEM elevation profile along the same line.
dem_profile = dem[mid_row, :]

# Iterate (axis, swept-value) pairs in lockstep.
for ax, (value, run) in zip(axes, runs.items(), strict=False):
    # Catchment-level seepage time-series for this run.
    density = saturated_fraction[value]
    # Indices of the driest and wettest stress periods.
    t_min, t_max = int(density.argmin()), int(density.argmax())

    # Plot two extreme states on the same cross-section.
    for label, tidx, color in [("Min", t_min, "navy"), ("Max", t_max, "dodgerblue")]:
        # Reshape the flat watertable elevation array into the grid.
        wt = run.field("watertable_elevation", tidx).reshape(grid_shape).copy()
        # Treat negative elevations as inactive.
        wt[wt < 0] = np.nan
        # Light-blue band between the substratum and the watertable.
        ax.fill_between(
            distance, dem_profile - thickness, wt[mid_row, :], color=color, alpha=0.4, lw=0
        )
        # Watertable line. Label embeds the date for context.
        ax.plot(distance, wt[mid_row, :], color=color, lw=1, label=f"{label} ({dates[tidx]:%Y-%m})")

    # Brown band between the watertable (last `wt`) and the topography.
    ax.fill_between(distance, wt[mid_row, :], dem_profile, color="saddlebrown", alpha=0.3, lw=0)
    # Topography line.
    ax.plot(distance, dem_profile, color="saddlebrown", lw=1.5)
    # Grey band between the substratum and the bottom of the figure.
    ax.fill_between(distance, 0, dem_profile - thickness, color="lightgrey", alpha=0.5, lw=0)
    # Substratum line.
    ax.plot(distance, dem_profile - thickness, color="dimgray", lw=1)

    # Crop the X axis to the valid DEM extent.
    valid = np.isfinite(dem_profile)
    ax.set_xlim(distance[valid].min(), distance[valid].max())
    # Y axis covers the substratum-to-topography range with a small margin.
    ax.set_ylim(np.nanmin(dem_profile) - thickness - 5, np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    # Title = swept value.
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.legend(fontsize=8)

# Tight layout removes the extra padding between subplots.
fig.tight_layout()
# Save and close to free the figure handle.
fig.savefig(FIG_DIR / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 5. Simulated vs observed discharge
# ---------------------------------------------------------------------

# Initialise the observed series; stays None when no station is loaded.
Q_obs = None
# Hydrometry data loaded from project.toml.
hydrometry = project.data.hydrometry
# Plot the observed series only if at least one station was loaded.
if hydrometry is not None and hydrometry.points:
    # Use the first station id available.
    station_id = hydrometry.points[0].station_id
    # Read raw observed discharge from the catalog.
    q_raw = first_run.timeseries(OBS_VARIABLE, station=station_id)
    # Restrict to the simulation window.
    q_raw = q_raw.loc[sim_start:sim_end]
    # Convert L/s to mm/month (the unit used for simulated runoff below).
    Q_obs = (q_raw / catchment_area_m2 * 86400).resample("ME").sum() * 1000

# Number of days per stress period (for daily-to-monthly conversion).
days_in_month = np.array([d.days_in_month for d in dates])
# Map of {Sy -> simulated monthly runoff series}.
Q_sim = {}
for value, run in runs.items():
    # Stack of drain flux rasters over time.
    drain = run.fields("outflow_drain")
    # Replace NaNs with 0 so the sum is well defined.
    drain[~np.isfinite(drain)] = 0.0
    # Convert daily-mean flux to monthly depth equivalent (mm/month).
    q_daily = np.abs(drain * catchment_mask).sum(axis=(1, 2)) / catchment_area_m2 * 86400 * 1000
    Q_sim[value] = pd.Series(q_daily * days_in_month, index=dates)

# Common Y range across all panels (log-friendly).
pos = np.concatenate(
    [q.values for q in Q_sim.values()] + ([Q_obs.values] if Q_obs is not None else [])
)
pos = pos[pos > 0]
y_min, y_max = float(pos.min()) * 0.5, float(pos.max()) * 2.0

# One row per swept value, two columns: time-series + scatter.
fig, axes = plt.subplots(
    len(runs), 2, figsize=(12, 3.5 * len(runs)), gridspec_kw={"width_ratios": [3, 1]}, dpi=200
)
# Force a 2-D layout for `len(runs) == 1`.
axes = axes.reshape(len(runs), 2)

for (ax_ts, ax_sc), (value, q_sim) in zip(axes, Q_sim.items(), strict=False):
    # Time-series panel.
    if Q_obs is not None:
        ax_ts.plot(Q_obs, color="k", lw=2, label="Observed")
    ax_ts.plot(q_sim, color="red", lw=2, label="Simulated")
    ax_ts.set_ylabel("Q/A [mm/month]")
    ax_ts.set_yscale("log")
    ax_ts.set_ylim(y_min, y_max)
    # Year-only X ticks.
    ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_ts.legend(fontsize=8)
    ax_ts.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)

    # Observed-vs-simulated scatter (with a 1:1 line).
    if Q_obs is not None:
        # Align simulated values to observed timestamps.
        q_aligned = q_sim.reindex(Q_obs.index, method="nearest")
        ax_sc.scatter(Q_obs, q_aligned, s=20, alpha=0.7, color="forestgreen", edgecolor="none")
        # 1:1 reference line.
        ax_sc.plot([max(1, y_min), y_max], [max(1, y_min), y_max], color="grey", zorder=-1)
        ax_sc.set_xscale("log")
        ax_sc.set_yscale("log")
        ax_sc.set_xlim(max(1, y_min), y_max)
        ax_sc.set_ylim(max(1, y_min), y_max)
        ax_sc.set_xlabel("Obs [mm/month]")
        ax_sc.set_ylabel("Sim [mm/month]")

fig.tight_layout()
fig.savefig(FIG_DIR / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 6. Intermittent vs perennial drainage density
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(8, 3 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

for ax, (value, intermittent) in zip(axes, drainage_density.items(), strict=False):
    # Cells active at a given stress period.
    active = (accumulation_flux[value] > 0) & catchment_mask
    # Perennial drainage density per stress period.
    perennial = np.zeros(n_periods)
    # Group stress periods by year and look for cells active every step.
    for year in sorted({d.year for d in dates}):
        # Indices of stress periods that fall in this year.
        yr = [t for t, d in enumerate(dates) if d.year == year]
        # Cells that stay active every step of the year.
        always = active[yr].all(axis=0)
        # Convert to a percentage of active catchment cells.
        perennial[yr] = 100.0 * (always & catchment_mask).sum() / n_active_cells

    # Intermittent network: positive flux at any step.
    ax.fill_between(
        dates, 0, intermittent, step="pre", color="dodgerblue", alpha=0.5, label="Intermittent"
    )
    # Perennial network: positive flux every step of the year.
    ax.fill_between(dates, 0, perennial, step="pre", color="navy", alpha=0.5, label="Perennial")
    ax.set_ylabel("Drainage density [%]")
    ax.set_xlim(sim_start, sim_end)
    ax.set_ylim(0, None)
    # Year ticks plus monthly minor ticks.
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(FIG_DIR / "drainage_density_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 7. Saturation maps (driest / wettest steps) with vector contour
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 2, figsize=(8, 4 * len(runs)), dpi=200)
axes = axes.reshape(len(runs), 2)

for row_axes, (value, run) in zip(axes, runs.items(), strict=False):
    density = saturated_fraction[value]
    t_min, t_max = int(density.argmin()), int(density.argmax())

    # Two columns: driest first, wettest second.
    for ax, (tidx, label) in zip(row_axes, [(t_min, "Min"), (t_max, "Max")], strict=False):
        # Accumulation-flux raster at the chosen step.
        flux = accumulation_flux[value][tidx]
        # Title carries the swept value, the date and the saturation pct.
        ax.set_title(
            f"{SWEEP_PARAM}={value}  {label} ({dates[tidx]:%Y-%m})  Asat={density[tidx]:.1f}%",
            fontsize=9,
        )
        # Grey DEM background, masked outside the catchment.
        ax.imshow(
            np.ma.masked_where(~catchment_mask, dem),
            cmap="Greys",
            alpha=0.5,
            extent=crs_extent,
            origin="upper",
        )
        # Navy overlay where flow accumulates inside the catchment.
        ax.imshow(
            np.ma.masked_where((flux <= 0) | ~catchment_mask, flux),
            cmap=ListedColormap(["navy"]),
            extent=crs_extent,
            origin="upper",
        )
        # Watershed contour drawn on top of the rasters.
        contour_gdf.plot(ax=ax, color="black", lw=0.6)
        ax.set_xticks([])
        ax.set_yticks([])
        # Equal aspect to keep cells square.
        ax.set_aspect("equal")

fig.tight_layout()
fig.savefig(FIG_DIR / "saturation_maps_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 8. Persistence index (per-cell fraction of active stress periods)
# ---------------------------------------------------------------------

fig, axes = plt.subplots(1, len(runs), figsize=(4 * len(runs), 5), dpi=200)
axes = np.atleast_1d(axes)

for ax, (value, accflux_stack) in zip(axes, accumulation_flux.items(), strict=False):
    # Fraction of stress periods with positive accumulation per cell.
    persistency = (accflux_stack > 0).sum(axis=0) / n_periods
    # Mask cells outside the catchment or with zero persistence.
    pi = np.ma.masked_where(~catchment_mask | (persistency <= 0), persistency)
    # Jet colormap so wet cells stand out clearly.
    im = ax.imshow(pi, cmap="jet", vmin=0, vmax=1, extent=crs_extent, origin="upper")
    contour_gdf.plot(ax=ax, color="black", lw=0.6)
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")

# Single colorbar shared across the row.
cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
fig.colorbar(im, cax=cbar_ax, orientation="horizontal", label="Persistence index [-]")
fig.tight_layout(rect=[0, 0.08, 1, 1])
fig.savefig(FIG_DIR / "persistency_comparison.png", bbox_inches="tight")
plt.close(fig)


# Always close the project to release the catalog handle.
project.close()
