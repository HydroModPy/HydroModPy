# Contributing to HydroModPy

This document explains how to set up HydroModPy for development, how the
configuration system works, and how to contribute code or report issues.

## Table of contents

- [Opening issues](#opening-issues)
- [Installation (developer mode)](#installation-developer-mode)
- [CLI reference](#cli-reference)
  - [Initialize a workspace](#initialize-a-workspace)
  - [Create a project](#create-a-project)
  - [Generate a TOML config](#generate-a-toml-config)
  - [Run a simulation](#run-a-simulation)
  - [Run tests](#run-tests)
- [Workspace organization](#workspace-organization)
  - [Data catalog (catalog.db)](#data-catalog-catalogdb)
  - [Project structure](#project-structure)
  - [Output folders](#output-folders)
- [TOML configuration guide](#toml-configuration-guide)
  - [Config inheritance (base_config)](#config-inheritance-base_config)
  - [Simulation section](#simulation-section)
- [Prototyping with Python](#prototyping-with-python)
- [Data managers](#data-managers)
- [Configuration system (Pydantic + TOML)](#configuration-system-pydantic--toml)
  - [Declaring fields](#declaring-fields)
  - [ParamLevel](#paramlevel)
  - [VisibleWhen](#visiblewhen)
  - [Validators](#validators)
  - [Adding a new config section](#adding-a-new-config-section)
- [Running tests](#running-tests)
- [Pull requests](#pull-requests)

---

## Opening issues

Open issues at: https://github.com/HydroModPy/HydroModPy/issues

Do not hesitate to open an issue. This is the best way to contribute, even
if you do not write code. Issues are useful for:

- **Bugs**: describe what happened, what you expected, and how to reproduce
  it. Include the TOML config (or a minimal version) and the error traceback.
- **Feature requests**: describe what you need and why. If you want a new
  data source (for example a national API), provide the technical
  documentation: API endpoint, response format, variables available, units,
  coordinate system.
- **New variables or formats**: specify the variable name, physical unit,
  temporal resolution, spatial coverage (point or gridded), and the file
  format or API interface.
- **Questions**: if the documentation does not cover your use case, ask.

When requesting a new API integration, the more technical detail you
provide the faster it can be implemented. Include:

- API base URL and authentication method (if any).
- Example request and response (JSON, CSV, ...).
- Variable names and units returned by the API.
- Spatial and temporal resolution.
- Any rate limits or access restrictions.

---

## Installation (developer mode)

Clone the repository, create a conda environment with the right Python
version, and install in **editable mode**:

```bash
git clone git@github.com:HydroModPy/HydroModPy.git
cd HydroModPy
conda create -n hmp python=3.12 -y
conda activate hmp
pip install -e .
```

**Python version:** 3.11, 3.12, or 3.13. Pick one when creating the
environment (here 3.12). HydroModPy does not support 3.10 or older.

The `-e` flag (editable) creates a link between the installed package and
your local source tree. When you edit a `.py` file the change takes effect
immediately -- no need to reinstall after each modification. This is the
standard workflow for Python packages under active development.

After installation two CLI commands become available: `hmp` and `hydromodpy`.
They are identical, pick whichever you prefer.

If `hmp` is not found after install, run `hash -r` (zsh/bash) to refresh
the command lookup cache, or reinstall with `pip install -e . --no-deps`.

---

## CLI reference

### Initialize a workspace

```bash
hmp init                         # creates ~/hydromodpy/
hmp init --path /mnt/shared      # creates at a custom location
```

This creates the standard workspace directory structure:

```
hydromodpy/
  data/
    hydrometry/                  # one folder per variable
      hydrometry_custom_LOC.csv  # example location file
      hydrometry_custom_EXAMPLE_20200101_20201231_D.csv
    piezometry/
    precipitation/
    recharge/
    ...                          # 13 variable folders total
  projects/                      # your projects go here
```

The LOC file and the example chronicle CSV show the expected format.
A `catalog.db` (SQLite data registry) is created automatically on first
data load.

### Create a project

```bash
hmp new my_catchment                         # in default workspace
hmp new my_catchment --workspace /mnt/shared # in a custom workspace
```

This creates `projects/my_catchment/` with two template files:

- `project.toml` -- shared settings (geographic, domain, data, flow).
- `run_demo.toml` -- run configuration that inherits from `project.toml`.

### Generate a TOML config

```bash
# Full config (expert profile, all modules)
hmp config my_config.toml

# Minimal config (user profile)
hmp config my_config.toml --profile user

# Only specific modules
hmp config my_config.toml --modules geographic flow modflownwt

# List available modules
hmp config --list-modules
```

The generated TOML includes all field descriptions as comments, default
values, type annotations, and constraints. It looks like this:

```toml
# Geographic runtime mode.
# 'standard' keeps the historical DEM/outlet/polygon workflow.
# 'synthetic' builds one analytical support from [geographic.synthetic].
# Type: Literal['standard', 'synthetic'] | one of: "standard", "synthetic" | Default: "standard"
source_mode = "standard"
```

Start from a generated TOML and edit the values. The descriptions tell you
what each parameter does, what type it expects, and what the default is.

### Run a simulation

```bash
hmp run config.toml
```

This reads the TOML (which must contain a `[simulation]` section listing
the processes to run) and executes the full pipeline: geographic
preprocessing, domain construction, data loading, flow/transport solving,
post-processing. The older alias `hmp simulation config.toml` also works.

### Run tests

```bash
hmp test unit                    # unit tests
hmp test regression --fast       # fast regression tier
hmp test regression --extensive  # extended regression tier
hmp test regression -j auto      # parallel execution
hmp test regression --list       # list available regression tests
```

See `docs/developers/CLI.md` for the full test CLI reference.

---

## Workspace organization

A HydroModPy workspace groups shared data and multiple projects in a
single directory tree. After `hmp init` and a few runs, the workspace
looks like this:

```
~/hydromodpy/                          # workspace root (created by hmp init)
  catalog.db                           # data registry (created on first load)
  data/                                # shared data, one folder per variable
    hydrometry/
    piezometry/
    precipitation/
    recharge/
    ...
  projects/
    my_catchment/                      # one project = one catchment
      project.toml                     # base config (geographic, domain, flow)
      run_steady_nwt.toml              # run variant (inherits project.toml)
      run_transient_mf6.toml           # another variant, different solver
      run_steady_prototype.py          # optional Python script for prototyping
      results_stable/                  # preprocessing outputs (shared across runs)
        geographic/
          watershed_dem.tif
          watershed.shp
        geology/
      results_simulations/             # one subfolder per simulation run
        steady_nwt/
          my_catchment.nam
          _postprocess/
            watertable_elevation.npy
            _figures/
            _rasters/
        transient_mf6/
          ...
```

The key idea: `data/` is shared across all projects (API downloads,
cached grids), while each project has its own `results_stable/` and
`results_simulations/`.

### Data catalog (catalog.db)

The catalog is a small SQLite database that tracks every data file
downloaded or loaded. It avoids re-downloading data that is already on
disk.

Each entry records:

- **variable** and **source** (e.g. `recharge` / `sim2`)
- **file_path** pointing to the cached file (.csv, .nc, .tif)
- **bbox** (xmin, ymin, xmax, ymax) for gridded data
- **date_start** / **date_end** for the time period covered
- **station_id** for point data (one entry per station)

When a data manager needs data, it queries the catalog first:

1. If a cached entry covers the requested area and period, it loads the
   file directly from disk.
2. If the cache only covers part of the period, the manager fetches only
   the missing dates and merges the result.
3. If nothing is cached, the manager downloads the full dataset and
   registers it in the catalog.

For gridded data, the catalog also handles **subsumption**: when a larger
grid is stored, smaller grids fully contained inside it are automatically
removed to save disk space.

The `catalog.db` file is created automatically on first data load. You
do not need to create it manually.

### Project structure

A project directory typically contains:

- **`project.toml`** -- base configuration shared by all runs (geographic,
  domain, flow parameters, data sources). Created by `hmp new`.
- **`run_*.toml`** -- one file per run variant. Each inherits from
  `project.toml` (via `base_config`) and only overrides what changes:
  solver choice, time period, grid resolution, etc.
- **`*.py`** -- optional Python scripts for prototyping. These load the
  same `project.toml` but drive the execution from Python instead of
  using `[simulation]`.

For complex setups you can add an intermediate config layer:

```
project.toml                           # geographic + domain + flow
  config_fast_common.toml              # time window + data (inherits project.toml)
    run_fast_nwt.toml                  # solver = modflownwt (inherits config_fast_common.toml)
    run_fast_mf6.toml                  # solver = modflow6
  config_extensive_common.toml         # longer time window
    run_extensive_nwt.toml
    run_extensive_mf6.toml
```

This keeps each file short and avoids duplicating parameters.

### Output folders

- **`results_stable/`** -- geographic preprocessing, geology, hydrography
  rasters. Computed once and reused across runs. Subfolders match the data
  type name (`geographic/`, `geology/`, etc.).
- **`results_simulations/<run_id>/`** -- solver output files (.nam, .dis,
  .hds, etc.) and post-processing results (watertable, seepage maps,
  pathlines). One subfolder per run. The `run_id` is derived from the
  TOML filename (e.g. `run_fast_nwt.toml` produces `fast_nwt/`).

---

## TOML configuration guide

A minimal TOML for a steady-state simulation on the Canut catchment looks
like this:

```toml
[workspace]
project_root = "."

[geographic]
catch_def = "from_outlet_coord"
dem_init_path = "path/to/regional_dem.tif"
x_outlet = 327816.965
y_outlet = 6777886.670
snap_dist = "150 m"
buff_area = "10%"
crs_project = "EPSG:2154"

[domain]
zone_ids = ["geology"]

[domain.depth_model]
type = "constant_thickness"
thickness = "50.0 m"

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K", "Sy", "Ss"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/d"

[flow.param.K.field_homogeneous]
value = 1.728

[modflownwt.runtime]
mf_version = "mfnwt"
nwt_headtol = 1e-4

[modflownwt.sgrid.vertical]
nlay = 5
```

The recommended workflow:

1. Generate a template: `hmp config my_project.toml --profile user`
2. Open the file and read the comments -- they explain every parameter.
3. Fill in the values for your catchment.
4. Run: `hmp run my_project.toml`

Lengths accept SI-friendly strings: `"150 m"`, `"0.15 km"`, `"50.0 m"`.
Numeric values without units are interpreted as metres.

### Config inheritance (base_config)

TOML files can inherit from a parent file using `base_config`:

```toml
# run_steady_nwt.toml
base_config = "project.toml"

# Only override what changes for this run
[modflownwt.runtime]
nwt_headtol = 1e-4

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflownwt"]
```

The loader merges the parent TOML into the child recursively. Nested
dictionaries are merged key by key. Scalar values in the child override
the parent. This avoids repeating geographic, domain, and flow
parameters across multiple run configurations.

### Simulation section

The `[simulation]` section declares which processes to run and in what
order. It is required for `hmp simulation` but absent from prototype
scripts (where Python handles the orchestration).

```toml
[simulation]
name = "my_run"

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-12-31"
step_value = "30 day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflownwt"]

[[simulation.process]]
id = "transport_main"
type = "transport"
solvers = ["modpath"]
```

The planner resolves dependencies automatically (transport requires
flow to run first).

---

## Prototyping with Python

> **The official way to use HydroModPy is TOML-driven simulation mode**
> (`hmp run config.toml`). The TOML pipeline covers all standard workflows
> and is the recommended path for production runs, reproducibility, and
> collaboration.

Prototyping with Python is intended for **raw development of new
functionality that is not yet integrated into the launcher**. Typical
use cases: interfacing a new solver, testing an experimental boundary
condition, or manipulating internal objects (Domain, Flow, Surface) that
the TOML pipeline does not expose yet. Once the feature is stable, it
should be wired into the TOML configuration and the launcher so that
all users can access it without writing Python.

In prototype mode you skip the `[simulation]` section and drive the
execution from Python. The TOML still holds all physical parameters.
Only the orchestration is in Python.

Here is a minimal prototype that loads a config, builds the geographic
domain, and runs MODFLOW:

```python
from pathlib import Path
import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.domain import Domain
from hydromodpy.physics.flow import Flow
from hydromodpy.solver.modflow_nwt import Modflow, ModflowPreprocessOptions, ModflowRunOptions

# 1. Load config from TOML
config_path = Path("project.toml")
cfg = HydroModPyConfig.from_toml(config_path)

# 2. Workspace and geographic preprocessing
ws = hmp.Workspace(config=cfg.workspace)
geographic = hmp.Geographic(cfg.geographic, ws)
domain_geo = geographic.get_domain_geographic_context()

# 3. Build the 3D domain
domain = Domain(config=cfg.domain, surface_topo=domain_geo.surface_topo)

# 4. Build flow from config
flow = Flow(config=cfg.flow)

# 5. Override a parameter from Python if needed
# flow.parameters["K"].field_homogeneous.value = 2.0

# 6. Run MODFLOW-NWT
model = Modflow(
    geographic,
    modflow_config=cfg.modflownwt,
    model_folder=str(ws.simulations_folder),
    model_name=cfg.workspace.catch_name,
    bin_path=str(ws.bin_path),
)
model.pre_processing(flow=flow, domain=domain, options=ModflowPreprocessOptions())
model.processing(options=ModflowRunOptions(write_model=True, run_model=True))
```

See `examples/projects/01_canut/run_steady_prototype.py` for a complete
working example with visualization.

### Connecting to the geographic system

The geographic system extracts the watershed from a DEM:

```python
# From TOML config
geographic = hmp.Geographic(cfg.geographic, ws)
domain_geo = geographic.get_domain_geographic_context()

# domain_geo gives you:
#   domain_geo.surface_topo        -> surface topography (2D array + metadata)
#   domain_geo.watershed_shp       -> catchment polygon path
#   domain_geo.catchment_area_km2  -> catchment area in km2
```

For synthetic (analytical) domains, set `source_mode = "synthetic"` in the
TOML and configure the `[geographic.synthetic]` sub-section.

---

## Data managers

Data managers load observational and forcing data (hydrometry, piezometry,
precipitation, recharge, etc.) from various sources.

### Supported variables

| Variable | Point data | Gridded data | Sources |
|----------|-----------|-------------|---------|
| hydrometry | yes | no | `custom` (CSV), `hubeau` (API) |
| piezometry | yes | no | `custom`, `hubeau` |
| water_quality | yes | no | `custom`, `hubeau` |
| intermittency | yes | no | `custom`, `hubeau` |
| precipitation | yes | yes | `custom`, `sim2` (NetCDF) |
| etp | yes | yes | `custom`, `sim2` |
| temperature | yes | yes | `custom`, `sim2` |
| recharge | yes | yes | `custom`, `sim2`, `synthetic` |
| runoff | yes | yes | `custom`, `sim2` |

### Standard data contracts

All managers return the same types:

- **`PointRecord`**: one time series at one station (station_id, data
  DataFrame, unit, location).
- **`FieldRecord`**: one gridded field at one timestep (2D array +
  spatial metadata).
- **`StationLocation`**: coordinates (x, y) and optional metadata.
- **`LoadResult`**: container with `points: list[PointRecord]` and
  `fields: list[FieldRecord]`.

### Custom data format

For `source = "custom"`, place your data in a directory with:

1. A **LOC file** (`*_LOC.csv`): station metadata.
2. One **chronicle CSV per station**: timestamped values.

**LOC file columns:**

| Column | Required | Description |
|--------|----------|-------------|
| `id` | yes | Station identifier (must match chronicle filename) |
| `x` | yes | X coordinate |
| `y` | yes | Y coordinate |
| `crs` | yes | Coordinate reference system (e.g. `EPSG:4326`) |
| `unit` | yes | Physical unit of the data (e.g. `m3/s`, `m`) |
| `name` | no | Human-readable station name |

**Chronicle CSV columns:**

| Column | Required | Description |
|--------|----------|-------------|
| `datetime` | yes | Timestamp (ISO 8601, e.g. `2020-01-15`) |
| `value` | yes | Measured value |

**File naming convention:**

```
{variable}_{source}_{station_id}_{start}_{end}_{freq}.csv
```

Example: `hydrometry_custom_J001401001_20000101_20201231_D.csv`
(daily discharge for station J001401001, 2000 to 2020).

**Example directory:**
```
data/hydrometry/
  hydrometry_custom_LOC.csv
  hydrometry_custom_STATION01_20000101_20201231_D.csv
  hydrometry_custom_STATION02_20000101_20201231_D.csv
```

Gridded data uses NetCDF (`.nc`) or GeoTIFF (`.tif`) instead of CSV.

### Using data managers from Python

```python
from hydromodpy.data_managers.store import DataStore
from hydromodpy.data_managers.variables.hydrometry.config import (
    HydrometryConfig, HydrometrySourceConfig,
)

store = DataStore(workspace_root=ws_root, project_extent=bbox, project_period=period)

cfg_hydro = HydrometryConfig(
    sources=[HydrometrySourceConfig(source="custom", path="data/hydrometry")],
    date_start="2000-01-01",
    date_end="2020-12-31",
)

records = store.load_hydrometry(cfg_hydro)
for r in records:
    print(f"{r.station_id}: {r.n_records} points, unit={r.unit}")
```

### Exporting data configs to TOML

```python
from hydromodpy.config.generate_toml import generate_toml_from_instances

generate_toml_from_instances(
    {"hydrometry": cfg_hydro, "piezometry": cfg_piezo},
    output_path="data_config.toml",
    exclude_defaults=True,
    exclude_none=True,
)
```

See `examples/projects/data_setup/` for complete examples.

---

## Configuration system (Pydantic + TOML)

All configuration in HydroModPy is defined with [Pydantic](https://docs.pydantic.dev/)
models. The TOML files that users edit are generated from these models. This
means the TOML is always in sync with the code: field names, types, defaults
and descriptions are derived from a single source of truth.

### Declaring fields

Every field **must** have:

1. A `ParamLevel` annotation (see below).
2. A `description` in `Field(...)`.

Without a description the TOML generator produces empty comments and the
Streamlit UI shows a blank tooltip. Without a `ParamLevel` the field
defaults to `"user"` level, which may expose internal parameters to end
users.

Pattern:

```python
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from hydromodpy.config.param_level import ParamLevel, VisibleWhen

class MyConfig(BaseModel):
    """Short description that appears as TOML section header."""

    model_config = ConfigDict(extra="forbid")

    method: Annotated[Literal["a", "b"], ParamLevel("user")] = Field(
        default="a",
        description="Method selection. 'a' does X. 'b' does Y.",
    )
    threshold: Annotated[float, ParamLevel("dev")] = Field(
        default=0.01,
        gt=0,
        description="Convergence threshold in metres.",
    )
    debug_path: Annotated[Optional[Path], ParamLevel("expert")] = Field(
        default=None,
        description="Path to dump debug arrays. Leave empty for production runs.",
    )
```

Key rules:

- Use `ConfigDict(extra="forbid")` to reject unknown keys in the TOML.
- Use `Literal[...]` for enumerated choices (the TOML generator prints
  `one of: "a", "b"` automatically).
- Use `gt=`, `ge=`, `lt=`, `le=` for numeric constraints (printed in the
  TOML comment).
- Write descriptions as **plain sentences** that explain what the parameter
  does and when it is needed. Descriptions are split on `. ` for line
  wrapping in the generated TOML.

### ParamLevel

`ParamLevel` controls which parameters appear in the generated TOML
depending on the requested profile.

| Level      | Audience | Visible at profile |
|------------|----------|--------------------|
| `"user"`   | End users, students, new users | `--profile user`, `dev`, `expert` |
| `"dev"`    | Developers, experienced users | `--profile dev`, `expert` |
| `"expert"` | Internal / advanced tuning | `--profile expert` only |

A field tagged `ParamLevel("dev")` is hidden when the TOML is generated
with `--profile user`. This keeps the user-facing config short while still
allowing full control when needed.

### VisibleWhen

`VisibleWhen` adds conditional visibility. The field is only shown in the
TOML (and the Streamlit UI) when a sibling field has a specific value:

```python
catch_def: Annotated[
    Optional[Literal["dem", "txt", "from_outlet_coord"]],
    ParamLevel("user"),
] = Field(default=None, description="Catchment definition mode.")

x_outlet: Annotated[
    Optional[float],
    ParamLevel("user"),
    VisibleWhen("catch_def", "from_outlet_coord"),
] = Field(default=None, description="X coordinate of the outlet.")
```

Here `x_outlet` only appears when `catch_def = "from_outlet_coord"`.
Multiple allowed values can be passed as a tuple:
`VisibleWhen("catch_def", ("from_outlet_coord", "from_polyg_shp"))`.

### Validators

Use standard Pydantic validators when the TOML value needs normalization
or cross-field validation:

```python
from pydantic import field_validator, model_validator

@field_validator("snap_dist", mode="before")
@classmethod
def _normalize_snap_dist(cls, value):
    """Accept '150 m' or '0.15 km' and convert to float metres."""
    if value is None:
        return None
    from hydromodpy.support.units import parse_length_to_m
    return float(parse_length_to_m(value, default_unit="m", label="snap_dist"))

@model_validator(mode="after")
def _check_requirements(self) -> "MyConfig":
    """Cross-field validation after all fields are set."""
    if self.method == "b" and self.threshold is None:
        raise ValueError("threshold is required when method='b'.")
    return self
```

### Adding a new config section

1. Create a Pydantic model following the pattern above.
2. Register it in `hydromodpy/config/generate_toml.py` inside
   `_get_registry()`:
   ```python
   from mypackage.my_config import MyConfig
   _MODULE_REGISTRY["my_section"] = MyConfig
   ```
3. The new section is now available via `hmp config --modules my_section`
   and in the top-level `HydroModPyConfig`.

---

## Running tests

```bash
# Fast unit tests (parallel)
python -m pytest -m "fast" -q -n auto

# Full regression suite
hmp test regression --fast
hmp test regression --extensive

# Specific solver family
hmp test regression --nwt
hmp test regression --mf6

# Update golden references (overwrites expected outputs)
hmp test regression --update-goldens
```

---

## Pull requests

1. Fork the repository and create a branch from `dev-refact` (or the
   relevant development branch).
2. Install in editable mode: `pip install -e .`
3. Make your changes. Follow the patterns described above for Pydantic
   configs (ParamLevel, description, ConfigDict).
4. Run the fast test suite: `hmp test regression --fast -j auto`
5. Open a pull request against the development branch.

Keep pull requests focused on a single topic. If your change touches
configuration, make sure the TOML generator still produces valid output:

```bash
hmp config /tmp/test_config.toml --profile user
hmp config /tmp/test_config.toml --profile expert
```

---

## License

HydroModPy is released under the [Eclipse Public License 2.0](https://opensource.org/licenses/EPL-2.0).
