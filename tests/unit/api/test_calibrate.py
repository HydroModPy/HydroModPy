"""Unit tests for ``hmp.calibrate``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy as hmp
from hydromodpy.core.toml_io.writer import dumps as dump_toml
from tests._helpers.api_doubles import make_capturing_project

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_calibrate_with_path_routes_to_run_calibration_cli(monkeypatch, tmp_path: Path) -> None:
    """A TOML path calls ``run_calibration_cli`` directly (no Project detour)."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    captured: dict = {}

    def fake_cli(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"report": "ok"}

    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)

    result = hmp.calibrate(config, project="my_label")
    assert result == {"report": "ok"}
    assert captured["config_path"] == config.resolve()
    assert captured["kwargs"] == {"project": "my_label"}


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

    hmp.calibrate(config, headless=False)
    assert "headless" not in captured["kwargs"]


@pytest.mark.parametrize("headless", [True, False])
def test_calibrate_object_config_routes_to_project(monkeypatch, headless: bool) -> None:
    """A non-path config opens a Project and delegates to ``project.calibrate``.

    ``headless`` reaches the Project constructor, not the verb kwargs; the
    user kwargs (here ``max_iter``) reach ``calibrate`` untouched and never
    leak a ``config_path``.
    """
    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(captured, result={"report": "from_object"}, verb="calibrate"),
    )

    fake_cfg = object()
    result = hmp.calibrate(fake_cfg, headless=headless, max_iter=10)
    assert result == {"report": "from_object"}
    assert captured["init_cfg"] is fake_cfg
    assert captured["init_headless"] is headless
    assert captured["verb_kwargs"] == {"max_iter": 10}
    assert "config_path" not in captured["verb_kwargs"]
    assert "headless" not in captured["verb_kwargs"]
    assert captured["closed"] is True


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
max_iter = 18

[[calibration.phases]]
name = "sy_transient"
parameters = ["Sy"]
regime = "transient"
objective_blocks = { hydrograph = 99, network = 1 }
max_iter = 30
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
            "max_iter": 18,
        },
        {
            "name": "sy_transient",
            "parameters": ["Sy"],
            "regime": "transient",
            "objective_blocks": {"hydrograph": 99, "network": 1},
            "max_iter": 30,
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
        self._ctx = SimpleNamespace(setup=setup)
        self.config = SimpleNamespace(
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
    """Stand-in for ``StagedCalibrationReport``: an object, not a mapping."""

    def to_dict(self) -> dict[str, bool]:
        return {"staged": True}


def _patch_runners(monkeypatch, calls: dict) -> None:
    """Record which runner a calibration entry point reaches."""

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["staged_path"] = Path(config_path)
        calls["staged_phase"] = phase
        return _FakeStagedReport()

    def fake_cli(config_path, **kwargs):
        calls["cli_path"] = Path(config_path)
        return {"staged": False}

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )
    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)


def test_project_calibrate_toml_mode_routes_phases_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """``Project.calibrate(config_path=...)`` honours the declared phases."""
    from hydromodpy.project import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(config=None, _config_path=None)
    result = Project.calibrate(project, config_path=config)

    assert isinstance(result, _FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


def test_project_calibrate_embedded_phases_route_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """A project built from a TOML that declares phases runs them staged."""
    from hydromodpy.project import Project

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(
        config=SimpleNamespace(calibration=_staged_config()),
        _config_path=config,
    )
    result = Project.calibrate(project, phase="steady_k")

    assert isinstance(result, _FakeStagedReport)
    assert calls["staged_path"] == config.resolve()
    assert calls["staged_phase"] == "steady_k"


def test_project_calibrate_in_memory_embedded_phases_route_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """No source file to fork each phase from: write one and run it staged.

    Replaces the old refusal (``in_memory_staged_refusal``, removed): an
    embedded declaration on a project built in memory now reaches the staged
    runner through the document ``run_calibration_programmatic`` writes.
    """
    from hydromodpy.project import Project

    calls: dict = {}

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["doc_path"] = Path(config_path)
        calls["phase"] = phase
        return _FakeStagedReport()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )

    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    project = _InMemoryPythonProject(ws_root)
    project.config.calibration = _staged_config()

    result = Project.calibrate(project, phase="steady_k")

    assert isinstance(result, _FakeStagedReport)
    assert calls["phase"] == "steady_k"
    doc_path = calls["doc_path"]
    assert doc_path.parent == ws_root / "sessions"
    assert doc_path.is_file()


