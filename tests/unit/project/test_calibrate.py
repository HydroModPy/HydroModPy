"""What a calibration declares, with nothing run: ``CalibrationPlan`` and ``calibration_plan``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.calibrate import (
    CalibrationPlan,
    calibration_plan,
    route_calibration,
    write_session_reports,
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


def test_plan_of_a_file(monkeypatch, tmp_path: Path) -> None:
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


def test_plan_of_a_config() -> None:
    plan = calibration_plan(SimpleNamespace(calibration=_staged_config()))
    document = json.loads(json.dumps(plan.to_dict()))
    assert document["plan"] is None and document["protocol"] is None
    assert set(document["calibration"]) >= {"method", "parameters", "phases"}


PLAN_REFUSALS = [
    pytest.param(None, (ConfigError, FileNotFoundError), "", id="missing file"),
    pytest.param(TYPO_TOML, ConfigError, "", id="unreadable file"),
    pytest.param(TYPO_TOML, ConfigError, "not_a_field", id="unknown key named"),
]


@pytest.mark.parametrize(("toml", "error", "match"), PLAN_REFUSALS)
def test_plan_refusals(tmp_path: Path, toml: str | None, error: type, match: str) -> None:
    path = tmp_path / "plan.toml" if toml is None else _write_toml(tmp_path / "plan.toml", toml)

    with pytest.raises(error, match=match):
        calibration_plan(path)


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


def test_route_of_unreadable_toml(tmp_path: Path, preflights) -> None:
    config = _write_toml(tmp_path / "c.toml", TYPO_TOML)

    with pytest.raises(ConfigError, match="cannot be read"):
        route_calibration(config, phase="steady_k", environment=_Environment())


def test_plan_of_held_config(monkeypatch, tmp_path: Path) -> None:
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


@pytest.mark.parametrize(("enabled", "count"), [(True, 1), (False, 0)])
def test_session_figures_follow_display(tmp_path: Path, enabled: bool, count: int) -> None:
    from tests.unit.display._calibration_journal import journal_session

    rows = [{"trial": n, "cost": 1.0 / n, "parameters": {"K": 1e-4 * n}} for n in (1, 2, 3)]
    session = journal_session(tmp_path, rows)
    figure = {"variable": "trials.cost", "type": "series", "when": "session"}
    (session.dir / "config.toml").write_text(
        f"[display]\nenabled = {str(enabled).lower()}\n"
        f'[[display.figure]]\nvariable = "{figure["variable"]}"\n'
        f'type = "{figure["type"]}"\nwhen = "{figure["when"]}"\n',
        encoding="utf-8",
    )
    result = SimpleNamespace(session_dir=session.dir, phases=())
    assert write_session_reports(result, report=False) is result
    assert len(list((session.dir / "figures").glob("*.png"))) == count
