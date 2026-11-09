"""A small synthetic island project, solved by MODFLOW 6 in a few seconds.

One layer, a steady state under a uniform recharge and an ocean on the shore.
``island_toml`` writes its configuration; ``run_island`` solves it in a child
process, which keeps the DEM backend out of a long-lived pytest worker.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_ISLAND = """\
[workflow]
mode = "simulation"

[site]
name = "island"

[workspace]

[simulation]
name = "{name}"

[simulation.results]
keep_solver_files = {keep}

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
types = ["oceanic", "recharge"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0

[[data.recharge.sources]]
source = "synthetic"
values = [1.0]

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

{wells}
[flow.sinks_sources.recharge]
first_clim = "mean"

[domain.layers]
nlay = 1
"""

_WELL = """\
[flow.sinks_sources.wells.pump]
flux = {flux}
units = "m3/s"

[flow.sinks_sources.wells.pump.location]
kind = "absolute_xy"
x = 305.0
y = 305.0
"""


def island_toml(
    name: str, *, keep_solver_files: bool = False, well_flux: float | None = None
) -> str:
    """Return the configuration of the island run ``name``.

    A ``well_flux`` in m3/s (negative pumps) adds one well on the crest, in the
    first layer, which ``AUTO_FLOW_REDUCE`` cuts when the rate exceeds what the
    cell can give.
    """
    wells = "" if well_flux is None else _WELL.format(flux=well_flux)
    return _ISLAND.format(name=name, keep=str(keep_solver_files).lower(), wells=wells)


def run_island(config: Path, *, cwd: Path = REPO_ROOT) -> None:
    """Solve the project of ``config`` in a child process and raise when it fails."""
    code = (
        "from pathlib import Path\n"
        "from hydromodpy.project.facade import Project\n"
        f"project = Project(Path({str(config)!r}), no_display=True)\n"
        "try:\n"
        "    project.simulate()\n"
        "finally:\n"
        "    project.close()\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=cwd, check=True)
