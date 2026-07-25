"""End-to-end: the reservoir fed by its catchment streamflow stops draining.

This is the executable acceptance criterion for the SFR integration, the
synthetic compressed equivalent of the Cheze reservoir failure (the legacy MF6
model lost its lake because the catchment baseflow left through DRN; observed
84.5-87.6 m NGF vs simulated 83 -> 59 m). The fixture is a committed V-shaped
tilted valley (``tests/data/sfr_cheze/``) whose dendritic stream network drains
into a small reservoir at the valley foot.

The run goes through the REAL production pipeline (``hmp run``):

    config TOML -> geographic preprocessing (whitebox D8, river network with
    stream links + Strahler) -> SFR trace delineation + binder -> data layer
    (synthetic recharge, CUSTOM lake_geometry / lake_abacus) -> flow build
    (LAK + SFR + DRN de-confliction + MVR) -> real mf6 -> store extraction.

Acceptance is numeric and two-sided:

* WITH SFR: the lake holds a band around its spillway-controlled equilibrium
  (committed golden chronicle): min stage above the floor, >= 90 % of steps
  inside [golden_min - 0.5, golden_max + 0.5], RMSE vs golden < 1.0 m, NSE vs
  golden above the pinned value, lake ``from_mvr`` > 0 (the catchment streamflow
  actually arrives), budget closure;
* WITHOUT SFR (negative control, same config minus the sfr boundary): the lake
  ends LOWER, the draining regime the SFR feed fixes.

Tolerances: row 47 of ``tests/TOLERANCES.md``.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    _open_result_store,
    _resolve_sim_id,
    assert_required_executables,
    run_hmp_cli,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "data" / "sfr_cheze"
_DEM_PATH = _FIXTURE_DIR / "dem_valley.tif"
_GEOMETRY_PATH = _FIXTURE_DIR / "lake_geometry.gpkg"
_ABACUS_PATH = _FIXTURE_DIR / "lake_abacus.csv"
_GOLDEN_STAGE_CSV = _FIXTURE_DIR / "golden_stage.csv"

_PROJECT_CRS = "EPSG:2154"
_LAKE_ID = "res0"
_X_OUTLET = 300037.5
_Y_OUTLET = 6701262.5
_STAGE_INIT_M = 93.0
_SPILLWAY_INVERT_M = 94.0

# tests/TOLERANCES.md row 47: synthetic Cheze acceptance bands.
_MIN_STAGE_FLOOR_M = 92.0
_BAND_MARGIN_M = 0.5
_BAND_COVERAGE = 0.90
_RMSE_MAX_M = 1.0
_NSE_MIN = 0.90
# NSE degenerates when the golden chronicle is flat (spillway-held level, mm
# variance); the gate then switches to a STRICTER max-abs error.
_FLAT_GOLDEN_VARIANCE_M2 = 1e-4
_MAX_ABS_ERROR_FLAT_M = 0.10
_BUDGET_PERCENT_DISCREPANCY = 1.0
_CONTROL_DRAWDOWN_MARGIN_M = 0.1


def _config_body(*, with_sfr: bool) -> str:
    active_bc = '"lake", "sfr", "drainage"' if with_sfr else '"lake", "drainage"'
    sfr_toml = """
[flow.sinks_sources.sfr.net0]
stream_threshold_km2 = 0.1
streambed_k = 1e-5
streambed_k_unit = "m/s"
streambed_thickness = "1 m"
manning = 0.035
outflow_to_lake = 1
# Scaled to this compressed fixture (2.5 km DEM, 82.5 m mesh cells): the dam
# sits AT the catchment outlet, so the terminal feeder reach stops ~200 m from
# it. The 1000 m default would read that feeder as the below-dam discharge
# reach and route its flow out of the model instead of into the reservoir.
outlet_keepout = "100 m"

# The routed surface runoff entering the network (distributed per reach by
# length); the catchment baseflow adds to it through the streambed exchange.
[flow.sinks_sources.sfr.net0.runoff]
kind = "constant"
value = 0.002
units = "m3/s"

