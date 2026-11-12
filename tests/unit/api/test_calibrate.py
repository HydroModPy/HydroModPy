"""``api.calibrate`` and ``Project.calibrate`` send a calibration to the right runner.

A configuration with ``[[calibration.phases]]`` is never flattened into one calibration.
It goes to the staged runner, or the call is refused. Runners are replaced by recorders.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import CalibrationError, ConfigError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project import api
from hydromodpy.project.calibrate import CalibrationPlan
from hydromodpy.project.dispatch.workflow import dispatch_workflow
from hydromodpy.project.facade import Project
from hydromodpy.project.request import request_of

pytestmark = pytest.mark.fast

STAGED_TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "grid"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]

[[calibration.phases]]
name = "steady_k"
description = "zero of the signed gap"
method = "bisection"
parameters = ["K"]
"""

# Same as STAGED_TOML with an unknown key in [calibration].
TYPO_TOML = STAGED_TOML.replace('method = "grid"\n', 'method = "grid"\nnot_a_field = 3\n')

MONO_PHASE_TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "grid"
"""

MINIMAL_REAL_PROJECT_TOML = """\
[workflow]
mode = "simulation"

[workspace]

[site]
name = "naizin"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = ["dem"]

[[data.dem.sources]]
source = "file"
path = "inputs/naizin_dem.tif"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[flow.bc.drainage]

[simulation]
name = "minimal"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow_nwt"]

