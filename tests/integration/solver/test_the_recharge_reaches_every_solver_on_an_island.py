"""What the recharge audit found, replayed on a small island under real solvers.

A series with a negative rate stopped MODFLOW 6 on a missing attribute. A wide sea
stayed free under Boussinesq, so the water table sat on the sea bed. The line search
of its Newton stalled on one cell at the land surface. MODPATH divided by a zero porosity and read a drain term
the model did not have.
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
CENTRE_M = 305.0
MM_DAY = 1e-3 / 86400.0
MONTHLY_TIME = """\
start_datetime = "2003-01-01"
end_datetime = "2003-12-31"
step_value = "1 month"
coverage_policy = "ignore"
"""
LIST_WITH_A_DEFICIT = "[1.0, 1.5, 1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.0, 1.0, 1.5, 2.0]"


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
    table = table[table["zone_id"].astype(str) == "0"]
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
    table = table[table["zone_id"].astype(str) == "0"]
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


def test_modpath_runs_without_drains_on_a_grid_that_is_not_the_dem(tmp_path: Path) -> None:
    root = tmp_path / "particles"
    config = _project(
        root,
        "particles",
        solver="modflow_nwt",
        replacements=(
            ('active_bc = ["ocean", "drainage"]', 'active_bc = ["ocean"]'),
            ('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]'),
            (
                '[[simulation.process]]\nid = "flow_main"\ntype = "flow"\n'
                'solvers = ["modflow_nwt"]\n',
                '[[simulation.process]]\nid = "flow_main"\ntype = "flow"\n'
                'solvers = ["modflow_nwt"]\n\n[[simulation.process]]\n'
                'id = "transport_main"\ntype = "transport"\nsolvers = ["modpath"]\n',
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