[flow.sinks_sources.sfr.net0.width]
kind = "constant"
value = "2 m"
"""
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
snap_dist = "60 m"
buff_area = "10%"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1
compute_stream_links = true
compute_strahler_order = true

[domain]
[domain.depth_model]
kind = "constant_thickness"
thickness = "30.0 m"

[simulation]
name = "sfr cheze e2e"

[simulation.results]
keep_solver_files = true

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-12-26 00:00:00"
step_value = "30 day"
coverage_policy = "warn"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "transient"
active_sinks_sources = ["recharge"]
active_bc = [{active_bc}]
param_list = ["K", "Ss", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-5 m/s"

[flow.param.Ss.field]
kind = "homogeneous"
value = "1e-6 m-1"

[flow.param.Sy.field]
kind = "homogeneous"
value = "0.05 -"

[flow.ic]
type = "top"

[flow.bc.cauchy.drainage]
application_domain = "top"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[flow.sinks_sources.lakes.{_LAKE_ID}]
bedleak = 1e-10
bedleak_unit = "1/s"
stageinit = "{_STAGE_INIT_M} m"

# The managed withdrawal that empties the reservoir unless the catchment
# streamflow feeds it (the Cheze regime: supply abstraction vs river inflow).
[flow.sinks_sources.lakes.{_LAKE_ID}.withdrawal]
kind = "constant"
value = 0.0004
units = "m3/s"

[[flow.sinks_sources.lakes.{_LAKE_ID}.outlets]]
couttype = "WEIR"
invert = "{_SPILLWAY_INVERT_M} m"
width = "5.0 m"
lakeout = 0
{sfr_toml if with_sfr else ""}
[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "synthetic"
values = [2.0, 2.0, 2.0, 1.5, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0, 1.5, 2.0]
freq = "MS"
runoff_ratio = 0.0

[[data.lake_geometry.sources]]
source = "custom"
path = "{_GEOMETRY_PATH}"

[[data.lake_abacus.sources]]
source = "custom"
path = "{_ABACUS_PATH}"
lake_id = "{_LAKE_ID}"

[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 30
ny = 30

[modflow6.sgrid.vertical]
nlay = 2

[display]
show = false
"""


def _run_and_read_stage(tmp_path: Path, *, with_sfr: bool, tag: str):
    out_path = tmp_path / tag
    out_path.mkdir(parents=True, exist_ok=True)
    config_path = out_path / f"run_{tag}.toml"
    config_path.write_text(_config_body(with_sfr=with_sfr), encoding="utf-8")
    run_hmp_cli(config_path=config_path, out_path=out_path, timeout=2400)

    store = _open_result_store(out_path)
    try:
        sim_id = _resolve_sim_id(store)
        stage = store.query_timeseries(sim_id, f"lake:{_LAKE_ID}", "stage")
        from_mvr = None
        if with_sfr:
            from_mvr = store.query_timeseries(sim_id, f"lake:{_LAKE_ID}", "from_mvr")
    finally:
        store.close()
    return out_path, stage, from_mvr


def _golden_stage() -> list[float]:
    with _GOLDEN_STAGE_CSV.open(encoding="utf-8") as fh:
        return [float(row["stage"]) for row in csv.DictReader(fh)]


