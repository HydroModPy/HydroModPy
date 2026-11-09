"""Synthetic projects for the scenario tests, written as TOML text.

The island is a 610 m square grid with one layer and an ocean on the shore.
Five variants play it with a different solver or workflow, and five more start
it from a computed or an earlier state. Four more carry a transport process
behind the flow, in the order the planner reads, the flow first and the
transport after it. One more, ``v2_1_forms``, writes the solver tables where 2.0.0
wrote them, which the register of changes moves. Every project is
built from the literal texts below. The factory reads no file, opens no network
and draws no random number, so a project has the same bytes on every machine.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

ISLAND_VARIANTS: tuple[str, ...] = ("gwt", "nwt", "boussinesq", "spinup", "calage")

INITIAL_STATE_VARIANTS: tuple[str, ...] = (
    "steady_ic_modflow6",
    "steady_ic_nwt",
    "steady_ic_boussinesq",
    "cyclic_ic",
    "restart",
)

# The three transport chains of the lot matrix, beside the island variants.
# A fourth case, ``nwt_modpath_seepage_clip``, is the same island again and
# stays outside this tuple: it carries ``zone_partic = "seepage_clip"`` only.
TRANSPORT_VARIANTS: tuple[str, ...] = (
    "nwt_mt3dms",
    "mf6_prt",
    "nwt_modpath",
)

TRANSIENT = """\
[workflow]
mode = "simulation"

[site]
name = "island"

[workspace]

[simulation]
name = "@NAME@"

[simulation.results]
keep_solver_files = false

[simulation.results.persistence]
field_precision = "exact"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["@SOLVER@"]
@TRANSPORT_PROCESS@
[display]
enabled = false

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-03-31"
step_value = "1 month"
coverage_policy = "ignore"

