"""What the recharge audit found, replayed on a small island under real solvers.

A series with a negative rate stopped MODFLOW 6 on a missing attribute. A wide sea
stayed free under Boussinesq, so the water table sat on the sea bed. The line search
of its Newton stalled on one cell at the land surface. MODPATH divided by a zero porosity and read a drain term
the model did not have. A steady period took the plain mean of its periods, whatever
their lengths.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from tests._helpers.island_project import island_toml, run_island

pytestmark = [
    pytest.mark.integration,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]

K_M_S = 5e-6
BED_M = -5.0
RADIUS_M = 200.0
MM_DAY = 1e-3 / 86400.0
MONTHLY_TIME = """\
start_datetime = "2003-01-01"
end_datetime = "2003-12-31"
step_value = "1 month"
coverage_policy = "ignore"
"""
LIST_WITH_A_DEFICIT = "[1.0, 1.5, 1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.0, 1.0, 1.5, 2.0]"
THREE_MONTHS = """\
start_datetime = "2003-01-01"
end_datetime = "2003-03-31"
step_value = "1 month"
coverage_policy = "ignore"
"""
RATES_MM_DAY = [1.0, 4.0, 2.0]
TIME_MEAN_MM_DAY = (31.0 * 1.0 + 28.0 * 4.0 + 31.0 * 2.0) / 90.0


def _project(
    root: Path,
    name: str,
    *,
    solver: str = "modflow6",
    mesh: str = "",
    replacements: tuple[tuple[str, str], ...] = (),
    after: str = "",
) -> Path:
    text = island_toml(name).replace('solvers = ["modflow6"]', f'solvers = ["{solver}"]')
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    root.mkdir(parents=True)
    config = root / "project.toml"
    config.write_text(text + mesh + after, encoding="utf-8")
    return config


def _budget_last(root: Path, name: str) -> dict[str, tuple[float, float]]:
    table = pd.read_parquet(root / "runs" / name / "tables.parquet" / "budgets.parquet")
    table = table[table["zone_id"].astype(str) == "domain"]
    last = table[table["timestep"] == table["timestep"].max()]
    return {row.component: (row.flux_in, row.flux_out) for row in last.itertuples()}


def _dupuit_centre_head(rate_mm_day: float) -> float:
    return BED_M + float(np.sqrt(BED_M**2 + rate_mm_day * MM_DAY / (2.0 * K_M_S) * RADIUS_M**2))


def test_a_negative_series_reaches_evt_under_modflow6(tmp_path: Path) -> None:
    root = tmp_path / "deficit"
    config = _project(
        root,
        "deficit",
        replacements=(
            ('types = ["oceanic", "recharge"]', 'types = ["oceanic"]'),
            ('[[data.recharge.sources]]\nsource = "synthetic"\nvalues = [1.0]\n', ""),
            ('flow_regime = "steady"', 'flow_regime = "transient"'),
            ('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]'),
            (
                'start_datetime = "2003-01-01 00:00:00"\n'
                'end_datetime = "2003-01-02 00:00:00"\n'
                'step_value = "1 day"\n'
                'coverage_policy = "ignore"\n',
                MONTHLY_TIME,
            ),
            ('first_clim = "mean"', f"values = {LIST_WITH_A_DEFICIT}"),
        ),
        after="""
