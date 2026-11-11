"""What a calibration declares, with nothing run: ``CalibrationPlan`` and ``calibration_plan``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.toml_io.writer import dumps as dump_toml
from hydromodpy.project.calibrate import (
    CalibrationPlan,
    calibration_plan,
    promote_trial,
    route_calibration,
)

pytestmark = pytest.mark.fast

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


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


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


def test_calibration_phases_of_a_config_object_builds_no_project(monkeypatch) -> None:
    """The phases of a config object are read from its section, with nothing else to say."""

    class _NoProject:
        def __init__(self, *args, **kwargs):
            raise AssertionError("listing phases must build no Project")

    monkeypatch.setattr("hydromodpy.project.facade.Project", _NoProject)

    config = SimpleNamespace(calibration=_staged_config())
    result = calibration_plan(config)

    assert result.protocol is None
    assert result.plan is None
    assert set(result.calibration) >= {"method", "parameters", "phases"}
    assert result.phases == [
        {
            "name": "steady_k",
            "description": "zero of the signed gap",
            "method": "bisection",
            "parameters": ["K"],
            "depends_on": None,
            "freeze_on_success": True,
            "search": {
                "method": {"value": "bisection", "source": "phase"},
                "max_trials": {"value": "auto", "source": "default"},
                "precision": {"value": None, "source": "default"},
                "method_options": {"value": {}, "source": "default"},
            },
            "interval_width": {
                "margin": 0.05,
                "kind": "relative",
                "source": "default",
                "on_distances": False,
                "rule": "5 % of the best cost",
            },
            "comparisons": [],
            "window": "no window, all of the run",
        }
    ]


def test_calibration_phases_surface_the_real_error_of_an_unreadable_toml(tmp_path: Path) -> None:
    """A file that cannot be read is not reported as declaring no phases."""
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "typo.toml", TYPO_TOML)
    with pytest.raises(ConfigError, match="not_a_field"):
        calibration_plan(config)


_PROTOCOL_TOML = """
[calibration]
protocol = "matching_hydrographic_network"

[calibration.parameters.K]

[calibration.parameters.Sy]

[calibration.outputs.streams]
support = "network"
map.complete = "streams.gpkg"

[[data.hydrometry.sources]]
station_ids = ["G1"]
"""

_NO_PROTOCOL_TOML = """
[calibration]
seed = 7
"""


def test_calibration_phases_expand_returns_the_whole_section(tmp_path: Path) -> None:
    """A protocol file expands to its whole section, pasteable, with no ``protocol`` key."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    result = calibration_plan(config)

    # A file of no edition keeps the default of 2.0, written out.
    assert set(result.calibration) == {
        "parameters",
        "outputs",
        "objective_blocks",
        "phases",
        "persist_trial_series",
    }
    phases = result.calibration["phases"]
    assert [phase["name"] for phase in phases] == ["steady_conductivity", "transient_storage"]
    assert result.calibration["objective_blocks"] == [
        {"name": "network_extension", "metric": "distance_gap", "uses_outputs": ["streams"]},
        {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["hydrograph"]},
    ]
    # The file's own network output and the gauge the protocol adds, together:
    # a section with only the protocol's additions would not load on its own.
    assert set(result.calibration["outputs"]) == {"streams", "hydrograph"}
    assert result.calibration["outputs"]["hydrograph"] == {
        "variable": "discharge",
        "support": "point",
        "observes": "G1",
    }
    assert set(result.calibration["parameters"]) == {"K", "Sy"}


_PROTOCOL_TOML_WITH_ITS_OWN_HYDROGRAPH = """
[calibration]
protocol = "matching_hydrographic_network"

[calibration.parameters.K]

[calibration.parameters.Sy]

[calibration.outputs.streams]
support = "network"
map.complete = "streams.gpkg"

[calibration.outputs.hydrograph]
variable = "discharge"
support = "point"
observes = "G1"
time = "all"
reducer = "none"

[[data.hydrometry.sources]]
station_ids = ["G1"]
"""


