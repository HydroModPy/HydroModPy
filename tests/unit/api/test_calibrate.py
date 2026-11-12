"""Unit tests for the verb ``calibrate`` and for ``Project.calibrate``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.toml_io.writer import dumps as dump_toml
from hydromodpy.project import api

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("options", "searches"),
    [
        pytest.param({}, False, id="an identical calibration is given back"),
        pytest.param({"force": True}, True, id="force searches again"),
        pytest.param({"resume": True}, True, id="resume searches again"),
    ],
)
def test_calibrate_with_path_gives_back_a_completed_session(
    monkeypatch, tmp_path: Path, options: dict, searches: bool
) -> None:
    """A completed session of the case and of the same key answers ``hmp.calibrate``."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    calls: dict = {}
    _patch_runners(monkeypatch, calls)
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
def test_project_calibrate_gives_back_a_completed_session_of_its_own_section(
    monkeypatch, tmp_path: Path, force: bool
) -> None:
    """The ``[calibration]`` a project carries is answered by the session of its key."""
    from hydromodpy.project.facade import Project

    calls: dict = {}
    _patch_runners(monkeypatch, calls)
    project = _InMemoryPythonProject(tmp_path)
    project._cfg.calibration = _staged_config()
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


def test_calibrate_with_path_drops_headless_kwarg(monkeypatch, tmp_path: Path) -> None:
    """``headless`` does not reach the CLI runner on the TOML branch."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n',
    )
    captured: dict = {}

    def fake_cli(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)

    api.calibrate(config, headless=False)
    assert "headless" not in captured["kwargs"]


# ---------------------------------------------------------------------------
# Staged calibration routing
#
# A configuration declaring [[calibration.phases]] must never be flattened into
# one calibration over the union of every declared parameter. Every entry point
# either routes to the staged runner or refuses out loud.
# ---------------------------------------------------------------------------

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

TYPO_TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "grid"
not_a_field = 3

[calibration.parameters.K]
bounds = [1e-6, 1e-3]

[[calibration.phases]]
name = "steady_k"
parameters = ["K"]
"""

MONO_PHASE_TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "grid"
"""


PHASES_TOML_EQUIVALENT = """\
[workflow]
mode = "calibration"

[calibration]
seed = 42

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]
path = "flow.param.Sy.field.value"

[calibration.outputs.gauge]
support = "point"
variable = "discharge"
x = 0
y = 0
observed_values = [1.0, 2.0, 3.0]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["gauge"]

[[calibration.objective_blocks]]
name = "network"
metric = "kge"
uses_outputs = ["gauge"]

[[calibration.phases]]
name = "k_steady"
parameters = ["K"]
regime = "steady"
objective_blocks = ["hydrograph"]
max_trials = 18