def test_calibrate_object_config_with_phases_routes_through_project(monkeypatch) -> None:
    """``hmp.calibrate(config_object)`` no longer refuses a declared phase.

    It delegates to ``Project.calibrate``, which knows how to run embedded
    phases from a project built in memory (see the test above).
    """
    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(captured, result={"report": "staged"}, verb="calibrate"),
    )

    config = SimpleNamespace(calibration=_staged_config())
    result = hmp.calibrate(config, phase="steady_k")
    assert result == {"report": "staged"}
    assert captured["verb_kwargs"] == {"phase": "steady_k"}


def test_python_mode_phases_and_equivalent_toml_pick_the_same_phases(
    monkeypatch, tmp_path: Path
) -> None:
    """Phases declared in Project.calibrate(phases=...) and the equivalent
    TOML validate to the same phase declarations and the same methods.

    Covers the ``Project.calibrate(..., phases=[...])`` Python mode: the
    dictionaries use the TOML keys one for one, the call writes a document
    next to ``sessions/``, and that document is a plain calibration TOML
    (``hmp calibrate <path>`` replays it, checked separately).

    Compares the parsed configs the two routes produce, not what the staged
    runner does with them (patched here, like every other test in this
    file): a launch-level comparison belongs to ``tests/unit/calibration``,
    against the runner itself.
    """
    from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
    from hydromodpy.calibration.runners.staged_runner import phase_summaries
    from hydromodpy.project import Project

    toml_path = _write_toml(tmp_path / "phases.toml", PHASES_TOML_EQUIVALENT)
    cfg_toml, _raw_toml = load_toml_calibration(toml_path)

    calls: dict = {}

    def fake_staged(config_path, *, phase=None, **kwargs):
        calls["doc_path"] = Path(config_path)
        return _FakeStagedReport()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )

    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    project = _InMemoryPythonProject(ws_root)

    result = Project.calibrate(project, **PYTHON_MODE_PHASES_KWARGS)

    assert isinstance(result, _FakeStagedReport)
    doc_path = calls["doc_path"]
    assert doc_path.parent == ws_root / "sessions"
    cfg_python, _raw_python = load_toml_calibration(doc_path)

    def phase_dump(cfg):
        return [p.model_dump(mode="json", exclude_none=True) for p in cfg.phases]

    assert phase_dump(cfg_python) == phase_dump(cfg_toml)
    assert phase_summaries(cfg_python) == phase_summaries(cfg_toml)


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
project_root = "."

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "naizin_dem.tif"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = []

