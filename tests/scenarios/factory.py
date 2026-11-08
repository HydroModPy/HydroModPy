"""Synthetic projects for the scenario tests, written as TOML text.

The island is a 610 m square grid with one layer and an ocean on the shore.
Five variants play it with a different solver or workflow, and five more start
it from a computed or an earlier state. Every project is
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
active_sinks_sources = ["recharge"]
active_bc = ["ocean", "drainage"]
param_list = ["K", "Sy", "Ss"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-6 m/s"

[flow.bc.ocean]
kind = "dirichlet"
value = "0.0 m"


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

TRANSPORT_PARAMETERS = """

[transport.modflow6gwt.parameters]
sconc_init = 0.1
sconc_input = 0.05
diffu_coeff = 1e-10
react_order = 1
rate_decay = 1.585489599e-08
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
source = "custom"
path = "piezometry"
default_crs = "EPSG:2154"
source_unit = "m"

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["ocean", "drainage"]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-6 m/s"

[flow.bc.ocean]
kind = "dirichlet"
value = "0.0 m"


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
