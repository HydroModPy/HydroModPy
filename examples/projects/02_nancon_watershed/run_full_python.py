"""Full-Python equivalent of run_transient_nwt.toml.

Builds the Nançon transient MODFLOW-NWT configuration directly in
Python, without parsing a TOML file. Each line is annotated so a new
user can match the script with the config classes.
"""

# Standard library: makes annotations lazy (helps with forward refs).
from __future__ import annotations

# Path is the typed file-path API used everywhere in HydroModPy.
from pathlib import Path

# Public façade. `hmp.Project`, `hmp.Config`, `hmp.Geographic`, etc.
import hydromodpy as hmp

# WorkspaceConfig is the only sub-config that lives in `core.workspace`.
# It carries the project_root used to resolve relative paths.
from hydromodpy.core.workspace.config import WorkspaceConfig

# Folder of this script. Used as the project root.
HERE = Path(__file__).resolve().parent
# Shared example data folder (../../data relative to this project).
DATA = HERE.parent.parent / "data"


def build_config() -> hmp.Config:
    """Return a fully-typed HydroModPyConfig matching run_transient_nwt.toml."""
    return hmp.Config(
        # Mandatory workflow selector. "simulation" runs one MODFLOW pass.
        workflow="simulation",
        # Workspace anchor. Outputs go under HERE / simulations, figures, etc.
        workspace=WorkspaceConfig(project_root=HERE),
        # Geographic block: watershed delineated from the outlet point.
        geographic=hmp.Geographic.from_outlet(
            # Outlet X (Lambert-93).
            x=389285.91,
            # Outlet Y (Lambert-93).
            y=6816518.749,
            # Regional DEM used for flow accumulation.
            dem=DATA / "dem" / "DEM_armorican_massif.tif",
            # Maximum snap distance to align the outlet with a stream cell.
            snap_dist="150 m",
            # Buffer kept around the watershed polygon.
            buff_area="10%",
            # Project CRS. Lambert-93 is the official French metric CRS.
            crs_project="EPSG:2154",
        ),
        # Aquifer model: 30 m of constant-thickness layer below topography.
        domain=hmp.Domain.with_thickness(30.0),
        # Data block: declared families plus their typed sources.
        data=hmp.Data(
            # Families used by this run.
            types=["dem", "geology", "hydrography", "hydrometry", "recharge"],
            # DEM source. Same file as the geographic block.
            dem=hmp.DEM.from_geotiff(DATA / "dem" / "DEM_armorican_massif.tif"),
            # Background lithology (BRGM 1:1M national geological map).
            geology=hmp.Geology.brgm_1m(),
            # Observed discharge time-series (custom CSVs).
            hydrometry=hmp.Hydrometry.from_csv_directory(
                DATA / "hydrometry",
                # Lower bound of the simulation window.
                start="2000-01-01",
                # Upper bound (inclusive).
                end="2002-12-31",
            ),
            # Recharge forcing (custom CSVs).
            recharge=hmp.Recharge.from_csv_directory(
                DATA / "recharge",
                start="2000-01-01",
                end="2002-12-31",
            ),
        ),
        # Flow process: homogeneous K, Sy, Ss; drainage BC; recharge sink.
        flow=hmp.Flow.homogeneous(
            # Hydraulic conductivity (m/s).
            K=5e-5,
            # Specific yield (dimensionless).
            Sy=0.05,
            # Specific storage (1/m).
            Ss=1e-5,
            # Drainage Cauchy boundary on the aquifer top.
            active_bc=["drainage"],
            # Diffuse recharge applied to the top face.
            active_sinks_sources=["recharge"],
        ),
        # Simulation window: monthly stress periods over three years.
        simulation=hmp.Sim.transient(
            time=("2000-01-01", "2002-12-31", "1 month"),
            # Solver name. Must match active_bc support in the chosen engine.
            flow="modflownwt",
            # Run name in the catalog.
            name="nancon_transient_nwt",
        ),
    )


def main() -> None:
    """Build the config, run one simulation, print its sim_id."""
    # Build the typed config object.
    cfg = build_config()
    # Project context-manager closes the catalog automatically on exit.
    with hmp.Project(cfg) as project:
        # `run()` chains prepare + execute + ingest + render + cleanup.
        run = project.run()
        # `run.sim_id` is the catalog UUID, `run.name` echoes the chosen name.
        print(f"sim_id={run.sim_id} name={run.name}")


# Standard "script entry point" guard so importing the module does not
# launch a simulation by accident.
if __name__ == "__main__":
    main()