[flow]
flow_regime = "steady"
active_sinks_sources = []
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[simulation]
name = "minimal"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[calibration]
seed = 7

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "a_stream_network.gpkg"
diagonal_neighbors = true

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[display]
enabled = false
"""


def _write_real_project(tmp_path: Path) -> Path:
    """A minimal, real, loadable project: relative dem_init_path and
    project_root = ".", the idiom every example uses. Also declares Sy and
    a network output the two tests below never mention in their Python
    call, to prove neither leaks into the written document.
    """
    path = tmp_path / "project.toml"
    path.write_text(MINIMAL_REAL_PROJECT_TOML, encoding="utf-8")
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


def test_file_backed_python_phases_document_keeps_the_projects_own_paths(
    monkeypatch, tmp_path: Path
) -> None:
    """The written document means the same thing wherever it sits.

    HydroModPyConfig.from_toml resolves a relative path against the file it
    is given. A document that referenced the project through base_config
    would re-anchor every relative path the project declares -- project_root
    included -- on sessions/, not on the project: a bug found and fixed
    while writing the real replay check for this step. Embedding the
    project's own already-resolved config (every path already absolute)
    avoids it.
    """
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project import Project

    config_path = _write_real_project(tmp_path)
    # Where the project resolves a bare relative stream_geometry_path: same
    # directory as project.toml. Content is never read, only existence.
    (tmp_path / "k_python_stream_network.gpkg").write_bytes(b"")

    calls: dict = {}
    _write_document(monkeypatch, calls)

    with Project(config_path, headless=True) as project:
        # Read here, not from a fresh HydroModPyConfig.from_toml(config_path):
        # headless=True itself adjusts display, and the document embeds
        # project.config as Project sees it, not a bare reload of the file.
        expected = project.config
        result = project.calibrate(
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            outputs={
                "streams": {
                    "support": "network",
                    "stream_geometry_path": "k_python_stream_network.gpkg",
                    "diagonal_neighbors": True,
                }
            },
            objective_blocks=[
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["streams"]}
            ],
            phases=[{"name": "k_only", "parameters": ["K"], "max_iter": 5}],
        )

    assert isinstance(result, _FakeStagedReport)
    doc_path = calls["doc_path"]
    assert doc_path.parent == config_path.parent / "sessions"

    written = HydroModPyConfig.from_toml(doc_path)
    # workflow.mode is deliberately overridden to "calibration" so the
    # document dispatches as one; every other section is untouched.
    assert written.workflow.mode == "calibration"
    excluded = {"calibration", "workflow"}
    assert written.model_dump(
        mode="json", exclude=excluded, exclude_none=True
    ) == expected.model_dump(mode="json", exclude=excluded, exclude_none=True)
    assert written.workspace.project_root == expected.workspace.project_root
    assert written.geographic.catchment.dem_init_path == expected.geographic.catchment.dem_init_path

    # The relative stream_geometry_path is meant relative to the project, as
    # in TOML mode: the document must carry it resolved, not relative to
    # sessions/, one level short of where the project keeps it.
    assert written.calibration.outputs["streams"].stream_geometry_path == str(
        (tmp_path / "k_python_stream_network.gpkg").resolve()
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
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project import Project

    config_path = _write_real_project(tmp_path)

    calls: dict = {}
    _write_document(monkeypatch, calls)

    with Project(config_path, headless=True) as project:
        project.calibrate(
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            phases=[{"name": "k_only", "parameters": ["K"], "max_iter": 5}],
        )

    written = HydroModPyConfig.from_toml(calls["doc_path"])
    assert set(written.calibration.parameters) == {"K"}
    assert set(written.calibration.outputs) == set()
    assert written.calibration.protocol is None


def test_calibrate_object_config_lists_its_phases(monkeypatch) -> None:
    """``list_phases`` is answered from the config object, not swallowed."""

    class _NoProject:
        def __init__(self, *args, **kwargs):
            raise AssertionError("listing phases must build no Project")

    monkeypatch.setattr("hydromodpy.project.Project", _NoProject)

    config = SimpleNamespace(calibration=_staged_config())
    assert hmp.calibrate(config, list_phases=True) == [
        {
            "name": "steady_k",
            "description": "zero of the signed gap",
            "method": "bisection",
            "parameters": ["K"],
            "depends_on": None,
            "freeze_on_success": True,
            "interval_width": {
                "tolerance": 0.05,
                "mode": "relative",
                "source": "default",
                "mode_source": "default",
                "on_distances": False,
                "rule": "5 % of the best cost",
            },
            "comparisons": [],
        }
    ]


def test_dispatch_workflow_calibration_routes_phases_to_staged_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """``hmp run`` on a phased calibration TOML runs it staged."""
    from hydromodpy.project.dispatch.workflow import dispatch_workflow

    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    result = dispatch_workflow("calibration", config)

    # The testbed provider calls dict(run_calibration(...)): the dispatcher owes
    # its callers a mapping, not the report object.
    assert dict(result) == {"staged": True}
    assert calls["staged_path"] == config.resolve()
    assert "cli_path" not in calls


# ---------------------------------------------------------------------------
# The routing probe
# ---------------------------------------------------------------------------


def test_list_phases_surfaces_the_real_error_of_an_unreadable_toml(tmp_path: Path) -> None:
    """A file that cannot be read is not reported as declaring no phases."""
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    with pytest.raises(ConfigError, match="not_a_field"):
        hmp.calibrate(config, list_phases=True)


def test_selected_phase_surfaces_the_real_error_of_an_unreadable_toml(tmp_path: Path) -> None:
    """``--phase`` on an unreadable file reports the file, not a missing phase."""
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    with pytest.raises(ConfigError, match="not_a_field"):
        hmp.calibrate(config, phase="steady_k")


def test_unreadable_toml_still_defers_to_the_runner_without_a_phase(
    monkeypatch, tmp_path: Path
) -> None:
    """The probe stays non-fatal where the runner reports the failure itself."""
    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    assert hmp.calibrate(config) == {"staged": False}
    assert calls["cli_path"] == config.resolve()


def test_project_calibrate_with_a_phase_surfaces_the_real_error_of_an_unreadable_toml(
    monkeypatch, tmp_path: Path
) -> None:
    """The facade asks the same question ``hmp.calibrate`` asks.

    TYPO_TOML declares ``steady_k`` and fails to validate, so a report of "no
    phases" would send the reader to a phases block that is present and
    correct. The routing probe is non-fatal on purpose and must not answer
    here.
    """
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project import Project

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(config=None, _config_path=None)
    with pytest.raises(ConfigError) as refusal:
        Project.calibrate(project, config_path=config, phase="steady_k")

    message = str(refusal.value)
    assert "not_a_field" in message
    assert "declares no" not in message
    assert calls == {}


def test_project_calibrate_without_a_phase_still_defers_to_the_runner(
    monkeypatch, tmp_path: Path
) -> None:
    """Routing alone stays non-fatal: the runner reports the file itself."""
    from hydromodpy.project import Project

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(config=None, _config_path=None)
    assert Project.calibrate(project, config_path=config) == {"staged": False}
    assert calls["cli_path"] == config.resolve()


def test_project_calibrate_forwards_only_kwargs_the_staged_runner_accepts(
    monkeypatch, tmp_path: Path
) -> None:
    """``return_report`` is documented on ``calibrate`` for every mode.

    The double binds the forwarded call against the REAL signature, so a
    keyword the staged runner does not declare fails here instead of reaching
    the user as a bare ``TypeError``.
    """
    import inspect

    from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
    from hydromodpy.project import Project

    signature = inspect.signature(run_staged_calibration)
    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    forwarded: dict = {}

    def fake_staged(config_path, **kwargs):
        signature.bind(config_path, **kwargs)
        forwarded.update(kwargs)
        return _FakeStagedReport()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration",
        fake_staged,
    )

    project = SimpleNamespace(config=None, _config_path=None)
    Project.calibrate(project, config_path=config, phase="steady_k", return_report=False)

    assert forwarded["phase"] == "steady_k"
    assert forwarded["return_report"] is False


def test_phase_on_a_mono_phase_toml_raises_a_typed_calibration_error(tmp_path: Path) -> None:
    """Refusing a phase is a calibration refusal, so the CLI can exit 21."""
    from hydromodpy.core.exceptions import CalibrationError

    config = _write_toml(tmp_path / "calib.toml", MONO_PHASE_TOML)
    with pytest.raises(CalibrationError, match="steady_k"):
        hmp.calibrate(config, phase="steady_k")


_PROTOCOL_TOML = """
[calibration]
protocol = "matching_hydrographic_network"