def test_calibration_phases_expand_lists_an_output_the_file_already_declares_once(
    tmp_path: Path,
) -> None:
    """A sealed run's own dump of the hydrograph output is one output, not two."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML_WITH_ITS_OWN_HYDROGRAPH)

    result = calibration_plan(config)

    assert set(result.calibration["outputs"]) == {"streams", "hydrograph"}


def test_calibration_phases_expand_names_the_protocol_and_its_first_reference(
    tmp_path: Path,
) -> None:
    """The header data names the protocol, its version and a short citation."""
    config = _write_toml(tmp_path / "calib.toml", _PROTOCOL_TOML)

    result = calibration_plan(config)

    assert result.protocol == {
        "name": "matching_hydrographic_network",
        "version": "1.3",
        "citation": "Abherve et al. 2023, 10.5194/hess-27-3221-2023",
        "inherited": False,
    }


def test_calibration_phases_expand_says_when_the_protocol_comes_from_the_base_config(
    tmp_path: Path,
) -> None:
    """Only then does a file pasting the section under that base drop a protocol."""
    _write_toml(tmp_path / "project.toml", _PROTOCOL_TOML)
    config = _write_toml(
        tmp_path / "run_calibration.toml",
        'base_config = "project.toml"\n\n[calibration]\nseed = 3\n',
    )

    result = calibration_plan(config)

    assert result.protocol["inherited"] is True
    assert result.calibration["seed"] == 3


def test_calibration_phases_expand_on_a_file_without_a_protocol_returns_its_own_section(
    tmp_path: Path,
) -> None:
    """No protocol declared: the section comes back unchanged, and ``protocol`` is None."""
    config = _write_toml(tmp_path / "calib.toml", _NO_PROTOCOL_TOML)

    result = calibration_plan(config)

    assert result.calibration == {"seed": 7, "persist_trial_series": False}
    assert result.protocol is None


def test_calibration_phases_expand_round_trips_through_a_hand_written_file(tmp_path: Path) -> None:
    """The printed section alone, pasted into a plain file, is the same calibration.

    A hand-written file drops the protocol table (``protocol__delete = true`` in
    a real ``base_config`` chain; here there is none to inherit from) and keeps
    everything else. Expanding it again -- a no-op, since it names no protocol
    -- must return the exact section the protocol expansion produced.
    """
    protocol_config = _write_toml(tmp_path / "protocol.toml", _PROTOCOL_TOML)
    expanded = calibration_plan(protocol_config)

    written = dump_toml({"calibration": expanded.calibration})
    hand_written = _write_toml(tmp_path / "hand_written.toml", written)

    round_tripped = calibration_plan(hand_written)

    assert round_tripped.protocol is None
    assert round_tripped.calibration == expanded.calibration


def test_the_plan_of_a_file_gives_json_and_names_what_a_launch_writes(
    monkeypatch, tmp_path: Path
) -> None:
    config = _write_toml(tmp_path / "staged.toml", STAGED_TOML)
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run",
        lambda cfg, path, **kw: {"case": path.stem, "project_root": path.parent},
    )

    plan = calibration_plan(config, workspace=tmp_path)

    assert isinstance(plan, CalibrationPlan)
    document = json.loads(json.dumps(plan.to_dict()))
    assert list(document) == ["phases", "calibration", "protocol", "plan"]
    assert document["plan"] == {"case": "staged", "project_root": str(tmp_path)}
    assert [phase["name"] for phase in document["phases"]] == ["steady_k"]


def test_the_plan_of_a_config_object_gives_json_without_a_launch_plan() -> None:
    plan = calibration_plan(SimpleNamespace(calibration=_staged_config()))
    document = json.loads(json.dumps(plan.to_dict()))
    assert document["plan"] is None and document["protocol"] is None
    assert set(document["calibration"]) >= {"method", "parameters", "phases"}


@pytest.mark.parametrize("name", ["missing.toml", "typo.toml"])
def test_a_file_that_is_not_there_or_not_readable_is_refused(tmp_path: Path, name: str) -> None:
    from hydromodpy.core.exceptions import ConfigError

    if name == "typo.toml":
        _write_toml(tmp_path / name, TYPO_TOML)
    with pytest.raises((ConfigError, FileNotFoundError)):
        calibration_plan(tmp_path / name)


# route_calibration: what a launch of a file needs, and the runner it goes to

SINGLE_TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "grid"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
"""


