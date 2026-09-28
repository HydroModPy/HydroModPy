"""Eq. 4 in ``apply`` mode: Doptim on the snapped map, plus the displacement bound.

A snapped map can pass its validity length by construction, which is why the verdict read
at the returned trial also asks the snap not to have moved the map further
than ``max_displacement_p90`` nor rejected more than ``max_rejected_share``.
``diagnose`` scores the raw map and adds nothing to the verdict.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.observations.network_geometry import snap_settings
from hydromodpy.calibration.runners.cli_runner import _roptim_verdict_extra
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.stream_snap import SnapStreamsConfig


def _output(on_violation: str = "warn") -> SimpleNamespace:
    return SimpleNamespace(support="network", on_roptim_violation=on_violation)


def _components(mode: float, *, p90: float, rejected: float) -> dict[str, float]:
    return {
        "net.roptim": 1.2,
        "net.L_ref": 75.0,
        "net.Doptim": 90.0,
        "net.validity_length_m": 150.0,
        "net.validity_length_provenance": 0.0,
        "net.snap_mode": mode,
        "net.snap_displacement_p90_m": p90,
        "net.snap_displacement_bound_m": 75.0,
        "net.snap_rejected_share": rejected,
        "net.snap_rejected_share_max": 0.10,
        "net.snap_floor_m": 30.0,
    }


def test_apply_within_its_bounds_is_valid() -> None:
    verdict = _roptim_verdict_extra({"net": _output()}, _components(2.0, p90=75.0, rejected=0.05))[
        "roptim_verdict"
    ]["net"]

    assert verdict["valid"] is True
    assert verdict["snap"]["valid"] is True
    assert verdict["snap"]["floor_m"] == pytest.approx(30.0)


@pytest.mark.parametrize(("p90", "rejected"), [(80.0, 0.05), (50.0, 0.2)])
def test_apply_beyond_a_bound_is_invalid_although_roptim_passes(caplog, p90, rejected) -> None:
    verdict = _roptim_verdict_extra(
        {"net": _output()}, _components(2.0, p90=p90, rejected=rejected)
    )["roptim_verdict"]["net"]

    assert verdict["valid"] is False
    assert verdict["causes"] == ["snap"]
    assert verdict["snap"]["valid"] is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("moved the map too far" in message for message in messages)
    assert not any("exceeds the validity length" in message for message in messages)


def test_apply_failing_both_names_both_causes(caplog) -> None:
    components = {**_components(2.0, p90=80.0, rejected=0.0), "net.Doptim": 200.0}

    verdict = _roptim_verdict_extra({"net": _output()}, components)["roptim_verdict"]["net"]

    assert verdict["causes"] == ["doptim", "snap"]
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "exceeds the validity length 150 m" in message
    assert "moved the map too far" in message


def test_apply_beyond_a_bound_stops_a_strict_calibration() -> None:
    with pytest.raises(CalibrationError, match="moved the map too far"):
        _roptim_verdict_extra({"net": _output("error")}, _components(2.0, p90=80.0, rejected=0.0))


def test_diagnose_adds_nothing_to_the_verdict() -> None:
    verdict = _roptim_verdict_extra({"net": _output()}, _components(1.0, p90=500.0, rejected=0.9))[
        "roptim_verdict"
    ]["net"]

    assert verdict["valid"] is True
    assert "snap" not in verdict


def test_a_trial_without_a_snap_is_read_as_before() -> None:
    components = {
        "net.roptim": 2.5,
        "net.L_ref": 75.0,
        "net.Doptim": 187.5,
        "net.validity_length_m": 150.0,
    }
    verdict = _roptim_verdict_extra({"net": _output()}, components)["roptim_verdict"]["net"]

    assert verdict["valid"] is False
    assert "snap" not in verdict


def test_the_criterion_reads_the_snap_from_the_run_configuration() -> None:
    def run_ctx(setting):
        cfg = SimpleNamespace(geographic=SimpleNamespace(snap_streams=setting))
        return SimpleNamespace(state=SimpleNamespace(cfg=cfg))

    assert snap_settings(run_ctx(SnapStreamsConfig())) is None
    applied = SnapStreamsConfig(mode="apply")
    assert snap_settings(run_ctx(applied)) is applied
    assert snap_settings(SimpleNamespace(state=SimpleNamespace(cfg=None))) is None


def test_two_bounds_read_the_snap_of_each_bound() -> None:
    # A two-bound output publishes every map component under its bound's
    # suffix and no unsuffixed roptim: each bound gets its own snap verdict.
    components = {"net.n_bounds_scored": 2.0, "net.weight_minimal": 0.5, "net.weight_maximal": 0.5}
    for suffix, p90 in (("_minimal", 80.0), ("_maximal", 50.0)):
        one = _components(2.0, p90=p90, rejected=0.0)
        components.update({f"{key}{suffix}": value for key, value in one.items()})

    verdicts = _roptim_verdict_extra({"net": _output()}, components)["roptim_verdict"]

    assert set(verdicts) == {"net_minimal", "net_maximal"}
    assert verdicts["net_minimal"]["valid"] is False
    assert verdicts["net_minimal"]["snap"]["valid"] is False
    assert verdicts["net_maximal"]["valid"] is True
    assert verdicts["net_maximal"]["snap"]["floor_m"] == pytest.approx(30.0)