[calibration.parameters.K]

[calibration.parameters.Sy]

[calibration.outputs.streams]
support = "network"
stream_geometry_path = "streams.gpkg"

[[data.hydrometry.sources]]
station_ids = ["G1"]
"""

_NO_PROTOCOL_TOML = """
[calibration]
seed = 7
foo = "bar"
"""


def test_calibrate_expand_returns_only_what_the_protocol_writes(tmp_path: Path) -> None:
    """A protocol file expands to its two written sections, no ``protocol`` key."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    result = hmp.calibrate(config, expand=True)

    assert set(result["calibration"]) == {"objective_blocks", "phases", "outputs"}
    phases = result["calibration"]["phases"]
    assert [phase["name"] for phase in phases] == ["steady_conductivity", "transient_storage"]
    assert result["calibration"]["objective_blocks"] == [
        {"name": "network_extension", "metric": "distance_gap", "uses_outputs": ["streams"]},
        {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["hydrograph"]},
    ]
    # The protocol's own output, not the file's: "streams" already sits in the
    # file and stays out of what --expand adds.
    assert set(result["calibration"]["outputs"]) == {"hydrograph"}
    assert result["calibration"]["outputs"]["hydrograph"] == {
        "variable": "discharge",
        "support": "point",
        "observes": "G1",
    }