[[calibration.phases]]
name = "sy_transient"
parameters = ["Sy"]
regime = "transient"
objective_blocks = { hydrograph = 99, network = 1 }
max_trials = 30
"""

PYTHON_MODE_PHASES_KWARGS = {
    "parameters": {
        "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
        "Sy": {"bounds": [5e-3, 0.35], "path": "flow.param.Sy.field.value"},
    },
    "outputs": {
        "gauge": {
            "support": "point",
            "variable": "discharge",
            "x": 0,
            "y": 0,
            "observed_values": [1.0, 2.0, 3.0],
        },
    },
    "objective_blocks": [
        {"name": "hydrograph", "metric": "nse", "uses_outputs": ["gauge"]},
        {"name": "network", "metric": "kge", "uses_outputs": ["gauge"]},
    ],
    "phases": [
        {
            "name": "k_steady",
            "parameters": ["K"],
            "regime": "steady",
            "objective_blocks": ["hydrograph"],
            "max_trials": 18,
        },
        {
            "name": "sy_transient",
            "parameters": ["Sy"],
            "regime": "transient",
            "objective_blocks": {"hydrograph": 99, "network": 1},
            "max_trials": 30,
        },
    ],
    "seed": 42,
}


class _InMemoryPythonProject:
    """Duck-typed project with no config_path: the pure Python-mode case.

    Exposes only what :func:`run_calibration_programmatic` reads: the
    workspace root (for ``sessions/``) and a config with a ``model_dump``,
    since there is no source TOML to reuse.
    """

    def __init__(self, ws_root: Path) -> None:
        self._config_path = None
        workspace = SimpleNamespace(root=ws_root, project_root=ws_root)
        setup = SimpleNamespace(workspace=workspace)
        # A project built in memory anchors its checks where its project.toml would be.
        self._ctx = SimpleNamespace(setup=setup, config_path=ws_root / "project.toml")
        self.config = self._cfg = SimpleNamespace(
            model_dump=lambda **kwargs: {"workflow": {"mode": "simulation"}}
        )


def _staged_config():
    """A validated ``[calibration]`` section declaring one phase."""
    from hydromodpy.calibration.config import CalibrationConfig

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


class _FakeStagedReport:
    """Stand-in for a ``CalibrationReport``: an object, not a mapping."""

    def to_dict(self) -> dict[str, bool]:
        return {"staged": True}


def _patch_runners(monkeypatch, calls: dict) -> None:
    """Record which runner a calibration entry point reaches."""

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["staged_path"] = Path(config_path)
        calls["staged_phase"] = phase
        calls["staged_kwargs"] = kwargs
        return _FakeStagedReport()

    def fake_cli(config_path, **kwargs):
        calls["cli_path"] = Path(config_path)
        calls["cli_kwargs"] = dict(kwargs)
        return {"staged": False}

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )
    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)


def test_project_calibrate_toml_mode_routes_phases_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """``Project.calibrate(config_path=...)`` honors the declared phases."""
    from hydromodpy.project.facade import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(_cfg=None, _config_path=None)
    result = Project.calibrate(project, config_path=config)

    assert isinstance(result, _FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


def test_project_calibrate_embedded_phases_route_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """A project built from a TOML that declares phases runs them staged."""
    from hydromodpy.project.facade import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(
        _cfg=SimpleNamespace(calibration=_staged_config()),
        _config_path=config,
        _environment=None,
    )
    result = Project.calibrate(project, phase="steady_k")

    assert isinstance(result, _FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert calls["staged_phase"] == "steady_k"


# ---------------------------------------------------------------------------
# File-backed Python mode: the document must mean the same thing wherever it
# is read from, and must never leak what the project's own [calibration]
# declares. Uses a real, minimal HydroModPyConfig (not the duck-typed double
# above): the bug these two guard is specific to real path resolution.
# ---------------------------------------------------------------------------

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


def _write_real_project(tmp_path: Path) -> Path:
    """A minimal, real, loadable project: a relative DEM path and
    a [site], the idiom every example uses. Also declares Sy and
    a network output the two tests below never mention in their Python
    call, to prove neither leaks into the written document.
    """
    path = tmp_path / "project.toml"
    path.write_text(MINIMAL_REAL_PROJECT_TOML, encoding="utf-8")
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs" / "naizin_dem.tif").write_bytes(b"")
    return path


def _write_document(monkeypatch, calls: dict) -> None:
    """Patch the staged runner so the write happens but nothing runs."""

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["doc_path"] = Path(config_path)
        return _FakeStagedReport()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )


def test_file_backed_python_phases_document_holds_only_what_python_gave(
    monkeypatch, tmp_path: Path
) -> None:
    """[calibration] is a plain overwrite, never a merge with the project's.

    The project declares Sy and a network output; the Python call below
    names only K and declares no output. Neither Sy nor the network output
    may appear in the written document, or a phases= call naming only K
    would silently also carry Sy and an unrelated output along.
    """
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.project.facade import Project

    config_path = _write_real_project(tmp_path)

    calls: dict = {}
    _write_document(monkeypatch, calls)

    with Project(config_path, headless=True) as project:
        project.calibrate(
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            phases=[{"name": "k_only", "parameters": ["K"], "max_trials": 5}],
        )

    written = HydroModPyConfig.from_toml(calls["doc_path"])
    assert set(written.calibration.parameters) == {"K"}
    assert set(written.calibration.outputs) == set()
    assert written.calibration.protocol is None


def test_dispatch_workflow_calibration_routes_phases_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """``hmp run`` on a phased calibration TOML runs it staged."""
    from hydromodpy.project.dispatch.workflow import dispatch_workflow
    from hydromodpy.project.request import request_of

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    result = dispatch_workflow("calibration", request_of(config), base=tmp_path)

    # The testbed provider calls dict(run_calibration(...)): the dispatcher owes
    # its callers a mapping, not the report object.
    assert dict(result) == {"staged": True}
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


# ---------------------------------------------------------------------------
# The routing probe
# ---------------------------------------------------------------------------


def test_selected_phase_surfaces_the_real_error_of_an_unreadable_toml(tmp_path: Path) -> None:
    """``--phase`` on an unreadable file reports the file, not a missing phase."""
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    with pytest.raises(ConfigError, match="not_a_field"):
        api.calibrate(config, phase="steady_k")


def test_phase_on_a_mono_phase_toml_raises_a_typed_calibration_error(tmp_path: Path) -> None:
    """Refusing a phase is a calibration refusal, so the CLI can exit 21."""
    from hydromodpy.core.exceptions import CalibrationError

    config = _write_toml(tmp_path / "calib.toml", MONO_PHASE_TOML)
    with pytest.raises(CalibrationError, match="steady_k"):
        api.calibrate(config, phase="steady_k")


def test_project_calibrate_forwards_resume_and_the_label_on_the_file_routes(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.project.facade import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)
    project = SimpleNamespace(_cfg=None, _config_path=None)

    Project.calibrate(project, config_path=config, resume=True, project="mine")

    assert calls["staged_kwargs"] == {
        "bounds": Bounds(),
        "project": "mine",
        "workspace": None,
        "metric_fn": None,
        "objective": None,
        "resume": True,
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"case": "other"}, "case= names the session"),
        ({"protocol": "matching_hydrographic_network"}, "protocol= alone"),
    ],
)
def test_project_calibrate_refuses_what_a_file_cannot_take(
    monkeypatch, tmp_path: Path, kwargs: dict, message: str
) -> None:
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.facade import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    _patch_runners(monkeypatch, {})

    with pytest.raises(ConfigError, match=message):
        Project.calibrate(
            SimpleNamespace(_cfg=None, _config_path=None), config_path=config, **kwargs
        )


def test_project_calibrate_names_an_unknown_argument() -> None:
    from hydromodpy.project.facade import Project

    with pytest.raises(TypeError, match="'stagnation'"):
        Project.calibrate(SimpleNamespace(), parameters={"K": {}}, stagnation=3)


def test_project_calibrate_dry_run_returns_the_plan_of_the_file(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.project.facade import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run",
        lambda cfg, path, **kw: {"case": path.stem},
    )

    plan = Project.calibrate(SimpleNamespace(), config_path=config, dry_run=True)

    assert plan == {"case": "staged"}
    assert "staged_path" not in calls


def test_the_verb_dry_run_gives_a_calibration_plan_and_runs_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project.calibrate import CalibrationPlan

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run",
        lambda cfg, path, **kw: {"case": path.stem},
    )

    plan = api.calibrate(config, dry_run=True, preflight=False)

    assert isinstance(plan, CalibrationPlan)
    assert plan.plan == {"case": "staged"}
    assert [phase["name"] for phase in plan.phases] == ["steady_k"]
    assert "staged_path" not in calls
    with pytest.raises(CalibrationError, match="unknown phase 'nope'"):
        api.calibrate(config, dry_run=True, preflight=False, phase="nope")


@pytest.mark.parametrize(
    ("source", "expected"), [(None, "needs a project built"), ("a.toml", "plan")]
)
def test_project_calibrate_dry_run_in_memory_needs_a_file(
    monkeypatch, tmp_path: Path, source: str | None, expected: str
) -> None:
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.facade import Project

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


def test_project_calibrate_protocol_builds_on_the_projects_own_calibration(tmp_path: Path) -> None:
    """K and Sy are the project's, the protocol lays its two phases over them."""
    from hydromodpy.project.facade import Project

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
    (tmp_path / "project.toml").write_text(text, encoding="utf-8")
    (tmp_path / "a.gpkg").write_bytes(b"")

    with Project(tmp_path / "project.toml", headless=True) as project:
        plan = project.calibrate(protocol="matching_hydrographic_network", dry_run=True)

    assert [(p["name"], p["parameters"]) for p in plan["phases"]] == [
        ("steady_conductivity", ["K"]),
        ("transient_storage", ["Sy"]),
    ]
