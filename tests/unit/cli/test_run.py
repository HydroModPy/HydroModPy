"""``hmp run`` and ``hmp calibrate`` on a ``[sites]`` project, on one ``[site]``, and ``--resume``.

A ``[sites]`` project is a plan of cases. ``hmp run --dry-run`` prints the plan and writes
nothing. ``hmp run`` writes the plan and launches it, one worker per case. A case of a written
plan refuses the ``HMP_SET_*`` overrides, since the plan rendered them. ``--resume REF`` replays
the config frozen in the run directory: a bare name is the latest version, a versioned name is
that directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_cmd
from hydromodpy.cli.exit_codes import EXIT_CASES_FAILED, EXIT_CONFIG, EXIT_USAGE
from hydromodpy.core.site.row import SiteRow
from hydromodpy.data.sites.catalog import write_catalog
from hydromodpy.project.launch.plan import expand_plan, write_plan_draft
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt
from tests.unit.project.launch._launch_fakes import (
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
kind = "from_outlet_coord"
snap_dist = "150 m"
buff_area = "10%"
{outlet}
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.bc.drainage]
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


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)
    before = sorted(path.name for path in project.iterdir())

    result = CliRunner().invoke(["run", str(project / "project.toml"), "--dry-run", "-q"])

    assert result.exit_code == 0, result.stderr
    assert "4 cases (2 sites x 2 recipes)" in result.stdout
    assert "alpha-k2e_5" in result.stdout
    assert sorted(path.name for path in project.iterdir()) == before


def test_dry_run_refuses_a_file_that_check_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[workflow]\nmode = "simulation"\n[bogus_section]\nx = 1\n', encoding="utf-8")

    check = CliRunner().invoke(["check", str(bad), "-q"])
    dry = CliRunner().invoke(["run", str(bad), "--dry-run", "-q"])

    assert check.exit_code == dry.exit_code == EXIT_CONFIG, dry.stderr


@pytest.mark.allow_subprocess
@pytest.mark.usefixtures("fake_worker")
def test_run_launches_every_case(tmp_path: Path) -> None:
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
def test_until_data_stops_after_prepare(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(["run", str(project / "project.toml"), "-q", "--until", "data"])

    assert result.exit_code == 0, result.stderr
    assert not (project / "runs").exists()


def test_sites_resume_takes_no_case_name(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(
        ["run", str(project / "project.toml"), "-q", "--resume", "alpha-base"]
    )

    assert result.exit_code == EXIT_USAGE
    assert "--only" in result.stderr
    assert not (project / "plan").exists()


def test_set_override_reaches_every_case(tmp_path: Path) -> None:
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


def test_plan_case_refuses_env_override(tmp_path: Path, monkeypatch) -> None:
    project = _sites_project(tmp_path)
    plan_dir = write_plan_draft(project, expand_plan(project, project / "project.toml"))
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-6")

    result = CliRunner().invoke(["run", str(plan_dir / "alpha-base.toml"), "--dry-run", "-q"])

    assert result.exit_code == EXIT_CONFIG
    assert "HMP_SET_flow__param__K__field__value set while running a case of a plan" in (
        result.stderr
    )


def test_calibrate_refuses_a_sites_recipe(tmp_path: Path) -> None:
    project = _sites_project(tmp_path)

    result = CliRunner().invoke(["calibrate", str(_recipe(project)), "-q"])

    assert result.exit_code == EXIT_CONFIG
    assert "hmp run dry.toml runs this recipe on every site" in result.stderr


def test_site_known_elsewhere_is_refused(tmp_path: Path) -> None:
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


FROZEN_TOML = '[workflow]\nmode = "simulation"\n'


def _args(**kw) -> argparse.Namespace:
    base = {
        "from_step": None,
        "until_step": None,
        "no_display": True,
        "no_parallel": False,
        "dry_run": True,
        "credentials": None,
        "allow_host": [],
        "max_download_bytes": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _seed_run(
    workspace: Path, name: str, *, freeze_config: bool = True, text: str = FROZEN_TOML
) -> Path:
    make_project(workspace)
    run_dir = write_attempt(workspace, f"runs/{name}", status="failed", attempt=1)
    if freeze_config:
        (run_dir / RUN_CONFIG_FILENAME).write_text(text, encoding="utf-8")
    return run_dir


def test_resume_replays_frozen_config(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    _seed_run(workspace, "cheze_baseline")

    calls: dict = {}

    def _fake_run_toml(config_path: Path, *, args: argparse.Namespace, **_: object) -> None:
        calls["config_path"] = config_path
        calls["resume"] = args.resume

    monkeypatch.setattr(run_cmd, "_run_toml", _fake_run_toml)
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref("cheze_baseline", args=_args(resume="cheze_baseline"))

    # The run's own frozen config drives the replay, under the run's name.
    assert calls["config_path"] == workspace / "runs" / "cheze_baseline" / RUN_CONFIG_FILENAME
    assert calls["config_path"].read_text(encoding="utf-8") == FROZEN_TOML
    assert calls["resume"] == "cheze_baseline"


def test_resume_picks_the_version(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    _seed_run(workspace, "cheze_baseline", text="# v1\n" + FROZEN_TOML)
    _seed_run(workspace, "cheze_baseline.v2", text="# v2\n" + FROZEN_TOML)

    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        run_cmd,
        "_run_toml",
        lambda config_path, *, args, **_: calls.append((config_path, args.resume)),
    )
    monkeypatch.chdir(workspace)

    run_cmd._resume_from_ref("cheze_baseline", args=_args(resume="cheze_baseline"))
    run_cmd._resume_from_ref("cheze_baseline.v2", args=_args(resume="cheze_baseline.v2"))

    assert [name for _path, name in calls] == ["cheze_baseline.v2", "cheze_baseline.v2"]
    assert all(path.read_text(encoding="utf-8").startswith("# v2") for path, _name in calls)


RESUME_REFUSALS = [
    pytest.param("cheze_baseline", False, "cheze_baseline", id="no frozen config"),
    pytest.param("exists", True, "nope", id="unknown ref"),
]


@pytest.mark.parametrize(("seeded", "freeze", "ref"), RESUME_REFUSALS)
def test_resume_refusals(tmp_path, monkeypatch, seeded, freeze, ref):
    workspace = tmp_path / "ws"
    _seed_run(workspace, seeded, freeze_config=freeze)
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as exc:
        run_cmd._resume_from_ref(ref, args=_args())
    assert exc.value.code != 0


def test_run_needs_config_or_resume(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_cmd.run(_args(config=None, resume=None))
    assert exc.value.code != 0


def test_calibration_bare_resume(tmp_path, monkeypatch, capsys):
    # A launched calibration started again reopens its session instead of a new version.
    from hydromodpy.project import api
    from hydromodpy.project.dispatch import workflow as project_workflow

    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = workspace / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    monkeypatch.chdir(workspace)
    calls: list = []

    def calibrate(request, *, base, environment=None):
        calls.append((request, Path(base)))
        return {}

    monkeypatch.setitem(project_workflow.DISPATCH, "calibration", calibrate)
    monkeypatch.setattr(api, "run", lambda path, **kw: pytest.fail("hmp.run was called"))

    run_cmd._run_toml(config, args=_args(resume="", dry_run=False, verbosity="quiet"))

    ((request, base),) = calls
    assert request.resume is not None and not request.resume, "a bare --resume reaches the runner"
    assert (Path(request.source), base) == (config.resolve(), workspace.resolve())

    with pytest.raises(SystemExit) as exit_info:
        run_cmd._run_toml(config, args=_args(resume="other", dry_run=False))
    assert exit_info.value.code == EXIT_CONFIG
    assert "pass a bare --resume" in capsys.readouterr().err


def test_resume_of_a_calibration_run(tmp_path, monkeypatch, capsys) -> None:
    # Its frozen file holds one solve, so it can no longer reopen the search.
    workspace = make_project(tmp_path / "ws")
    seal_run(
        workspace,
        "case",
        calibrated_by=CalibratedBy(
            session_id="s" * 32, phase="main", trial=1, session_status="completed"
        ),
    )
    monkeypatch.setattr(run_cmd, "_run_toml", lambda *_a, **_k: pytest.fail("no replay"))
    monkeypatch.chdir(workspace)

    with pytest.raises(SystemExit) as stopped:
        run_cmd._resume_from_ref("case", args=_args(resume="case"))

    assert stopped.value.code == EXIT_CONFIG
    assert "hmp run <file>.toml --resume" in capsys.readouterr().err


def test_bare_resume_name_of_a_file(tmp_path) -> None:
    # The run of "Config Winter.toml" is "config_winter", and a bare --resume names it.
    from hydromodpy.project.request import RunRequest

    config = tmp_path / "Config Winter.toml"

    assert run_cmd._case_name(RunRequest(config={}, form="toml"), {}, config) == "config_winter"
