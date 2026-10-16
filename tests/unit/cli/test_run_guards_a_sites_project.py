"""``hmp run`` and ``hmp calibrate`` on a ``[sites]`` project, and on one ``[site]``.

A ``[sites]`` project is a plan of cases. ``hmp run --dry-run`` prints the plan
and writes nothing; ``hmp run`` writes the plan and launches it, one worker per
case (:mod:`hydromodpy.project.launch`). A case of a written plan refuses the
``HMP_SET_*`` overrides: the plan rendered them, and the hash of the case is the
hash of the plan. A one-site project whose ``[site] name`` the workspace
catalog knows under another outlet is refused before anything runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CASES_FAILED, EXIT_CONFIG, EXIT_USAGE
from hydromodpy.config.sites.expansion import expand_plan
from hydromodpy.config.sites.plan import write_plan_draft
from hydromodpy.core.site import SiteRow
from hydromodpy.data.sites.catalog import write_catalog
from tests._helpers.cli_runner import CliRunner
from tests.unit.project._launch_fakes import (
    fake_worker,  # noqa: F401 - fixture
    write_behaviour,
)

_COMMON = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
snap_dist = "150 m"
buff_area = "10%"
{outlet}
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]
active_bc = ["drainage"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5
"""

_SITES = """
[sites]
table = "sites.csv"

[sites.recipes]
base = "project.toml"
k2e_5 = { file = "project.toml", set = { "flow.param.K.field.value" = 2e-5 } }

[sites.bind]
"site.name" = "site"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
"""


def _sites_project(tmp_path: Path) -> Path:
    project = tmp_path / "campaign"
    (project / "data").mkdir(parents=True)
    (project / "dem.tif").write_bytes(b"never read by the plan")
    (project / "project.toml").write_text(_COMMON.format(outlet="") + _SITES, encoding="utf-8")
    (project / "sites.csv").write_text(
        "site,x_outlet,y_outlet\nalpha,389285.9,6816518.7\nbeta,377120.0,6831410.0\n",
        encoding="utf-8",
    )
    return project


def _recipe(project: Path) -> Path:
    path = project / "dry.toml"
    path.write_text(
        'base_config = "project.toml"\n\n[calibration]\nmethod = "grid"\n', encoding="utf-8"
    )
    return path


def test_a_dry_run_prints_the_plan_and_writes_nothing(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)
    before = sorted(path.name for path in project.iterdir())

    result = CliRunner().invoke(["run", str(project / "project.toml"), "--dry-run", "-q"])

    assert result.exit_code == 0, result.stderr
    assert "4 cases (2 sites x 2 recipes)" in result.stdout
    assert "alpha-k2e_5" in result.stdout
    assert sorted(path.name for path in project.iterdir()) == before


@pytest.mark.allow_subprocess
@pytest.mark.usefixtures("fake_worker")
def test_a_run_without_dry_run_plans_and_launches_every_case(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)
    write_behaviour(project, {"beta-k2e_5": {"run": "fail"}})

    result = CliRunner().invoke(["run", str(project / "project.toml"), "-q", "--parallel", "2"])

    assert result.exit_code == EXIT_CASES_FAILED, result.stderr
    assert "4 case(s) started, 3 completed, 1 not completed" in result.stdout
    assert "beta-k2e_5: failed (SolverError: boom)" in result.stderr
    assert (project / "plan" / "current").is_file()
    assert sorted(path.name for path in (project / "runs").iterdir()) == [
        "alpha-base",
        "alpha-k2e_5",
        "beta-base",
        "beta-k2e_5",
    ]
    assert len(list((project / "jobs").glob("*-local/journal.jsonl"))) == 1


@pytest.mark.allow_subprocess
@pytest.mark.usefixtures("fake_worker")
def test_until_data_on_a_sites_project_stops_after_the_prepare_phase(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(["run", str(project / "project.toml"), "-q", "--until", "data"])

    assert result.exit_code == 0, result.stderr
    assert not (project / "runs").exists()


def test_resume_takes_no_case_name_on_a_sites_project(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(
        ["run", str(project / "project.toml"), "-q", "--resume", "alpha-base"]
    )

    assert result.exit_code == EXIT_USAGE
    assert "--only" in result.stderr
    assert not (project / "plan").exists()


def test_a_set_override_reaches_every_case_of_the_dry_run(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(
        [
            "run",
            str(project / "project.toml"),
            "--dry-run",
            "-q",
            "--set",
            "flow.param.K.field.value=not_a_number",
        ]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "4 cases: " in result.stderr


def test_a_case_of_a_written_plan_refuses_an_env_override(tmp_path: Path, monkeypatch) -> None:
    project = _sites_project(tmp_path)
    plan_dir = write_plan_draft(project, expand_plan(project, project / "project.toml"))
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-6")

    result = CliRunner().invoke(["run", str(plan_dir / "alpha-base.toml"), "--dry-run", "-q"])

    assert result.exit_code == EXIT_CONFIG
    assert "HMP_SET_flow__param__K__field__value set while running a case of a plan" in (
        result.stderr
    )


def test_hmp_calibrate_refuses_a_recipe_of_a_sites_project(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(["calibrate", str(_recipe(project)), "-q"])

    assert result.exit_code == EXIT_CONFIG
    assert "hmp run dry.toml runs this recipe on every site" in result.stderr


def test_a_site_the_catalog_knows_elsewhere_is_refused_before_the_run(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    project = workspace / "projects" / "one"
    (project / "data").mkdir(parents=True)
    (project / "dem.tif").write_bytes(b"never read")
    (project / "project.toml").write_text("", encoding="utf-8")
    run_toml = project / "run.toml"
    run_toml.write_text(
        '[site]\nname = "alpha"\n\n'
        + _COMMON.format(outlet="x_outlet = 300000.0\ny_outlet = 6900000.0\n").replace(
            'data_dir = "data"', f'data_dir = "data"\nroot = "{workspace.as_posix()}"'
        ),
        encoding="utf-8",
    )
    write_catalog(
        workspace,
        [SiteRow(site="alpha", x_outlet=389285.9, y_outlet=6816518.7, crs="EPSG:2154")],
    )

    result = CliRunner().invoke(["run", str(run_toml), "-q"])

    assert result.exit_code == EXIT_CONFIG, result.stderr
    assert "'alpha' is declared in the site catalog" in result.stderr
    assert not (project / "runs").exists()
