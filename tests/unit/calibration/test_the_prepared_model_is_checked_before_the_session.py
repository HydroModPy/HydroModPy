"""What only the prepared model shows is checked once, right after the preparation.

Three checks need the configuration the pipeline was prepared from: a bound
the field refuses, and the drain and release-package conductances a network
search relies on. They ran at the top of every search, so once per restart,
after the session had been reserved: a refused search left a failed session
behind. They now run once per preparation, before the session is reserved, on
every route.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.runners import cli_runner, programmatic_runner, staged_runner
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.core.exceptions import ObjectiveError

_FILE = """
[workspace]

[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[calibration]
method = "bisection"
max_trials = "auto"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "here.gpkg"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""

_PHASE = """
[[calibration.phases]]
name = "k_only"
method = "bisection"
parameters = ["K"]
"""


@pytest.fixture
def prepared(monkeypatch) -> list[str]:
    """Prepare a model whose drains carry a fixed conductance, and record it."""
    from hydromodpy.physics.flow.flow_config import FlowConfig

    flow = FlowConfig.model_validate(
        {"active_bc": ["drainage"], "bc": {"drainage": {"kind": "cauchy", "value": 1e-3}}}
    )
    reached: list[str] = []

    def _prepare(cfg_path, **_kwargs):
        reached.append(Path(cfg_path).name)
        return SimpleNamespace(base_cfg=SimpleNamespace(flow=flow))

    for module in (cli_runner, staged_runner, programmatic_runner):
        monkeypatch.setattr(module, "prepare_trials", _prepare)
    return reached


def _write(tmp_path: Path, *extra: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(_FILE + "".join(textwrap.dedent(item) for item in extra), encoding="utf-8")
    (tmp_path / "here.gpkg").write_text("", encoding="utf-8")
    return path


def _sessions(tmp_path: Path) -> list[str]:
    root = tmp_path / "sessions"
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def test_a_search_without_phases_is_refused_before_its_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_calibration_cli(_write(tmp_path))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_a_phase_is_refused_before_the_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_staged_calibration(_write(tmp_path, _PHASE))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_a_search_from_python_is_refused_before_its_session(tmp_path, prepared) -> None:
    from hydromodpy.project import Project

    path = _write(tmp_path)
    with Project(path, headless=True) as project:
        with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
            project.calibrate(
                parameters={"K": {"bounds": [1e-7, 1e-3]}},
                outputs={"net": {"support": "network", "stream_geometry_path": "here.gpkg"}},
                objective_blocks=[
                    {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            )

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []
