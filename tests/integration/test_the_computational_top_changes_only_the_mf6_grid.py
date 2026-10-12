"""The computational top changes the MODFLOW 6 grid and nothing else.

Two projects with a thickness that varies from cell to cell are written twice:
once as HydroModPy builds them, once with the computational top held at the
ground. The DISV top and the WEL ``AUTO_FLOW_REDUCE`` fraction may differ, and
nothing else: every other elevation of every package (DRN, EVT, SFR, LAK, HFB,
WEL, the ocean CHD, the initial heads) stays the same byte for byte, and so do
the ground and descent files the extractor reads. This guards the rule that
only the grid MODFLOW 6 reads carries the computational top.

The valley is the synthetic Cheze fixture (``tests/data/sfr_cheze/``) on a flat
substratum, with a lake, its stream network, drains, evapotranspiration, a
barrier, two wells and evapotranspiration. The island is the circular island of the validation
cases, with its ocean.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.support import computational_top as rule

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHEZE = _REPO_ROOT / "tests" / "data" / "sfr_cheze"

_COMMON = """\
[workflow]
mode = "simulation"

[workspace]
project_root = "{root}"

[simulation]
name = "toit"

[simulation.results]
keep_solver_files = true


[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[display]
enabled = false
"""

_VALLEY = (
    _COMMON
    + f"""
[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-30 00:00:00"
step_value = "15 day"
coverage_policy = "ignore"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{_CHEZE / "dem_valley.tif"}"
x_outlet = 300037.5
y_outlet = 6701262.5
snap_dist = "60 m"
buff_area = "10%"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1
compute_stream_links = true
compute_strahler_order = true

[domain.depth_model]
kind = "flat_substratum"
substratum_elevation = "60.0 m"

[flow]
flow_regime = "transient"
first_period_steady = true
active_sinks_sources = ["recharge", "wells"]
active_bc = ["lake", "sfr", "drainage"]
param_list = ["K", "Sy", "Ss"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-5 m/s"

[flow.param.Sy.field]
kind = "homogeneous"
value = "0.05 -"

[flow.param.Ss.field]
kind = "homogeneous"
value = "1e-6 m-1"

[flow.ic]
type = "top"

[flow.bc.drainage]
application_domain = "top"
value = "0.0 m2/s"

# A negative rate goes to the EVT package, the streams and the lake feed the
# aquifer.
[flow.sinks_sources.recharge]
values = -0.3

[flow.sinks_sources.wells.hill]
flux = -0.0005
units = "m3/s"

[flow.sinks_sources.wells.hill.location]
kind = "absolute_xy"
x = 301500.0
y = 6701800.0

[flow.sinks_sources.wells.valley]
flux = -0.0002
units = "m3/s"

[flow.sinks_sources.wells.valley.location]
kind = "absolute_xy"
x = 300800.0
y = 6701300.0

[flow.sinks_sources.flow_barriers.wall]
line = [[301000.0, 6700600.0], [301000.0, 6702000.0]]
depths = [5.0]
hydchr = 1e-9

[flow.sinks_sources.lakes.res0]
bedleak = 1e-10
bedleak_unit = "1/s"
stageinit = "93.0 m"

[[flow.sinks_sources.lakes.res0.outlets]]
couttype = "WEIR"
invert = "94.0 m"
width = "5.0 m"
lakeout = 0

[flow.sinks_sources.sfr.net0]
streambed_k = 1e-5
streambed_k_unit = "m/s"
streambed_thickness = "1 m"
manning = 0.035
outflow_to_lake = 1
outlet_keepout = "100 m"

[flow.sinks_sources.sfr.net0.runoff]
kind = "constant"
value = 0.002
units = "m3/s"

[flow.sinks_sources.sfr.net0.width]
kind = "constant"
value = "2 m"

[[data.lake_geometry.sources]]
source = "custom"
path = "{_CHEZE / "lake_geometry.gpkg"}"

[[data.lake_abacus.sources]]
source = "custom"
path = "{_CHEZE / "lake_abacus.csv"}"
lake_id = "res0"

[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 30
ny = 30

[modflow6.sgrid.vertical]
nlay = 2
"""
)

_ISLAND = (
    _COMMON
    + """
[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-02 00:00:00"
step_value = "1 day"
coverage_policy = "ignore"

[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "toit_island"

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
runoff_ratio = 0.0

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

[modflow6.sgrid.vertical]
nlay = 1
"""
)

CASES = {"valley": _VALLEY, "island": _ISLAND}

# Solver outputs and listings: results, not inputs.
_OUTPUT_SUFFIXES = {".hds", ".cbc", ".lst", ".grb", ".csv", ".tif", ".json", ".stage", ".obs"}
_FLOPY_STAMP = re.compile(r"^#.*$", re.MULTILINE)


# The packages each case must write, so that the comparison covers them.
PACKAGES = {
    "valley": {".drn", ".evta", ".sfr", ".lak", ".mvr", ".hfb", ".wel", ".ic"},
    "island": {".chd", ".drn", ".ic"},
}


def _ground_held(ground, layer_bottom, raised):
    del layer_bottom, raised
    return np.asarray(ground, dtype=float).reshape(-1).copy()


def run_in_process(root: str, case: str, raised: bool) -> None:
    """Run ``case`` in ``root``, the computational top held at the ground unless ``raised``."""
    from hydromodpy.project.facade import Project

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    config = root_path / "project.toml"
    config.write_text(CASES[case].replace("{root}", root_path.as_posix()), encoding="utf-8")
    if not raised:
        rule.computational_top = _ground_held
    project = Project(config, no_display=True)
    try:
        project.simulate()
    finally:
        project.close()


def run_case(root: Path, case: str, *, raised: bool) -> Path:
    """Run ``case`` in a child process; return the folder MODFLOW 6 was written to.

    The child keeps the DEM backend out of the long-lived pytest worker, and the
    rule it holds at the ground dies with it.
    """
    code = (
        "from tests.integration.test_the_computational_top_changes_only_the_mf6_grid "
        f"import run_in_process; run_in_process({str(root)!r}, {case!r}, {raised!r})"
    )
    subprocess.run([sys.executable, "-c", code], cwd=_REPO_ROOT, check=True)
    folders = [p for p in (root / ".hmp" / "scratch").glob("*/*") if any(p.glob("*.disv"))]
    assert len(folders) == 1, folders
    return folders[0]


def written_inputs(folder: Path) -> dict[str, str | bytes]:
    """Return every input file MODFLOW 6 and the extractor read, by name."""
    files: dict[str, str | bytes] = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix in _OUTPUT_SUFFIXES:
            continue
        if path.suffix == ".npz":
            with np.load(path) as payload:
                files[path.name] = b"".join(
                    name.encode() + payload[name].tobytes() for name in sorted(payload.files)
                )
            continue
        files[path.name] = _FLOPY_STAMP.sub("", path.read_text(encoding="utf-8"))
    return files


def _options_without_auto_flow_reduce(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "auto_flow_reduce" not in line.lower())


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, tuple[Path, Path]]:
    root = tmp_path_factory.mktemp("computational_top")
    return {
        case: (
            run_case(root / case / "on", case, raised=True),
            run_case(root / case / "off", case, raised=False),
        )
        for case in CASES
    }


@pytest.mark.parametrize("case", sorted(CASES))
def test_only_the_grid_and_the_well_turnoff_differ(built, case) -> None:
    on, off = (written_inputs(folder) for folder in built[case])
    assert sorted(on) == sorted(off)
    assert PACKAGES[case] <= {Path(name).suffix for name in on}

    differ = sorted(name for name in on if on[name] != off[name])
    assert all(name.endswith((".disv", ".wel")) for name in differ), differ
    assert any(name.endswith(".disv") for name in differ), "the thickness varies: T' != G"
    for name in differ:
        if name.endswith(".wel"):
            assert _options_without_auto_flow_reduce(on[name]) == (
                _options_without_auto_flow_reduce(off[name])
            )


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_grid_moves_only_the_top_and_only_upwards(built, case) -> None:
    import flopy

    grids = []
    for folder in built[case]:
        sim = flopy.mf6.MFSimulation.load(sim_ws=str(folder), verbosity_level=0, load_only=["disv"])
        grids.append(sim.get_model().disv)
    on, off = grids
    np.testing.assert_array_equal(on.botm.array, off.botm.array)
    np.testing.assert_array_equal(on.idomain.array, off.idomain.array)
    assert on.cell2d.array.tolist() == off.cell2d.array.tolist()
    raised = np.asarray(on.top.array) - np.asarray(off.top.array)
    assert raised.min() >= 0.0
    assert raised.max() > 0.0


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_store_keeps_the_ground_geometry(built, case) -> None:
    import zarr

    meshes = []
    for folder in built[case]:
        (store,) = (folder.parents[3] / "runs").glob("*/fields.zarr")
        meshes.append(zarr.open_group(str(store), mode="r")["mesh"])
    on, off = meshes
    for name in ("topography", "z_interfaces", "layer_thickness", "descent_surface"):
        np.testing.assert_array_equal(on[name][:], off[name][:], err_msg=name)