_PROTOCOL_TOML_WITH_ITS_OWN_HYDROGRAPH = """
[calibration]
protocol = "matching_hydrographic_network"

[calibration.parameters.K]

[calibration.parameters.Sy]

[calibration.outputs.streams]
support = "network"
stream_geometry_path = "streams.gpkg"

[calibration.outputs.hydrograph]
variable = "discharge"
support = "point"
observes = "G1"
time = "all"
reducer = "none"
diagonal_neighbors = false

[[data.hydrometry.sources]]
station_ids = ["G1"]
"""


def test_calibrate_expand_does_not_repeat_an_output_the_file_already_declares(
    tmp_path: Path,
) -> None:
    """A sealed run's own dump of the hydrograph output must not read as new.

    The file spells out every default the protocol's own fresh write leaves
    out (``time``, ``reducer``, ``diagonal_neighbors``); comparing raw dicts
    would show it again under ``outputs`` as though the protocol had just
    added it.
    """
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML_WITH_ITS_OWN_HYDROGRAPH)

    result = hmp.calibrate(config, expand=True)

    assert set(result["calibration"]) == {"objective_blocks", "phases"}


def test_calibrate_expand_names_the_protocol_and_its_first_reference(tmp_path: Path) -> None:
    """The header data names the protocol, its version and a short citation."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    result = hmp.calibrate(config, expand=True)

    assert result["protocol"] == {
        "name": "matching_hydrographic_network",
        "version": "1.1",
        "citation": "Abherve et al. 2023, 10.5194/hess-27-3221-2023",
    }


def test_calibrate_expand_on_a_file_without_a_protocol_returns_its_own_section(
    tmp_path: Path,
) -> None:
    """No protocol declared: the section comes back unchanged, and ``protocol`` is None."""
    config = _write_toml(tmp_path / "calib.toml", _NO_PROTOCOL_TOML)

    result = hmp.calibrate(config, expand=True)

    assert result == {"calibration": {"seed": 7, "foo": "bar"}, "protocol": None}


def test_calibrate_expand_round_trips_through_a_hand_written_file(tmp_path: Path) -> None:
    """Pasting the printed section into a plain file expands to the same phases.

    A hand-written file drops the protocol table (``protocol__delete = true`` in
    a real ``base_config`` chain; here there is none to inherit from, so the
    key is simply absent) and keeps the phases and blocks the protocol wrote.
    Expanding it again -- a no-op, since it names no protocol -- must return
    the exact phases and blocks the protocol expansion produced.
    """
    protocol_config = _write_toml(tmp_path / "protocol.toml", _PROTOCOL_TOML)
    expanded = hmp.calibrate(protocol_config, expand=True)

    written = dump_toml({"calibration": expanded["calibration"]})
    hand_written = _write_toml(
        tmp_path / "hand_written.toml",
        f"""
[calibration.parameters.K]

[calibration.parameters.Sy]

[calibration.outputs.streams]
support = "network"
stream_geometry_path = "streams.gpkg"

{written}
""",
    )

    round_tripped = hmp.calibrate(hand_written, expand=True)

    assert round_tripped["protocol"] is None
    assert round_tripped["calibration"]["phases"] == expanded["calibration"]["phases"]
    assert (
        round_tripped["calibration"]["objective_blocks"]
        == expanded["calibration"]["objective_blocks"]
    )


def test_calibrate_expand_refuses_list_phases(tmp_path: Path) -> None:
    """``expand`` answers what would run, it does not also run or list it."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    with pytest.raises(ValueError, match="expand"):
        hmp.calibrate(config, expand=True, list_phases=True)


def test_calibrate_expand_refuses_a_phase(tmp_path: Path) -> None:
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    with pytest.raises(ValueError, match="expand"):
        hmp.calibrate(config, expand=True, phase="steady_conductivity")


def test_calibrate_expand_refuses_a_config_object() -> None:
    """``expand`` unfolds a protocol from a TOML document, not a config object."""
    config = SimpleNamespace(calibration=_staged_config())

    with pytest.raises(ValueError, match="TOML path"):
        hmp.calibrate(config, expand=True)
