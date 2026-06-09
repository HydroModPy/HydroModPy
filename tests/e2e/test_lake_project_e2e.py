"""End-to-end: a config-declared lake flows through the REAL pipeline to LAK.

This is the executable acceptance criterion for the dev-lakeres -> MF6 port. It
proves (or, today, documents the gap that prevents) a lake declared purely in a
HydroModPy config TOML reaching the MODFLOW 6 LAK package through the production
chain:

    config TOML
      -> Project / standard_steps Pipeline (the same workflow as ``hmp run``)
      -> data layer (planner infers the lake_* families; the loader reads the
         CUSTOM lake_geometry polygon + lake_abacus table into FieldRecord /
         TableRecord)
      -> mesh build
      -> flow / LAK package build (build_lak_package_args)
      -> real mf6 run
      -> lake result extraction (ResultStore timeseries keyed ``lake:<id>``)

It is NOT a hand-built flopy model: the lake enters only through the synthetic
CUSTOM data sources declared in the config, so the data managers / planner /
loader sit on the critical path. This is the distinction from the flopy-direct
LAK tests under tests/validation and tests/integration, which hardcode
``polygon=None`` and bypass Project / Flow / the data layer entirely.

The pipeline is wired end to end (no xfail)
-------------------------------------------
The data -> flow binders (``apply_lake_geometry_to_flow`` /
``apply_lake_abacus_to_flow`` in structure_binders.py) run in the planning step,
so the loaded lake_geometry polygon and lake_abacus table reach the flow lake
payload, ``_active_lake_definitions`` resolves the lake, and the LAK build branch
fires for real. The primary test therefore asserts a genuine LAK build: a
``*.lak`` file is written and a finite ``lake:<id>`` stage series lands in the
ResultStore. The negative-control test asserts no LAK is built when no lake is
declared.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from tests.regression.golden_utils import (
    _open_result_store,
    _resolve_sim_id,
    assert_required_executables,
    resolve_model_workspace,
    run_hmp_cli,
)

# Outlet of the committed regional DEM catchment (EPSG:2154); the synthetic lake
# polygon is centred here so it lands inside the delineated catchment / DISV
# active area.
_X_OUTLET = 265611.933
_Y_OUTLET = 6784182.776
_PROJECT_CRS = "EPSG:2154"
_LAKE_ID = "lac0"
# Initial lake stage; chosen near the committed DEM elevation at the outlet
# (~102 m) so the lake stage and the synthetic abacus below sit on the real
# terrain. The abacus stages bracket it.
_STAGE_INIT_M = 101.0

# Committed regional DEM (absolute path so the generated TOML does not depend on
# a relative anchor that breaks when the config lives in tmp_path).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEM_PATH = _REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"


def _write_lake_geometry_fixture(data_dir: Path) -> Path:
    """Write a tiny rectangular lake polygon (~200 m box) at the outlet.

    The polygon is in the project CRS (EPSG:2154) so GridIntersect needs no
    reprojection, and is sized to span a few cells of the small DISV grid.
    """
    geom_dir = data_dir / "lake_geometry"
    geom_dir.mkdir(parents=True, exist_ok=True)
    path = geom_dir / "lac0.gpkg"
    half = 100.0
    polygon = box(
        _X_OUTLET - half,
        _Y_OUTLET - half,
        _X_OUTLET + half,
        _Y_OUTLET + half,
    )
    gdf = gpd.GeoDataFrame(
        {"lake_id": [_LAKE_ID]},
        geometry=[polygon],
        crs=_PROJECT_CRS,
    )
    gdf.to_file(str(path), driver="GPKG")
    return path


def _write_lake_abacus_fixture(data_dir: Path) -> Path:
    """Write a minimal monotonic stage-volume-area abacus CSV.

    The stage column brackets ``_STAGE_INIT_M`` (101 m) and spans the committed
    DEM elevation around the outlet (~100-106 m) so the lake's initial stage and
    its equilibrium stage both map onto a valid abacus row.
    """
    abacus_dir = data_dir / "lake_abacus"
    abacus_dir.mkdir(parents=True, exist_ok=True)
    path = abacus_dir / "lac0.csv"
    path.write_text(
        "stage,volume,sarea\n"
        "98.0,0.0,0.0\n"
        "101.0,4.0e4,2.0e4\n"
        "104.0,1.0e5,2.5e4\n"
        "108.0,2.0e5,3.0e4\n",
        encoding="utf-8",
    )
    return path


_RECHARGE_DATA_TOML = """\
[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "synthetic"
values = [2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0]
freq = "MS"
runoff_ratio = 0.1
"""


def _config_body(*, active_bc: list[str], flow_extra: str, data_toml: str) -> str:
    """Return the self-contained project TOML for the given lake declaration.

    Self-contained (no ``base_config``) so the run does not inherit the committed
    fixtures' relative well / oceanic paths, which would break when the config
    lives in tmp_path. ``active_bc`` and any lake-specific ``flow.*`` subtables
    are injected into the single ``[flow]`` table (TOML forbids declaring it
    twice). Uses one aligned 30-day period and a small 30x30 / 1-layer DISV grid
    to keep the mf6 run fast; ``keep_solver_files`` retains ``.solver_scratch`` so
    the LAK package file can be asserted on disk.
    """
    active_bc_toml = ", ".join(f'"{name}"' for name in active_bc)
    return f"""\
[workflow]
mode = "simulation"

[workspace]
project_root = "."

[geographic]
crs_project = "{_PROJECT_CRS}"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{_DEM_PATH}"
x_outlet = {_X_OUTLET}
y_outlet = {_Y_OUTLET}
snap_dist = "50 m"
buff_area = "20%"

[domain]
[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[simulation]
name = "lake e2e"

[simulation.results]
keep_solver_files = true

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-30 00:00:00"
step_value = "30 day"
coverage_policy = "warn"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "transient"
active_sinks_sources = ["recharge"]
active_bc = [{active_bc_toml}]
param_list = ["K", "Ss", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-5 m/s"

[flow.param.Ss.field]
kind = "homogeneous"
value = "1e-10 m-1"

[flow.param.Sy.field]
kind = "homogeneous"
value = "0.02 -"

[flow.ic]
type = "top"

[flow.bc.cauchy.drainage]
application_domain = "top"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"
{flow_extra}
{data_toml}
[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 30
ny = 30

[modflow6.sgrid.vertical]
nlay = 2

[display]
show = false
"""


def _write_lake_config(
    config_path: Path,
    *,
    geometry_path: Path,
    abacus_path: Path,
) -> None:
    """Write the lake project TOML: a drainage outlet plus a config-declared lake.

    ``active_bc`` carries ``lake`` (-> MF6 LAK, modflow6-only) and ``drainage`` (a
    seepage outlet that lets the flow model converge). The lake carries a WEIR
    spillway outlet so its stage is capped near the surrounding terrain. The lake
    reaches the build only through the CUSTOM lake_geometry / lake_abacus data
    sources and the ``flow.sinks_sources.lakes`` payload, so the whole data layer
    is on the path.
    """
    flow_extra = f"""
[flow.sinks_sources.lakes.{_LAKE_ID}]
bedleak = 0.1
stageinit = "{_STAGE_INIT_M} m"

[[flow.sinks_sources.lakes.{_LAKE_ID}.outlets]]
couttype = "WEIR"
invert = "104.0 m"
width = "5.0 m"
lakeout = 0
"""
    data_toml = (
        _RECHARGE_DATA_TOML
        + f"""
[[data.lake_geometry.sources]]
source = "custom"
path = "{geometry_path}"

[[data.lake_abacus.sources]]
source = "custom"
path = "{abacus_path}"
lake_id = "{_LAKE_ID}"
"""
    )
    config_path.write_text(
        _config_body(
            active_bc=["lake", "drainage"],
            flow_extra=flow_extra,
            data_toml=data_toml,
        ),
        encoding="utf-8",
    )


def _write_no_lake_config(config_path: Path) -> None:
    """Write the SAME base config without a lake (drainage only, no LAK)."""
    config_path.write_text(
        _config_body(
            active_bc=["drainage"],
            flow_extra="",
            data_toml=_RECHARGE_DATA_TOML,
        ),
        encoding="utf-8",
    )


def _find_lak_artifacts(model_ws: Path) -> tuple[list[Path], list[Path]]:
    """Return the written ``*.lak`` packages and laktab artifacts in the workspace."""
    lak_files = sorted(model_ws.glob("*.lak"))
    laktab_files = sorted(model_ws.glob("*.laktab")) + sorted(model_ws.glob("*laktab*"))
    return lak_files, laktab_files


def _assert_planner_infers_lake_families(config_path: Path) -> None:
    """INTEGRITY: the config-declared lake reaches the data-layer planner.

    Builds the SAME DataLoadPlan the production loader uses and asserts the lake
    families are inferred from ``flow.active_bc`` containing ``lake``. This proves
    the lake flows through the data layer rather than being bypassed; it is pure
    config logic (no solver, no network) so it is a stable integrity gate even
    while the loader / binder are unported.
    """
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.data.planner import DataPlanner

    cfg = HydroModPyConfig.from_toml(config_path)
    plan = DataPlanner().build(cfg.data, flow_active_bc=cfg.flow.active_bc)
    assert "lake_geometry" in plan.types, (
        f"planner did not infer lake_geometry from active_bc={cfg.flow.active_bc}; "
        f"plan types: {plan.types}"
    )
    assert "lake_abacus" in plan.types, (
        f"planner did not infer lake_abacus from active_bc={cfg.flow.active_bc}; "
        f"plan types: {plan.types}"
    )


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_lake_project_e2e_builds_lak_and_extracts_stage(tmp_path: Path) -> None:
    """A config-declared lake drives the LAK build + a lake stage series via mf6.

    The config-declared lake reaches the data layer (lake_geometry polygon +
    lake_abacus table), the data -> flow binders attach the polygon / abacus onto
    the flow lake payload, and the LAK package fires: a ``*.lak`` file and laktab
    are written and a finite ``lake:<id>`` stage / exchange series is extracted.
    """
    # Gate on the mf6 binary; skip (not fail) when it is absent.
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    out_path = tmp_path / "lake_run"
    out_path.mkdir(parents=True, exist_ok=True)
    data_dir = out_path / "data"

    geometry_path = _write_lake_geometry_fixture(data_dir)
    abacus_path = _write_lake_abacus_fixture(data_dir)

    config_path = out_path / "run_lake_e2e.toml"
    _write_lake_config(
        config_path,
        geometry_path=geometry_path,
        abacus_path=abacus_path,
    )

    # INTEGRITY: the lake reaches the data-layer planner (config -> data plan).
    _assert_planner_infers_lake_families(config_path)

    # Run the real production pipeline (same standard_steps Pipeline as hmp run).
    run_hmp_cli(config_path=config_path, out_path=out_path, timeout=1800)

    # PRIMARY: the LAK package was actually built and written for the run.
    model_ws, _, _ = resolve_model_workspace(out_path)
    lak_files, laktab_files = _find_lak_artifacts(model_ws)
    assert lak_files, (
        f"No *.lak package written under {model_ws}: the config-declared lake did "
        "not reach the LAK build."
    )
    assert laktab_files, f"No laktab written under {model_ws}: the abacus did not reach LAK."

    # SECONDARY: the lake produced a finite stage series near stageinit, proving
    # the lake actually ran. Lake series land under the ``lake:<id>`` station id.
    store = _open_result_store(out_path)
    try:
        sim_id = _resolve_sim_id(store)
        stage = store.query_timeseries(sim_id, f"lake:{_LAKE_ID}", "stage")
        assert not stage.empty, "lake stage series is empty"
        last_stage = float(stage.iloc[-1])
        assert last_stage == last_stage, "lake stage is NaN"  # NaN-check
        assert 98.0 < last_stage < 108.0, (
            f"lake stage {last_stage} not in the abacus bracket near stageinit {_STAGE_INIT_M}"
        )
        # The lake-aquifer exchange must also be extracted for the lake id.
        exchange = store.query_timeseries(sim_id, f"lake:{_LAKE_ID}", "gwf_exchange")
        assert not exchange.empty, "lake-aquifer exchange series is empty"
    finally:
        store.close()


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_lake_project_e2e_negative_control_no_lake_no_lak(tmp_path: Path) -> None:
    """The SAME base config without a lake produces NO LAK file.

    Confirms the LAK presence asserted by the primary test is driven by the
    config-declared lake, not incidental to the fixture / grid. This control does
    not depend on the missing binder, so it runs for real (no xfail).
    """
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    out_path = tmp_path / "no_lake_run"
    out_path.mkdir(parents=True, exist_ok=True)

    config_path = out_path / "run_no_lake_e2e.toml"
    _write_no_lake_config(config_path)

    run_hmp_cli(config_path=config_path, out_path=out_path, timeout=1800)

    model_ws, _, _ = resolve_model_workspace(out_path)
    lak_files, _ = _find_lak_artifacts(model_ws)
    assert not lak_files, (
        f"Unexpected *.lak package {lak_files} written for a config without a lake "
        "in active_bc: LAK presence must be config-driven."
    )
