"""What a calibration declares, with nothing run: ``CalibrationPlan`` and ``calibration_plan``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.toml_io.writer import dumps as dump_toml
from hydromodpy.project.calibrate import CalibrationPlan, calibration_plan

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
