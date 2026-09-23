"""Build the PyHELP recharge grid the Urse model is forced with.

PyHELP is a land-surface model: it turns daily precipitation, air temperature
and solar radiation into a daily water balance per grid cell, and the
percolation below the root zone is the recharge a groundwater model needs.
It is a preprocessing step, not a HydroModPy process, so it has no TOML
surface: this script is the declaration.

It writes ``examples/data/recharge/recharge_pyhelp_urse.nc``, the file
``project.toml`` then reads as its recharge source. The NetCDF is shipped with
the examples, so ``hmp run project.toml`` works without running this first;
run it to change a soil or vegetation parameter and see the recharge move.

    python examples/projects/10_coupling_with_land_surface_model_pyhelp/build_pyhelp_recharge.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

from hydromodpy.physics.hydrology.pyhelp.preprocessing.pipeline import preprocessing_pyhelp

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data"
WORKDIR = HERE / ".pyhelp"
OUT_NC = DATA / "recharge" / "recharge_pyhelp_urse.nc"


# %% ---- EXTENDING THE GRID OVER THE MODEL BUFFER
#
# PyHELP runs one column per grid cell inside the catchment polygon and leaves
# the rest empty. The groundwater domain is the catchment plus a 20% buffer
# ring, so those empty cells fall inside it, and a forcing with holes is
# refused on discretization. The ring gets the value of the nearest modelled
# cell: not a measurement, the least-wrong extension of one.


def fill_outside_catchment(path: Path) -> None:
    """Fill the cells PyHELP did not model with their nearest modelled value."""
    import numpy as np
    import xarray as xr
    from scipy.ndimage import distance_transform_edt

    with xr.open_dataset(path) as opened:
        data = opened.load()

    for name in ("recharge", "runoff", "evapo"):
        values = data[name].values
        missing = ~np.isfinite(values[0])
        if not missing.any():
            continue
        nearest = distance_transform_edt(missing, return_distances=False, return_indices=True)
        rows, cols = np.asarray(nearest)
        data[name].values = values[:, rows, cols]

    filled = path.with_suffix(".filled.nc")
    data.to_netcdf(filled)
    filled.replace(path)
    print(f"unmodelled cells filled by nearest neighbour in {path}")


# %% ---- WHAT THE LAND SURFACE MODEL PRODUCED
#
# An input diagnostic, not a run output: no registry figure describes a forcing
# the solver has not seen yet. Two panels, the ones the legacy example drew -
# the annual total, and the monthly totals year by year on a log axis, where a
# winter of 100 mm and a summer of 1 mm both stay readable.


def plot_recharge(path: Path, png_path: Path) -> None:
    """Draw the yearly and monthly totals of the PyHELP recharge."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import xarray as xr

    with xr.open_dataset(path) as data:
        daily = data["recharge"].mean(dim=("y", "x")).to_series()

    yearly = daily.resample("YE").sum()
    monthly = daily.resample("ME").sum()

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), dpi=150)
    top.bar([str(stamp.year) for stamp in yearly.index], yearly.to_numpy(), color="#1f6fb4")
    top.set_ylabel("Recharge (mm/year)")
    top.set_title("PyHELP recharge over the Urse catchment")
    top.grid(True, axis="y", ls=":", lw=0.4)

    bottom.plot(monthly.index, monthly.to_numpy(), lw=1.6, color="#1f6fb4", marker="o", ms=3)
    bottom.set_yscale("log")
    bottom.set_ylabel("Recharge (mm/month)")
    bottom.set_xlabel("Month")
    bottom.grid(True, which="both", ls=":", lw=0.4)

    fig.tight_layout()
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)
    print(f"recharge plot written to {png_path}")


# %% ---- RUN PYHELP
#
# The soil and vegetation numbers describe one uniform Alpine grassland over a
# 1 m soil: a saturated conductivity of 4.28e-8 m/s, 45% porosity, a field
# capacity of 0.23 and a wilting point of 0.116, growing between julian days
# 140 and 280. The grid geometry comes from the 250 m DEM, coarse on purpose:
# PyHELP is a one-dimensional column model and running one column per 25 m
# cell buys nothing.

if __name__ == "__main__":
    import shutil

    WORKDIR.mkdir(parents=True, exist_ok=True)
    OUT_NC.parent.mkdir(parents=True, exist_ok=True)

    # The grid builder writes its resampled DEM next to the one it is given, so
    # the source is copied into the working directory first: the shared data
    # folder holds inputs, not by-products.
    dem = WORKDIR / "DEM_urse_250m.tif"
    shutil.copyfile(DATA / "dem" / "DEM_urse_250m.tif", dem)

    written = preprocessing_pyhelp(
        workdir=str(WORKDIR),
        pyhelp_out_nc=str(OUT_NC),
        grid_base=DATA / "pyhelp" / "urse_grid_base.csv",
        dem=str(dem),
        shapefile=str(DATA / "watershed_polygon" / "urse_watershed.gpkg"),
        ready_climatic_csvs=[
            str(DATA / "pyhelp" / "urse_precipitation.csv"),
            str(DATA / "pyhelp" / "urse_air_temperature.csv"),
            str(DATA / "pyhelp" / "urse_solar_radiation.csv"),
        ],
        growth_start=140,
        growth_end=280,
        wind=2.5,
        hum1=60,
        hum2=65,
        hum3=70,
        hum4=70,
        LAI=2.4,
        EZD=44.5,
        CN=55,
        nlayer=1,
        lay_type1=1,
        thick1=100,
        poro1=0.45,
        fc1=0.23,
        wp1=0.116,
        ksat1=round(4.28e-8 * 3600 * 24, 5),
        dist_dr1=50,
        slope1=35,
    )
    print(f"PyHELP recharge grid written to {written}")
    fill_outside_catchment(Path(written))
    plot_recharge(Path(written), WORKDIR / "pyhelp_recharge.png")
