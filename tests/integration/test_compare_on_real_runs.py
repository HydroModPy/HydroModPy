"""``hmp diff`` on real runs of a small island, under real solvers.

The unit tests answer through a fake run. These prove that a sealed run answers
the way the comparison expects, on a steady run and a transient one, under
MODFLOW 6 and Boussinesq, on one mesh and on two.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.cli.main import main as hmp_main
from tests._helpers.island_project import island_toml, run_island

pytestmark = [
    pytest.mark.integration,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]

TRIANGLES = '\n[mesh]\nengine = "triangle"\ncell_size = 20.0\n'
STORAGE = """
[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5
"""
ONE_DAY = 'end_datetime = "2003-01-02 00:00:00"\nstep_value = "1 day"\n'


def _transient(step: str) -> tuple[tuple[str, str], ...]:
    return (
        ('flow_regime = "steady"', 'flow_regime = "transient"'),
        ('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]'),
        (ONE_DAY, f'end_datetime = "2003-03-31 00:00:00"\nstep_value = "1 {step}"\n'),
    )


def _solve(
    root: Path, name: str, *, solver: str = "modflow6", mesh: str = "", step: str = ""
) -> Path:
    text = island_toml(name).replace('solvers = ["modflow6"]', f'solvers = ["{solver}"]')
    for old, new in _transient(step) if step else ():
        assert old in text, old
        text = text.replace(old, new)
    project = root / name
    project.mkdir()
    config = project / "project.toml"
    config.write_text(text + mesh + (STORAGE if step else ""), encoding="utf-8")
    run_island(config)
    return project / "runs" / name


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("island")
    triangles = {"mesh": TRIANGLES}
    return {
        "grid": _solve(root, "grid"),
        "mf6": _solve(root, "mf6", **triangles),
        "bouss": _solve(root, "bouss", solver="boussinesq", **triangles),
        "daily": _solve(root, "daily", step="day", **triangles),
        "monthly": _solve(root, "monthly", step="month", **triangles),
    }


def _compare(runs: dict[str, Path], first: str, second: str, out: Path) -> dict[str, pd.DataFrame]:
    hmp_main(["diff", str(runs[first]), str(runs[second]), "--to", str(out)])
    assert (out / "README.md").is_file()
    names = ("budget", "series", "maps")
    return {name: pd.read_csv(out / f"{name}.csv") for name in names}


def test_two_solvers_on_one_mesh_compare_and_close_their_budgets(runs, tmp_path: Path) -> None:
    tables = _compare(runs, "mf6", "bouss", tmp_path)
    head = tables["maps"].query("variable == 'watertable_elevation'").iloc[0]
    assert head["same_mesh"]
    assert head["date"] == "steady"
    assert head["n"] == 918
    assert 0.0 < head["rmse"] < 0.2
    budget = tables["budget"].query("term == 'residual' and zone == 'domain'")
    assert budget["m3_s"].abs().max() < 1e-6
    recharge = tables["budget"].query("term == 'recharge'")["m3_s"]
    assert recharge.iloc[0] == pytest.approx(recharge.iloc[1])


def test_another_mesh_is_read_at_its_nearest_cells(runs, tmp_path: Path) -> None:
    head = _compare(runs, "grid", "mf6", tmp_path)["maps"].iloc[0]
    assert not head["same_mesh"]
    assert head["n"] > 900
    assert head["rmse"] < 0.5


def test_a_daily_and_a_monthly_run_of_a_steady_recharge_agree_on_the_months(
    runs, tmp_path: Path
) -> None:
    tables = _compare(runs, "daily", "monthly", tmp_path)
    series = tables["series"].iloc[0]
    assert series["n"] == 3
    assert series["last"] == "2003-04-01 00:00:00"
    assert series["rmse"] < 1e-6 * series["reference_mean"] + 1e-9
    assert tables["maps"].iloc[0]["rmse"] < 1e-3
    assert (tmp_path / "discharge_catchment.png").is_file()


def test_a_steady_and_a_transient_run_are_refused(runs, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as refused:
        hmp_main(["diff", str(runs["mf6"]), str(runs["daily"]), "--to", str(tmp_path)])
    assert refused.value.code != 0