class _Environment:
    """An environment that records where it was checked."""

    bounds = None

    def __init__(self) -> None:
        self.checked: list[Path] = []

    def check(self, *, project_root: Path, workspace_root: Path) -> None:
        self.checked.append(Path(project_root))


@pytest.fixture
def preflights(monkeypatch) -> list[Path]:
    seen: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.calibration.preflight.preflight_launch",
        lambda target, **_kw: seen.append(Path(target)),
    )
    return seen


@pytest.mark.parametrize(("content", "staged"), [(STAGED_TOML, True), (SINGLE_TOML, False)])
def test_a_file_with_phases_goes_to_the_staged_runner(
    tmp_path: Path, preflights, content: str, staged: bool
) -> None:
    config = _write_toml(tmp_path / "c.toml", content)
    environment = _Environment()

    route = route_calibration(config, environment=environment)

    assert route.staged is staged
    assert route.target == config.resolve()
    assert route.environment is environment
    assert environment.checked == [tmp_path.resolve()]
    assert preflights == [config.resolve()]


def test_the_environment_is_checked_against_the_project_root_when_one_is_given(
    tmp_path: Path, preflights
) -> None:
    config = _write_toml(tmp_path / "c.toml", SINGLE_TOML)
    root = tmp_path / "project"
    root.mkdir()
    environment = _Environment()

    route_calibration(config, environment=environment, project_root=root)

    assert environment.checked == [root.resolve()]


def test_a_phase_a_file_does_not_declare_is_refused_before_the_preflight(
    tmp_path: Path, preflights
) -> None:
    from hydromodpy.core.exceptions import CalibrationError

    config = _write_toml(tmp_path / "c.toml", SINGLE_TOML)

    with pytest.raises(CalibrationError, match="declares no .*calibration.phases"):
        route_calibration(config, phase="fine", environment=_Environment())

    assert preflights == []


def test_a_phase_of_a_file_that_does_not_read_names_the_real_error(
    tmp_path: Path, preflights
) -> None:
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "c.toml", TYPO_TOML)

    with pytest.raises(ConfigError, match="cannot be read"):
        route_calibration(config, phase="steady_k", environment=_Environment())


def test_a_completed_session_is_asked_for_only_when_the_caller_asks(
    monkeypatch, tmp_path: Path, preflights
) -> None:
    asked: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.identical_session_of_file",
        lambda target: asked.append(target) or "the report",
    )
    config = _write_toml(tmp_path / "c.toml", SINGLE_TOML)

    route = route_calibration(config, environment=_Environment())

    assert asked == []
    assert route.completed_session() == "the report"
    assert asked == [config.resolve()]


def test_a_trial_is_promoted_through_the_pipeline_the_library_fills(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.calibration.runners.trial import trial_pipeline

    seen: list[tuple] = []

    def promote(project_root, case, trial, *, as_name):
        seen.append((project_root, case, trial, as_name, trial_pipeline()))
        return tmp_path / "runs" / "case"

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.promotion.promote_trial_from_session", promote
    )

    run_dir = promote_trial(tmp_path, "case", 4, as_name="k_high")

    assert run_dir == tmp_path / "runs" / "case"
    assert [item[:4] for item in seen] == [(tmp_path, "case", 4, "k_high")]


def test_the_plan_of_a_held_configuration_is_anchored_to_its_file_and_case(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.core.state.result_dirs import run_dir_rel
    from hydromodpy.results.catalog.registration import next_version_dirname

    preflighted: list[Path] = []
    monkeypatch.setattr(
        "hydromodpy.calibration.preflight.preflight_launch",
        lambda target, **_kw: preflighted.append(Path(target)),
    )
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.document.describe_dry_run",
        lambda cfg, path, **kw: {"case": "own", "project_root": str(tmp_path)},
    )
    held = SimpleNamespace(calibration=_staged_config())
    source = tmp_path / "c.toml"

    same = calibration_plan(held, source=source, case="own").plan
    other = calibration_plan(held, source=source, case="other").plan

    assert same == {"case": "own", "project_root": str(tmp_path)}
    assert other["case"] == "other"
    assert other["version"] == next_version_dirname(tmp_path, "other")
    assert other["run_dir"] == run_dir_rel(other["version"])
    assert preflighted == [source, source]
