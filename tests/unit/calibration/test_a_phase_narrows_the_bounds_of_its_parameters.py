"""A phase may write its own ``bounds``, inside the ones ``[calibration]`` declares.

A broad first phase and a narrow second one used to need two sections. Now a
phase writes ``bounds = { K = [1e-6, 1e-4] }`` for the parameters it moves. They
have to lie inside the section's bounds: refused at load against the bounds the
file writes, and again before the first solve against the resolved ones (a
field's own range when the section writes none).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.staged_runner import _phase_config, phase_summaries
from hydromodpy.core.exceptions import ConfigValidationError

PARAMETERS = {
    "K": {"bounds": [1e-7, 1e-3], "search_space": "log"},
    "Sy": {"bounds": [0.005, 0.35], "search_space": "log"},
}


def _phase(name: str = "k", **fields: Any) -> dict[str, Any]:
    return {"name": name, "parameters": ["K"], "objective": "nse", **fields}


def _cfg(*phases: dict[str, Any], parameters: dict | None = None) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {"parameters": parameters or PARAMETERS, "phases": list(phases) or [_phase()]}
    )


def test_a_phase_takes_no_bounds_by_default() -> None:
    assert _cfg().phases[0].bounds is None


def test_a_phase_writes_its_bounds_inside_the_section_bounds() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))

    assert cfg.phases[0].bounds == {"K": [1e-6, 1e-4]}


def test_bounds_equal_to_the_section_bounds_are_inside() -> None:
    assert _cfg(_phase(bounds={"K": [1e-7, 1e-3]})).phases[0].bounds == {"K": [1e-7, 1e-3]}


@pytest.mark.parametrize(
    ("bounds", "reason"),
    [
        ({"K": [1e-8, 1e-4]}, r"\[1e-08, 0.0001\].*\[1e-07, 0.001\]"),
        ({"K": [1e-6, 1e-2]}, r"\[1e-06, 0.01\].*\[1e-07, 0.001\]"),
        ({"Sy": [0.01, 0.2]}, "'Sy', which it does not move"),
        ({"K": [1e-4, 1e-6]}, "lower bound must be below the upper"),
        ({"K": [1e-6, 1e-6]}, "lower bound must be below the upper"),
        ({"K": [1e-6]}, "two values"),
        ({"K": [1e-6, 1e-5, 1e-4]}, "two values"),
    ],
)
def test_a_phase_bounds_that_cannot_hold_are_refused_when_the_file_loads(
    bounds: dict[str, list[float]], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        _cfg(_phase(bounds=bounds))


def test_the_refusal_names_the_phase_and_the_parameter() -> None:
    with pytest.raises(ValidationError, match="phase 'k'.*'K'"):
        _cfg(_phase(bounds={"K": [1e-8, 1e-4]}))


def test_a_phase_writes_its_bounds_into_the_calibration_it_runs() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parameters["K"].bounds == [1e-6, 1e-4]
    assert cfg.parameters["K"].bounds == [1e-7, 1e-3]


def test_a_phase_without_bounds_runs_the_section_bounds() -> None:
    cfg = _cfg()

    assert _phase_config(cfg, cfg.phases[0]).parameters["K"].bounds == [1e-7, 1e-3]


def test_bounds_written_below_the_resolved_bounds_are_refused_before_the_first_solve() -> None:
    """The section writes none; the catalog's range, filled in after load, is the frame."""
    cfg = _cfg(
        _phase(bounds={"K": [1e-8, 1e-4]}),
        parameters={"K": {"search_space": "log"}},
    )
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    with pytest.raises(ConfigValidationError, match=r"\[1e-08, 0.0001\].*\[1e-07, 0.001\]"):
        _phase_config(cfg, cfg.phases[0])


def test_bounds_inside_the_resolved_bounds_run() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}), parameters={"K": {"search_space": "log"}})
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    assert _phase_config(cfg, cfg.phases[0]).parameters["K"].bounds == [1e-6, 1e-4]


def test_the_preflight_refuses_bounds_outside_the_resolved_ones() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    cfg.parameters["K"].bounds = [1e-5, 1e-3]

    class _Config:
        calibration = cfg

    findings = preflight_calibration(_Config(), source=Path("calibration.toml"))
    refused = [finding for finding in findings if "bounds" in finding.where]

    assert [finding.severity for finding in refused] == ["error"]
    assert "[1e-05, 0.001]" in refused[0].detail


def test_list_phases_prints_the_bounds_of_a_phase() -> None:
    from hydromodpy.cli.commands.calibrate import _phase_line

    cfg = _cfg(_phase("wide"), _phase("narrow", bounds={"K": [1e-6, 1e-4]}))
    wide, narrow = phase_summaries(cfg)

    assert "bounds" not in wide
    assert narrow["bounds"] == {"K": [1e-6, 1e-4]}
    assert "bounds K [1e-06, 0.0001]" in _phase_line(1, narrow)
    assert "bounds" not in _phase_line(0, wide)
