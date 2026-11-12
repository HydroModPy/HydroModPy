"""What a calibration declares, with nothing run: ``CalibrationPlan`` and ``calibration_plan``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.project.calibrate import CalibrationPlan, calibration_plan, route_calibration

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


def test_a_phase_of_a_file_that_does_not_read_names_the_real_error(
    tmp_path: Path, preflights
) -> None:
    from hydromodpy.core.exceptions import ConfigError

    config = _write_toml(tmp_path / "c.toml", TYPO_TOML)

    with pytest.raises(ConfigError, match="cannot be read"):
        route_calibration(config, phase="steady_k", environment=_Environment())


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