[calibration]
seed = 7

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
map.complete = "a_stream_network.gpkg"
model.neighbours = "D8"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[display]
enabled = false
"""


class FakeStagedReport:
    """Stand-in for a ``CalibrationReport``: an object, not a mapping."""

    def to_dict(self) -> dict[str, bool]:
        return {"staged": True}


def write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def staged_config() -> CalibrationConfig:
    """A validated ``[calibration]`` section declaring one phase."""
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": {"K": {"bounds": [1e-6, 1e-3], "path": "flow.param.K.field.value"}},
            "phases": [
                {
                    "name": "steady_k",
                    "description": "zero of the signed gap",
                    "method": "bisection",
                    "parameters": ["K"],
                }
            ],
        }
    )


def in_memory_project(root: Path) -> SimpleNamespace:
    """Project with no config_path: the pure Python-mode case."""
    workspace = SimpleNamespace(root=root, project_root=root)
    # A project built in memory anchors its checks where its project.toml would be.
    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=workspace), config_path=root / "project.toml"
    )
    config = SimpleNamespace(model_dump=lambda **kwargs: {"workflow": {"mode": "simulation"}})
    return SimpleNamespace(
        _config_path=None,
        _ctx=ctx,
        config=config,
        _cfg=config,
    )


def file_project() -> SimpleNamespace:
    """Project that carries no configuration of its own."""
    return SimpleNamespace(_cfg=None, _config_path=None)


def write_real_project(tmp_path: Path) -> Path:
    """A minimal loadable project, with Sy and a network output that the calls never name."""
    path = write_toml(tmp_path / "project.toml", MINIMAL_REAL_PROJECT_TOML)
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs" / "naizin_dem.tif").write_bytes(b"")
    return path


def patch_runners(monkeypatch) -> dict:
    """Record which runner a calibration entry point reaches."""
    calls: dict = {}

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["staged_path"] = Path(config_path)
        calls["staged_phase"] = phase
        calls["staged_kwargs"] = kwargs
        return FakeStagedReport()

    def fake_cli(config_path, **kwargs):
        calls["cli_path"] = Path(config_path)
        calls["cli_kwargs"] = dict(kwargs)
        return {"staged": False}

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration", fake_staged
    )
    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)
    return calls


def patch_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run",
        lambda cfg, path, **kw: {"case": path.stem},
    )


SESSIONS = [
    pytest.param({}, False, id="identical calibration given back"),
    pytest.param({"force": True}, True, id="force searches again"),
    pytest.param({"resume": True}, True, id="resume searches again"),
]


@pytest.mark.parametrize(("options", "searches"), SESSIONS)
def test_completed_session_of_a_file(monkeypatch, tmp_path, options, searches):
    config = write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    calls = patch_runners(monkeypatch)
    answered: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.identical_session_of_file",
        lambda target: answered.append(target) or "the report of the session",
    )

    result = api.calibrate(config, **options)

    assert ("cli_path" in calls) is searches
    assert result == ({"staged": False} if searches else "the report of the session")
    assert answered == ([] if searches else [config.resolve()])


@pytest.mark.parametrize("force", [False, True])
def test_completed_session_of_a_project(monkeypatch, tmp_path, force):
    calls = patch_runners(monkeypatch)
    project = in_memory_project(tmp_path)
    project._cfg.calibration = staged_config()
    project._cfg.workspace = SimpleNamespace(project_root=tmp_path)
    asked: dict = {}

    def identical(key, *, project_root, case, source, document):
        asked.update(key=key, root=project_root, case=case, source=source)
        return "the report of the session"

    monkeypatch.setattr(
        "hydromodpy.workflow.solution_key.planned_solution_key", lambda cfg, *, search: "k"
    )
    monkeypatch.setattr("hydromodpy.calibration.runners.document.identical_session", identical)

    result = Project.calibrate(project, case="calage", force=force)

    if force:
        assert asked == {} and "staged_path" in calls
    else:
        assert result == "the report of the session"
        assert asked == {"key": "k", "root": tmp_path, "case": "calage", "source": None}
        assert calls == {}


def test_headless_stops_before_cli_runner(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "calib.toml", '[workflow]\nmode = "calibration"\n')
    calls = patch_runners(monkeypatch)

    api.calibrate(config, headless=False)

    assert "headless" not in calls["cli_kwargs"]


def test_file_phases_go_to_staged_runner(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)

    result = Project.calibrate(file_project(), config_path=config)

    assert isinstance(result, FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


def test_embedded_phases_go_to_staged_runner(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)
    project = SimpleNamespace(
        _cfg=SimpleNamespace(calibration=staged_config()),
        _config_path=config,
        _environment=None,
    )

    result = Project.calibrate(project, phase="steady_k")

    assert isinstance(result, FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert calls["staged_phase"] == "steady_k"


def test_workflow_dispatch_of_phases(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)

    result = dispatch_workflow("calibration", request_of(config), base=tmp_path)

    # The testbed provider calls dict(run_calibration(...)): the dispatcher owes
    # its callers a mapping, not the report object.
    assert dict(result) == {"staged": True}
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


def test_resume_and_label_reach_the_runner(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)

    Project.calibrate(file_project(), config_path=config, resume=True, project="mine")

    assert calls["staged_kwargs"] == {
        "bounds": Bounds(),
        "project": "mine",
        "workspace": None,
        "metric_fn": None,
        "objective": None,
        "resume": True,
    }


def test_python_phases_replace_the_project_section(monkeypatch, tmp_path):
    # The project declares Sy and a network output. The call names only K, so
    # neither may be carried into the written document.
    config_path = write_real_project(tmp_path)
    calls = patch_runners(monkeypatch)

    with Project(config_path, headless=True) as project:
        project.calibrate(
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            phases=[{"name": "k_only", "parameters": ["K"], "max_trials": 5}],
        )

    written = HydroModPyConfig.from_toml(calls["staged_path"])
    assert set(written.calibration.parameters) == {"K"}
    assert set(written.calibration.outputs) == set()
    assert written.calibration.protocol is None


def test_dry_run_of_a_file(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)
    patch_dry_run(monkeypatch)

    plan = Project.calibrate(SimpleNamespace(), config_path=config, dry_run=True)

    assert plan == {"case": "staged"}
    assert "staged_path" not in calls


def test_dry_run_plan_of_the_verb(monkeypatch, tmp_path):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls = patch_runners(monkeypatch)
    patch_dry_run(monkeypatch)

    plan = api.calibrate(config, dry_run=True, preflight=False)

    assert isinstance(plan, CalibrationPlan)
    assert plan.plan == {"case": "staged"}
    assert [phase["name"] for phase in plan.phases] == ["steady_k"]
    assert "staged_path" not in calls
    with pytest.raises(CalibrationError, match="unknown phase 'nope'"):
        api.calibrate(config, dry_run=True, preflight=False, phase="nope")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(None, "needs a project built", id="no file"),
        pytest.param("a.toml", "plan", id="file"),
    ],
)
def test_dry_run_of_an_in_memory_project(monkeypatch, tmp_path, source, expected):
    monkeypatch.setattr("hydromodpy.project.calibrate._preflight_in_memory", lambda *a: None)
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run", lambda *a, **kw: "plan"
    )
    embedded = SimpleNamespace(
        _cfg=SimpleNamespace(calibration=SimpleNamespace(phases=None)),
        _config_path=None if source is None else tmp_path / source,
    )
    if source is None:
        with pytest.raises(ConfigError, match=expected):
            Project.calibrate(embedded, dry_run=True)
    else:
        assert Project.calibrate(embedded, dry_run=True) == expected


def test_protocol_builds_on_the_project_section(tmp_path):
    # K and Sy are the project's, the protocol lays its two phases over them.
    text = (
        MINIMAL_REAL_PROJECT_TOML.split("[calibration.outputs.seepage_network]")[0]
        .replace("seed = 7", 'protocol = "matching_hydrographic_network"')
        .replace('param_list = ["K"]', 'param_list = ["K", "Sy"]')
        .replace(
            'name = "minimal"',
            'name = "minimal"\n[simulation.time]\nstart_datetime = "2000-01-01"\nend_datetime = "2000-12-31"',
        )
    )
    text += (
        '\n[calibration.outputs.streams]\nsupport = "network"\nmap.complete = "a.gpkg"\n'
        '\n[flow.param.Sy.field]\nid = "Sy"\nkind = "homogeneous"\nunit = "-"\nvalue = 0.1\n'
        '\n[[data.hydrometry.sources]]\nstation_ids = ["G1"]\n'
    )
    write_toml(tmp_path / "project.toml", text)
    (tmp_path / "a.gpkg").write_bytes(b"")

    with Project(tmp_path / "project.toml", headless=True) as project:
        plan = project.calibrate(protocol="matching_hydrographic_network", dry_run=True)

    assert [(p["name"], p["parameters"]) for p in plan["phases"]] == [
        ("steady_conductivity", ["K"]),
        ("transient_storage", ["Sy"]),
    ]


FILE_REFUSALS = [
    pytest.param(TYPO_TOML, ConfigError, "not_a_field", id="unreadable file shows its error"),
    pytest.param(
        MONO_PHASE_TOML, CalibrationError, "steady_k", id="phase on a file without phases"
    ),
]


@pytest.mark.parametrize(("content", "error", "message"), FILE_REFUSALS)
def test_phase_refusals(tmp_path, content, error, message):
    config = write_toml(tmp_path / "calib.toml", content)

    with pytest.raises(error, match=message):
        api.calibrate(config, phase="steady_k")


PROJECT_REFUSALS = [
    pytest.param({"case": "other"}, "case= names the session", id="case with a file"),
    pytest.param(
        {"protocol": "matching_hydrographic_network"}, "protocol= alone", id="protocol with a file"
    ),
]


@pytest.mark.parametrize(("kwargs", "message"), PROJECT_REFUSALS)
def test_project_refusals(monkeypatch, tmp_path, kwargs, message):
    config = write_toml(tmp_path / "staged.toml", STAGED_TOML)
    patch_runners(monkeypatch)

    with pytest.raises(ConfigError, match=message):
        Project.calibrate(file_project(), config_path=config, **kwargs)


def test_unknown_argument_is_named():
    with pytest.raises(TypeError, match="'stagnation'"):
        Project.calibrate(SimpleNamespace(), parameters={"K": {}}, stagnation=3)
