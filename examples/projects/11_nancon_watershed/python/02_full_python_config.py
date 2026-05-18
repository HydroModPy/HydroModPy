"""Nancon - Python script 02 - Build the configuration entirely in Python.

The configuration is assembled from the public Pydantic classes shipped
on the top level of `hydromodpy`. Every class is typed, exposes
autocomplete in an IDE, and validates eagerly. No JSON-like dict, no
TOML file is involved.

The script reads top to bottom: one Pydantic sub-config per block, with
plenty of room to insert your own logic between blocks (compute a
parameter from a CSV, derive a path from a database, etc.). The final
`HydroModPyConfig(...)` call only re-assembles the named pieces.

Friendly constructors used below:

* `GeographicConfig.from_outlet(...)` - watershed from outlet coords.
* `DomainConfig.with_thickness(...)` - constant-thickness aquifer.
* `FlowConfig.transient(K=..., Sy=..., Ss=...)` - homogeneous params.
* `DemConfig.from_geotiff(...)` / `GeologyConfig.brgm_1m()` etc.

Launch:
    python examples/projects/11_nancon_watershed/python/02_full_python_config.py
"""

from pathlib import Path

import hydromodpy as hmp
from hydromodpy import (
    CauchyBC,
    DataManagersConfig,
    DemConfig,
    DisplayConfig,
    DomainConfig,
    EtpConfig,
    EtpSourceConfig,
    FlowConfig,
    GeographicConfig,
    GeologyConfig,
    HydrographyConfig,
    HydrographySourceConfig,
    HydrometryConfig,
    HydrometrySourceConfig,
    HydroModPyConfig,
    RechargeConfig,
    RechargeSourceConfig,
    RunoffConfig,
    RunoffSourceConfig,
    SimulationConfig,
    SimulationProcessConfig,
    SimulationTimeConfig,
    WorkflowConfig,
    WorkspaceConfig,
)

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
# Shared example data lives one level above the projects/ folder. The
# TOML loader resolves bare filenames against `<workspace>/data/<role>/`
# automatically; when we build the config in Python we pass absolute
# paths to keep the code independent from the current working directory.
DATA_ROOT = PROJECT_DIR.parent.parent / "data"
DEM_PATH = DATA_ROOT / "dem" / "DEM_armorican_massif.tif"


# ---------------------------------------------------------------------
# 1. Workflow + workspace
# ---------------------------------------------------------------------

workflow = WorkflowConfig(mode="simulation")

workspace = WorkspaceConfig(project_root=PROJECT_DIR)


# ---------------------------------------------------------------------
# 2. Geographic - watershed delineation
# ---------------------------------------------------------------------

geographic = GeographicConfig.from_outlet(
    x=389285.91,
    y=6816518.749,
    dem=DEM_PATH,
    snap_dist="150 m",
    buff_area="10%",
    crs_project="EPSG:2154",
)


# ---------------------------------------------------------------------
# 3. Domain - vertical discretization
# ---------------------------------------------------------------------

domain = DomainConfig.with_thickness(30.0, zone_ids=["geology"])


# ---------------------------------------------------------------------
# 4. Data - one Pydantic object per variable family
# ---------------------------------------------------------------------

# Static variables (no time dimension).
dem_data = DemConfig.from_geotiff(DEM_PATH)
geology_data = GeologyConfig.brgm_1m()
hydrography_data = HydrographyConfig(
    sources=[HydrographySourceConfig(source="bdtopage", rasterize_field="FID")],
)


# Observed-discharge timeseries.
hydrometry_data = HydrometryConfig(
    date_start="2000-01-01",
    date_end="2002-12-31",
    sources=[
        HydrometrySourceConfig(
            source="custom",
            path=DATA_ROOT / "hydrometry",
            extent="watershed",
        ),
    ],
)


# Recharge timeseries (used as the diffuse top forcing).
recharge_data = RechargeConfig(
    date_start="2000-01-01",
    date_end="2002-12-31",
    sources=[
        RechargeSourceConfig(
            source="custom",
            path=DATA_ROOT / "recharge",
            station_ids=["EX04"],
        ),
    ],
)


# Runoff timeseries (added to the simulated DRN baseflow when
# comparing against observed streamflow).
runoff_data = RunoffConfig(
    date_start="2000-01-01",
    date_end="2002-12-31",
    sources=[
        RunoffSourceConfig(
            source="custom",
            path=DATA_ROOT / "runoff",
            station_ids=["EX04"],
        ),
    ],
)


# ETP timeseries (SIM2 NetCDF shipped with the repo).
etp_data = EtpConfig(
    date_start="2000-01-01",
    date_end="2002-12-31",
    sources=[
        EtpSourceConfig(
            source="custom",
            path=DATA_ROOT / "etp" / "etp_sim2_5347fa22_20000101_20251231.nc",
        ),
    ],
)


# Assemble the data manager. `types` is the canonical list of families
# the launcher will inflate; the explicit attributes below carry the
# actual Pydantic objects we just built.
data = DataManagersConfig(
    project_crs="EPSG:2154",
    types=["dem", "geology", "hydrography", "hydrometry", "recharge", "runoff", "etp"],
    dem=dem_data,
    geology=geology_data,
    hydrography=hydrography_data,
    hydrometry=hydrometry_data,
    recharge=recharge_data,
    runoff=runoff_data,
    etp=etp_data,
)


# ---------------------------------------------------------------------
# 5. Flow process - parameters + boundary conditions
# ---------------------------------------------------------------------

# `FlowConfig.transient(K=..., Sy=..., Ss=...)` is a shortcut that
# fills `param`, `param_list` and `flow_regime` from the kwargs. The
# BC and the active lists are layered on top via `model_copy`.
drainage_bc = CauchyBC(
    id="drainage",
    kind="cauchy",
    application_domain="top",
    value=0.0,
    description="Cauchy drainage on the aquifer top face.",
)

flow = FlowConfig.transient(K=5e-5, Sy=0.05, Ss=1e-5).model_copy(
    update={
        "active_bc": ["drainage"],
        "active_sinks_sources": ["recharge", "etp"],
        "bc": {"drainage": drainage_bc},
    }
)


# ---------------------------------------------------------------------
# 6. Simulation orchestration
# ---------------------------------------------------------------------

simulation_time = SimulationTimeConfig(
    start_datetime="2000-01-01",
    end_datetime="2002-12-31",
    step_value="1 month",
)

flow_process = SimulationProcessConfig(id="flow_main", type="flow", solvers=["modflow_nwt"])

simulation = SimulationConfig(
    name="nancon_full_python",
    description="Nancon - same case as 01_run_simulation_nwt.toml, built from Python.",
    time=simulation_time,
    process=[flow_process],
)


# ---------------------------------------------------------------------
# 7. Display
# ---------------------------------------------------------------------

display = DisplayConfig(
    output_dir="figures",
    figures=[
        "watershed_id_card",
        "piezometric_map",
        "water_budget",
        "hydrograph",
        "recharge_map",
        "seepage_map",
    ],
)


# ---------------------------------------------------------------------
# 8. Assemble the final config and run
# ---------------------------------------------------------------------

cfg = HydroModPyConfig(
    workflow=workflow,
    workspace=workspace,
    geographic=geographic,
    domain=domain,
    data=data,
    flow=flow,
    simulation=simulation,
    display=display,
)


with hmp.Project(cfg) as project:
    run = project.run()
    if run is not None:
        print(f"sim_id={run.sim_id} name={run.name} status={run.status}")
