"""Unit tests for ``hmp.calibrate``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy as hmp
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
path = "flow.param.K.field.value"

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
path = "flow.param.K.field.value"

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


def test_project_calibrate_in_memory_phases_are_refused(monkeypatch) -> None:
    """No file to re-read per phase: refuse, naming the phases, never flatten."""
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project import Project

    calls: dict = {}
    _patch_runners(monkeypatch, calls)

    project = SimpleNamespace(
        config=SimpleNamespace(calibration=_staged_config()),
        _config_path=None,
    )
    with pytest.raises(CalibrationError, match="steady_k"):
        Project.calibrate(project)


def test_calibrate_object_config_with_phases_is_refused(monkeypatch) -> None:
    """``hmp.calibrate(config_object)`` refuses instead of running one stage."""
    from hydromodpy.core.exceptions import CalibrationError

    class _NoProject:
        def __init__(self, *args, **kwargs):
            raise AssertionError("a refused staged calibration must build no Project")

    monkeypatch.setattr("hydromodpy.project.Project", _NoProject)

    config = SimpleNamespace(calibration=_staged_config())
    with pytest.raises(CalibrationError, match="steady_k"):
        hmp.calibrate(config)


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