[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "island"

[geographic.synthetic.grid]
length_x = "610.0 m"
length_y = "610.0 m"
nx = 31
ny = 31

[geographic.synthetic.topography]
kind = "radial_island"
base_elevation = -1.0
crest_elevation = 12.0
island_radius = "200.0 m"

[domain.depth_model]
kind = "flat_substratum"
substratum_elevation = -5.0

[data]
types = ["oceanic"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0


[flow]
flow_regime = "transient"
first_period_steady = true
param_list = ["K", "Sy", "Ss"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-6 m/s"

[flow.bc.ocean]
kind = "dirichlet"
value = "0.0 m"

[flow.bc.drainage]

[flow.sinks_sources.recharge]
values = [1.0, 4.0, 2.0]

[domain.layers]
nlay = 1

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5
"""

TRANSPORT_PROCESS = """
[[simulation.process]]
id = "transport_main"
kind = "transport"
solvers = ["modflow6"]
"""

# The gwt island keeps the table shape of 2.0.0, the table the reference island
# writes, so both texts stay one. A living file in that shape still loads, with a
# migration warning, until its row leaves in 2.3.0.
TRANSPORT_PARAMETERS = """

[transport.modflow6gwt.parameters]
sconc_init = 0.1
sconc_input = 0.05
diffu_coeff = 1e-10
react_order = 1
rate_decay = 1.585489599e-08
"""

# The transport table of a variant, at the registry name of its solver. Empty
# for nwt_modpath, which keeps every default.
TRANSPORT_TAILS: dict[str, str] = {
    "nwt_mt3dms": "\n[transport.mt3dms]\nporosity = 0.1\n",
    "mf6_prt": "\n[transport.modflow6_prt]\nporosity = 0.1\n",
    "nwt_modpath": "",
    "nwt_modpath_seepage_clip": '\n[transport.modpath]\nzone_partic = "seepage_clip"\n',
}

# The solver tables of 2.0.0, which 2.1.0 moves under [solver]: the backend as a table
# with a kind, and the settings of the flow solver at the root. A file in this shape
# still loads, with a migration warning, and a sealed run of 2.0.0 replays.
OLDER_SOLVER_TABLES = """

[solver.backend]
kind = "modflow6"

[modflow6.runtime]
mf6_ims_complexity = "MODERATE"
"""

TRIANGLE_MESH = """
[mesh]
engine = "triangle"
cell_size = 30.0
"""

SPINUP_TAIL = """

[spinup]
max_cycles = 4
tol_head = 0.05
tol_stage = 0.05
"""

STEADY_IC_TAIL = """

[flow.ic]
kind = "steady_state"
source = "mean_recharge"
"""

CYCLIC_IC_TAIL = """

[flow.ic]
kind = "spinup_cyclic"
max_cycles = 3
tol_head = "1e-9 m"
"""

STEADY = """\
[workflow]
mode = "simulation"

[site]
name = "island"

[workspace]

[simulation]
name = "calage"

[simulation.results]
keep_solver_files = false

[simulation.results.persistence]
field_precision = "exact"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[display]
enabled = false

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-02 00:00:00"
step_value = "1 day"
coverage_policy = "ignore"

[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "island"

[geographic.synthetic.grid]
length_x = "610.0 m"
length_y = "610.0 m"
nx = 31
ny = 31

[geographic.synthetic.topography]
kind = "radial_island"
base_elevation = -1.0
crest_elevation = 12.0
island_radius = "200.0 m"

[domain.depth_model]
kind = "flat_substratum"
substratum_elevation = -5.0

[data]
types = ["oceanic", "recharge", "piezometry"]
inference_mode = "warn"

[[data.oceanic.sources]]
source = "constant"
value = 0.0

[[data.recharge.sources]]
source = "synthetic"
values = [1.0]

[[data.piezometry.sources]]
source = "file"
path = "data/piezometry"
default_crs = "EPSG:2154"
source_unit = "m"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-6 m/s"

[flow.bc.ocean]
kind = "dirichlet"
value = "0.0 m"


[flow.bc.drainage]

[flow.sinks_sources.recharge]
first_clim = "mean"

[domain.layers]
nlay = 1
"""

CALIB = """\
base_config = "project.toml"
export__delete = true

[workflow]
mode = "calibration"

[simulation]
name = "calage"

[calibration]
save_runs = "best_n"
use_cache = false
persist_trial_series = true

[calibration.parameters.K]
bounds = [2e-6, 2e-5]
search_space = "log"

[calibration.outputs.crest_head]
support = "point"
variable = "head"
observes = "W1"

[[calibration.objective_blocks]]
name = "heads"
metric = "rmse"
uses_outputs = ["crest_head"]

[[calibration.phases]]
name = "k_grid"
parameters = ["K"]
regime = "steady"
objective_blocks = ["heads"]
method = "grid"
max_trials = 3
method_options = { points_per_dim = 3 }

[display]
enabled = false
"""

STATION_LOC = "id,x,y\nW1,305.0,305.0\n"
STATION_RECORD = "datetime,value\n2003-01-01,2.0\n2003-01-02,2.0\n"


def transient_island(
    name: str, solver: str, *, mesh: str = "", process: str = "", tail: str = ""
) -> str:
    """Return the TOML text of the three-month island played by ``solver``."""
    text = TRANSIENT.replace("@NAME@", name).replace("@SOLVER@", solver)
    text = text.replace("@TRANSPORT_PROCESS@", process)
    return text + mesh + tail


def island_files(variant: str) -> dict[str, str]:
    """Return the files of one island variant, relative path to text."""
    if variant == "gwt":
        text = transient_island(
            variant, "modflow6", process=TRANSPORT_PROCESS, tail=TRANSPORT_PARAMETERS
        )
    elif variant == "nwt":
        text = transient_island(variant, "modflow_nwt")
    elif variant == "boussinesq":
        text = transient_island(variant, "boussinesq", mesh=TRIANGLE_MESH)
    elif variant == "spinup":
        text = transient_island(variant, "modflow6", tail=SPINUP_TAIL)
    elif variant == "v2_1_forms":
        text = transient_island(variant, "modflow6", tail=OLDER_SOLVER_TABLES)
    elif variant == "calage":
        return {
            "project.toml": STEADY,
            "calib.toml": CALIB,
            "data/piezometry/piezometry_custom_LOC.csv": STATION_LOC,
            "data/piezometry/piezometry_custom_W1_D.csv": STATION_RECORD,
        }
    else:
        raise KeyError(variant)
    return {"project.toml": text}


def _first_period_unsteady(text: str) -> str:
    """Turn the steady first period off, so that the start state reaches the heads."""
    return text.replace("first_period_steady = true", "first_period_steady = false")


def initial_state_files(variant: str) -> dict[str, str]:
    """Return the files of one island that starts from a computed or an earlier state.

    The steady variants start from the steady solve of their own solver. The
    cyclic variant repeats the three months up to three times. The restart
    variant holds three configurations to play in this order: ``prior.toml``,
    ``resumed.toml``, which names the first run in ``flow.restart_from``, and
    ``cold.toml``, the same run without a restart.
    """
    if variant == "steady_ic_modflow6":
        text = transient_island(variant, "modflow6", tail=STEADY_IC_TAIL)
    elif variant == "steady_ic_nwt":
        text = transient_island(variant, "modflow_nwt", tail=STEADY_IC_TAIL)
    elif variant == "steady_ic_boussinesq":
        text = transient_island(variant, "boussinesq", mesh=TRIANGLE_MESH, tail=STEADY_IC_TAIL)
    elif variant == "cyclic_ic":
        text = transient_island(variant, "modflow6", tail=CYCLIC_IC_TAIL)
    elif variant == "restart":
        prior = transient_island("prior", "modflow6")
        resumed = _first_period_unsteady(transient_island("resumed", "modflow6")).replace(
            "[flow]\n", '[flow]\nrestart_from = "prior"\n', 1
        )
        cold = _first_period_unsteady(transient_island("cold", "modflow6"))
        return {"prior.toml": prior, "resumed.toml": resumed, "cold.toml": cold}
    else:
        raise KeyError(variant)
    return {"project.toml": _first_period_unsteady(text)}


def transport_island(name: str, flow_solver: str, transport_solver: str, *, tail: str = "") -> str:
    """Return the island TOML with one transport process behind its flow.

    The flow process comes first, the transport after it, in the order the
    planner reads.
    """
    process = (
        "\n[[simulation.process]]\n"
        'id = "transport_main"\n'
        'kind = "transport"\n'
        f'solvers = ["{transport_solver}"]\n'
    )
    return transient_island(name, flow_solver, process=process, tail=tail)


def transport_variant_files(variant: str) -> dict[str, str]:
    """Return the files of one island with a transport process behind its flow.

    The transport solver follows the flow solver its ``requires`` declares, and
    carries its default parameters with a porosity given instead of the
    specific-yield fallback, in the ``[transport.<name>]`` table the registry
    names. A variant keeps its solver files, so a scenario can read what the
    flow leaves to its transport: the link file of MT3DMS, the head and budget
    files MODPATH reads, and the seepage raster. ``nwt_modpath_seepage_clip``,
    outside ``TRANSPORT_VARIANTS``, releases the particles from the seepage
    areas of the flow run, ``zone_partic = "seepage_clip"``.
    """
    solved_by = {
        "nwt_mt3dms": ("modflow_nwt", "mt3dms"),
        "mf6_prt": ("modflow6", "modflow6_prt"),
        "nwt_modpath": ("modflow_nwt", "modpath"),
        "nwt_modpath_seepage_clip": ("modflow_nwt", "modpath"),
    }
    if variant not in solved_by:
        raise KeyError(variant)
    flow_solver, transport_solver = solved_by[variant]
    text = transport_island(variant, flow_solver, transport_solver, tail=TRANSPORT_TAILS[variant])
    return {
        "project.toml": text.replace("keep_solver_files = false", "keep_solver_files = true"),
    }


def write_project(root: Path, files: Mapping[str, str]) -> Path:
    """Write ``files`` under ``root``, which must be absent or empty, and return ``root``."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"the project folder is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"the path must stay inside the project: {relative}")
        target = root.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root


def files_digest(files: Mapping[str, str]) -> str:
    """Return the sha256 of the files, in sorted order of their relative paths."""
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(files[relative].encode("utf-8") + b"\0")
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """Return the same digest, read back from the files under ``root``."""
    root = Path(root)
    found = {
        path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }
    return files_digest(found)


# The one-cell basin the global backend runs: the catchment mesh engine takes
# the whole synthetic domain as the one cell it meshes and the reservoir reads
# its recharge there. No ocean boundary, no aquifer property, no mesh section:
# the engine of the run is deduced from the backend.
BASIN = """\
[workflow]
mode = "simulation"

[site]
name = "basin"

[workspace]

[simulation]
name = "basin"

[simulation.results]
keep_solver_files = false

[simulation.results.persistence]
field_precision = "exact"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["linear_reservoir"]

[display]
enabled = false

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-01-20"
step_value = "1 day"
coverage_policy = "ignore"

[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "basin"

[geographic.synthetic.grid]
length_x = "610.0 m"
length_y = "610.0 m"
nx = 31
ny = 31

[geographic.synthetic.topography]
kind = "flat"
base_elevation = 100.0

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "synthetic"
values = [1.5]

[flow]
flow_regime = "transient"
first_period_steady = true

[flow.ic]
kind = "steady_state"
source = "mean_recharge"

[flow.sinks_sources.recharge]

[solver]
backend = "linear_reservoir"

[solver.linear_reservoir]
time_constant = "30 days"
"""

# The daily recharge of the basin, written as the two files the file source
# reads under data/recharge/: the station table, which holds the unit, and the
# chronicle, one rate a day over the window in mm per day. The station sits at
# the centre of the synthetic domain. The basin that uses it receives the rate
# at the step of the file, beside the period view.
BASIN_RECHARGE_STATIONS = """\
id,x,y,crs,unit
BASIN_5D,305.0,305.0,EPSG:2154,mm/day
"""

BASIN_DAILY_RECHARGE = """\
datetime,value
"""
for _day in range(1, 21):
    BASIN_DAILY_RECHARGE += f"2003-01-{_day:02d},{1.0 + (_day % 5) * 0.5:.1f}\n"

# The run of the basin on five-day periods, the long step the report reads. The
# recharge of every one of its four periods varies inside the period, so a
# reading that took one value per period would not answer for the water.
BASIN_5D = (
    BASIN.replace('step_value = "1 day"', 'step_value = "5 days"')
    .replace('[simulation]\nname = "basin"', '[simulation]\nname = "basin_5d"')
    .replace(
        'source = "synthetic"\nvalues = [1.5]',
        'source = "file"\npath = "data/recharge"\ndefault_crs = "EPSG:2154"',
    )
)


def basin_files(with_daily_recharge: bool = False) -> dict[str, str]:
    """Return the files of one basin project, relative path to text.

    The daily recharge goes beside the project as the file the file source
    reads; the project that runs on daily periods carries none.
    """
    files = {"project.toml": BASIN_5D if with_daily_recharge else BASIN}
    if with_daily_recharge:
        files["data/recharge/recharge_file_LOC.csv"] = BASIN_RECHARGE_STATIONS
        files["data/recharge/recharge_file_BASIN_5D_20030101_20030120_D.csv"] = BASIN_DAILY_RECHARGE
    return files