def _nse(sim: list[float], obs: list[float]) -> float:
    mean_obs = sum(obs) / len(obs)
    denom = sum((o - mean_obs) ** 2 for o in obs)
    num = sum((s - o) ** 2 for s, o in zip(sim, obs, strict=True))
    if denom == 0.0:
        return float("-inf") if num > 0 else 1.0
    return 1.0 - num / denom


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_sfr_fed_reservoir_holds_its_level_and_control_drains(tmp_path: Path) -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    out_path, stage, from_mvr = _run_and_read_stage(tmp_path, with_sfr=True, tag="with_sfr")

    # The SFR package was actually built and written for the run.
    solver_dirs = list(out_path.rglob("*.sfr"))
    assert solver_dirs, f"no *.sfr package written under {out_path}"

    sim = [float(v) for v in stage.values]
    assert sim, "lake stage series is empty"
    assert all(math.isfinite(v) for v in sim)

    golden = _golden_stage()
    assert len(golden) == len(sim), (
        f"golden chronicle has {len(golden)} steps, run produced {len(sim)}; regenerate "
        f"{_GOLDEN_STAGE_CSV} if the fixture window changed."
    )

    # HARD GATES (TOLERANCES row 47). A lake pinned at its bottom must FAIL.
    assert min(sim) > _MIN_STAGE_FLOOR_M, f"reservoir drained: min stage {min(sim):.2f} m"
    lo = min(golden) - _BAND_MARGIN_M
    hi = max(golden) + _BAND_MARGIN_M
    coverage = sum(1 for v in sim if lo <= v <= hi) / len(sim)
    assert coverage >= _BAND_COVERAGE, f"stage in band [{lo:.2f}, {hi:.2f}] only {coverage:.0%}"
    rmse = math.sqrt(sum((s - o) ** 2 for s, o in zip(sim, golden, strict=True)) / len(sim))
    assert rmse < _RMSE_MAX_M, f"RMSE vs golden {rmse:.3f} m"
    mean_golden = sum(golden) / len(golden)
    golden_variance = sum((o - mean_golden) ** 2 for o in golden) / len(golden)
    if golden_variance < _FLAT_GOLDEN_VARIANCE_M2:
        max_abs = max(abs(s - o) for s, o in zip(sim, golden, strict=True))
        assert max_abs < _MAX_ABS_ERROR_FLAT_M, f"max |sim-golden| {max_abs:.3f} m"
    else:
        assert _nse(sim, golden) > _NSE_MIN, f"NSE vs golden {_nse(sim, golden):.3f}"

    # The catchment streamflow actually feeds the lake through MVR.
    assert from_mvr is not None and not from_mvr.empty
    assert max(float(v) for v in from_mvr.values) > 0.0, "lake never received MVR inflow"

    # The GWF budget closes on the real solver listing.
    from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy

    scratch_dirs = [path.parent for path in out_path.rglob("*.lst") if path.name != "mfsim.lst"]
    assert scratch_dirs, "solver listing not kept; set keep_solver_files"
    discrepancy = _last_percent_discrepancy(scratch_dirs[0])
    assert discrepancy is not None
    assert abs(discrepancy) <= _BUDGET_PERCENT_DISCREPANCY

    # Produce the golden-vs-sim figure next to the run outputs.
    figure_path = _plot_sim_vs_golden(out_path, sim=sim, golden=golden)
    assert figure_path.is_file() and figure_path.stat().st_size > 4096

    # NEGATIVE CONTROL: the same model without SFR drains (the regime the SFR
    # feed fixes); the gap is the water that used to leave through DRN.
    _, control_stage, _ = _run_and_read_stage(tmp_path, with_sfr=False, tag="no_sfr")
    control = [float(v) for v in control_stage.values]
    assert control[-1] < sim[-1] - _CONTROL_DRAWDOWN_MARGIN_M, (
        f"control (no SFR) final stage {control[-1]:.2f} m is not below the SFR-fed "
        f"final stage {sim[-1]:.2f} m by {_CONTROL_DRAWDOWN_MARGIN_M} m; the fixture "
        "no longer discriminates."
    )
    # The control declines monotonically: the withdrawal empties it.
    assert all(b <= a for a, b in zip(control, control[1:], strict=False))


def _plot_sim_vs_golden(out_path: Path, *, sim: list[float], golden: list[float]) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(range(len(golden)), golden, "k--", label="golden (observed equivalent)")
    ax.plot(range(len(sim)), sim, "b-", label="simulated stage")
    ax.set_xlabel("stress period")
    ax.set_ylabel("reservoir stage [m]")
    ax.set_title("SFR-fed reservoir stage vs golden chronicle")
    ax.legend()
    figure_path = out_path / "sfr_cheze_stage_vs_golden.png"
    fig.savefig(figure_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return figure_path
