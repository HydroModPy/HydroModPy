"""Eq. 4 is read once, on the trial the search returns.

The paper reads ``roptim <= 2`` at the optimum ("At this point", HESS 27,
p. 3225). A trial on the way to the root is not the result, so every trial
keeps ``roptim`` and its validity length as components and only the report
qualifies the answer. The bound is a length: ``Doptim <= validity_length_m``.
"""

from __future__ import annotations

import logging
import math

import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.cli_runner import _roptim_verdict_extra
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.stream_geometry import VALIDITY_PROVENANCE_CODE
from tests.unit.calibration.test_staged_runner import TWO_PHASES, FakeRunner, _write


def _network(**overrides):
    return validate_calib_output(
        {"support": "network", "stream_geometry_path": "streams.gpkg", **overrides}
    )


def _components(
    roptim: float,
    *,
    name: str = "net",
    length: float = 150.0,
    provenance: str = "auto",
) -> dict[str, float]:
    return {
        f"{name}.roptim": roptim,
        f"{name}.L_ref": 75.0,
        f"{name}.Doptim": 75.0 * roptim,
        f"{name}.validity_length_m": length,
        f"{name}.validity_length_provenance": VALIDITY_PROVENANCE_CODE[provenance],
    }


def test_a_returned_trial_inside_the_bound_is_recorded_valid(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        extra = _roptim_verdict_extra({"net": _network()}, _components(1.5))

    assert extra["roptim_verdict"]["net"] == {
        "value": 1.5,
        "Doptim": 112.5,
        "h_obs_m": 75.0,
        "validity_length_m": 150.0,
        "provenance": "auto",
        "valid": True,
        "causes": [],
    }
    assert "Eq. 4" not in caplog.text


def test_a_returned_trial_past_the_bound_warns_once_by_default(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        extra = _roptim_verdict_extra({"net": _network()}, _components(5.31))

    verdict = extra["roptim_verdict"]["net"]
    assert verdict["valid"] is False and verdict["causes"] == ["doptim"]
    warnings = [record for record in caplog.records if "Eq. 4" in record.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "Doptim = 398.2 m exceeds the validity length 150 m (auto)" in message
    assert "roptim = 5.31 cells of h_obs" in message


def test_the_verdict_reads_the_length_the_trial_published_not_a_ratio() -> None:
    # A declared accuracy of 50 m on a 25 m grid: roptim = 3 cells of h_obs,
    # past two cells, and still inside 2 * 50 m.
    components = {
        "net.roptim": 3.0,
        "net.L_ref": 25.0,
        "net.Doptim": 75.0,
        "net.validity_length_m": 100.0,
        "net.validity_length_provenance": VALIDITY_PROVENANCE_CODE["declared_accuracy"],
    }

    verdict = _roptim_verdict_extra({"net": _network()}, components)["roptim_verdict"]["net"]

    assert verdict["valid"] is True
    assert verdict["provenance"] == "declared_accuracy"


def test_strict_mode_raises_a_calibration_error_on_the_returned_trial() -> None:
    output = _network(on_roptim_violation="error")

    with pytest.raises(CalibrationError, match="exceeds the validity length 150 m"):
        _roptim_verdict_extra({"net": output}, _components(5.31))


def test_strict_mode_accepts_a_returned_trial_inside_the_bound() -> None:
    output = _network(on_roptim_violation="error", validity_length="225 m")

    extra = _roptim_verdict_extra(
        {"net": output}, _components(2.5, length=225.0, provenance="user")
    )

    assert extra["roptim_verdict"]["net"]["valid"] is True
    assert extra["roptim_verdict"]["net"]["provenance"] == "user"


def test_an_empty_network_at_the_returned_trial_is_not_qualified() -> None:
    extra = _roptim_verdict_extra({"net": _network()}, _components(math.nan))

    verdict = extra["roptim_verdict"]["net"]
    assert verdict["value"] is None and verdict["valid"] is False
    assert verdict["causes"] == ["empty"]
    with pytest.raises(CalibrationError, match="not a number"):
        _roptim_verdict_extra({"net": _network(on_roptim_violation="error")}, _components(math.nan))


def test_a_trial_without_a_published_length_is_not_qualified() -> None:
    components = {"net.roptim": 1.0, "net.L_ref": 75.0, "net.Doptim": 75.0}

    verdict = _roptim_verdict_extra({"net": _network()}, components)["roptim_verdict"]["net"]

    assert verdict["valid"] is False and verdict["validity_length_m"] is None


def test_each_network_output_gets_its_own_verdict() -> None:
    outputs = {"a": _network(), "b": _network(validity_length="750 m")}
    components = {
        **_components(3.0, name="a"),
        **_components(3.0, name="b", length=750.0, provenance="user"),
    }

    verdicts = _roptim_verdict_extra(outputs, components)["roptim_verdict"]

    assert (verdicts["a"]["valid"], verdicts["b"]["valid"]) == (False, True)


def test_nothing_is_published_without_a_network_output_or_a_best_trial() -> None:
    assert _roptim_verdict_extra({"net": _network()}, None) == {}
    assert _roptim_verdict_extra(None, _components(1.0)) == {}


class _StrictFirstPhase(FakeRunner):
    """The first phase fails Eq. 4 in strict mode, after its session is saved."""

    def run_calibration_core(self, cfg, trial_ctx, **kwargs):
        report = super().run_calibration_core(cfg, trial_ctx, **kwargs)
        if len(self.calls) == 1:
            raise CalibrationError("roptim = 5.31 exceeds the bound 2")
        return report


def test_a_strict_violation_stops_a_staged_run_before_it_freezes(tmp_path, monkeypatch) -> None:
    fake = _StrictFirstPhase()
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    with pytest.raises(CalibrationError, match="roptim"):
        run_staged_calibration(_write(tmp_path, TWO_PHASES))

    # The dependent phase never ran, so nothing was calibrated on a K the
    # bound refused.
    assert fake.phases_run == ["steady_k"]