[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5
""",
    )

    run_island(config)

    table = pd.read_parquet(root / "runs" / "deficit" / "tables.parquet" / "budgets.parquet")
    table = table[table["zone_id"].astype(str) == "domain"]
    assert "evapotranspiration" in set(table["component"])
    recharge = table[table["component"] == "recharge"].sort_values("timestep")
    rates = recharge["flux_in"].to_numpy()
    assert np.all(rates[5:8] == 0.0)
    assert np.all(rates[[9, 10, 11]] > 0.0)


@pytest.mark.parametrize("rate_mm_day", [0.25, 5.0])
def test_a_wide_sea_holds_its_head_under_boussinesq(tmp_path: Path, rate_mm_day: float) -> None:
    root = tmp_path / "sea"
    config = _project(
        root,
        "sea",
        solver="boussinesq",
        replacements=(("values = [1.0]", f"values = [{rate_mm_day}]"),),
        mesh='\n[mesh]\nengine = "triangle"\ncell_size = 20.0\n',
    )

    run_island(config)

    fields = zarr.open_group(str(root / "runs" / "sea" / "fields.zarr"), mode="r")
    head = np.asarray(fields["head"][-1], dtype=float).reshape(-1)
    top = np.asarray(fields["mesh"]["topography"][:], dtype=float).reshape(-1)
    sea = top <= 0.0
    assert sea.sum() > 100
    assert np.abs(head[sea]).max() < 1e-9

    budget = _budget_last(root, "sea")
    total_in = sum(flux_in for flux_in, _ in budget.values())
    total_out = sum(flux_out for _, flux_out in budget.values())
    assert total_out == pytest.approx(total_in, rel=1e-5)
    if rate_mm_day < 1.0:
        assert head.max() == pytest.approx(_dupuit_centre_head(rate_mm_day), abs=0.2)


def _three_month_island(
    root: Path, name: str, *, solver: str, first_period_steady: bool, after: str = ""
) -> Path:
    mesh = '\n[mesh]\nengine = "triangle"\ncell_size = 30.0\n' if solver == "boussinesq" else ""
    return _project(
        root,
        name,
        solver=solver,
        replacements=(
            ('types = ["oceanic", "recharge"]', 'types = ["oceanic"]'),
            ('[[data.recharge.sources]]\nsource = "synthetic"\nvalues = [1.0]\n', ""),
            (
                'flow_regime = "steady"',
                f'flow_regime = "transient"\nfirst_period_steady = {str(first_period_steady).lower()}',
            ),
            ('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]'),
            (
                'start_datetime = "2003-01-01 00:00:00"\n'
                'end_datetime = "2003-01-02 00:00:00"\n'
                'step_value = "1 day"\n'
                'coverage_policy = "ignore"\n',
                THREE_MONTHS,
            ),
            ('first_clim = "mean"', f"values = {RATES_MM_DAY}"),
        ),
        mesh=mesh,
        after=f"""
[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5
{after}
""",
    )


@pytest.mark.parametrize("solver", ["modflow6", "modflow_nwt", "boussinesq"])
def test_a_steady_first_period_receives_the_time_mean(tmp_path: Path, solver: str) -> None:
    root = tmp_path / "steady"
    run_island(_three_month_island(root, "steady", solver=solver, first_period_steady=True))

    table = pd.read_parquet(root / "runs" / "steady" / "tables.parquet" / "budgets.parquet")
    table = table[table["zone_id"].astype(str) == "domain"]
    recharge = table[table["component"] == "recharge"].sort_values("timestep")
    rates = recharge["flux_in"].to_numpy(dtype=float)

    assert rates[0] / rates[1] == pytest.approx(TIME_MEAN_MM_DAY / RATES_MM_DAY[1], rel=1e-6)
    assert rates[2] / rates[1] == pytest.approx(RATES_MM_DAY[2] / RATES_MM_DAY[1], rel=1e-6)
    # Every solver closes its domain budget on the signed terms, storage included.
    net = (table["flux_in"] - table["flux_out"]).groupby(table["timestep"]).sum()
    np.testing.assert_allclose(net.to_numpy(dtype=float) / rates, 0.0, atol=1e-4)
    if solver != "boussinesq":
        # The criterion reads the own rate of each period, so the same mean again.
        fields = zarr.open_group(str(root / "runs" / "steady" / "fields.zarr"), mode="r")
        kept = fields["forcing"].attrs["criterion_mean_recharge_m_s"]
        assert kept == pytest.approx(TIME_MEAN_MM_DAY * MM_DAY, rel=1e-9)


@pytest.mark.parametrize("solver", ["modflow6", "modflow_nwt", "boussinesq"])
def test_a_steady_initial_state_stands_under_the_time_mean(tmp_path: Path, solver: str) -> None:
    def first_heads(name: str, ic: str) -> np.ndarray:
        root = tmp_path / name
        run_island(
            _three_month_island(root, name, solver=solver, first_period_steady=False, after=ic)
        )
        fields = zarr.open_group(str(root / "runs" / name / "fields.zarr"), mode="r")
        return np.asarray(fields["head"][0], dtype=float).reshape(-1)

    mean = first_heads("mean", '\n[flow.ic.h]\nkind = "steady_state"\nsource = "mean_recharge"\n')
    stated = first_heads(
        "stated",
        '\n[flow.ic.h]\nkind = "steady_state"\nsource = "prescribed"\n'
        f'rate = "{TIME_MEAN_MM_DAY!r} mm/day"\n',
    )
    plain = first_heads(
        "plain",
        '\n[flow.ic.h]\nkind = "steady_state"\nsource = "prescribed"\n'
        f'rate = "{float(np.mean(RATES_MM_DAY))!r} mm/day"\n',
    )

    assert np.nanmax(np.abs(mean - stated)) < 1e-3
    assert np.nanmax(np.abs(plain - stated)) > 5e-3


def test_modpath_runs_without_drains_on_a_grid_that_is_not_the_dem(tmp_path: Path) -> None:
    root = tmp_path / "particles"
    config = _project(
        root,
        "particles",
        solver="modflow_nwt",
        replacements=(
            ("[flow.bc.drainage]\n\n", ""),
            ('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]'),
            (
                '[[simulation.process]]\nid = "flow_main"\nkind = "flow"\n'
                'solvers = ["modflow_nwt"]\n',
                '[[simulation.process]]\nid = "flow_main"\nkind = "flow"\n'
                'solvers = ["modflow_nwt"]\n\n[[simulation.process]]\n'
                'id = "transport_main"\nkind = "transport"\nsolvers = ["modpath"]\n',
            ),
        ),
        mesh="\n[mesh]\ncell_size = 40.0\n",
        after="""
[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5
""",
    )

    # mp6 writes its log where it is launched.
    run_island(config, cwd=root)

    assert (root / "runs" / "particles" / "manifest.json").is_file()
