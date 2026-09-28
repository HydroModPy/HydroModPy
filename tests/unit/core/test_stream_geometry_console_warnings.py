"""The two warnings a network criterion build prints, as a reader meets them.

A calibration builds the criterion geometry once per trial and once per
promoted run. The recharge warning fired on float noise between two builds of
one session (9.074855002572016e-09 then 9.074854999999997e-09), and the alpha
warning printed the same five lines at every build.
"""

from __future__ import annotations

import logging

import pytest

from hydromodpy.core import stream_geometry


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a new process: no recharge seen, no alpha warned."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", None)
    monkeypatch.setattr(stream_geometry, "_alpha_warned", False)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_float_noise_between_two_builds_is_not_a_move(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._warn_if_recharge_moved(9.074855002572016e-09)
        stream_geometry._warn_if_recharge_moved(9.074854999999997e-09)

    assert _warnings(caplog) == []


def test_a_real_move_warns_with_four_significant_digits(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._warn_if_recharge_moved(9.074854999999997e-09)
        stream_geometry._warn_if_recharge_moved(8.655624187444443e-09)

    (message,) = _warnings(caplog)
    assert "9.075e-09 then 8.656e-09 m/s" in message


def test_a_move_just_above_the_tolerance_still_warns(caplog) -> None:
    base = 1.0e-8
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._warn_if_recharge_moved(base)
        stream_geometry._warn_if_recharge_moved(
            base * (1.0 + 10 * stream_geometry.RECHARGE_MOVE_TOLERANCE)
        )

    assert len(_warnings(caplog)) == 1


def test_the_alpha_warning_prints_once_then_goes_to_verbose(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._report_poor_alpha(0.780, 0.90)
        stream_geometry._report_poor_alpha(0.777, 0.90)
        stream_geometry._report_poor_alpha(0.781, 0.90)

    (message,) = _warnings(caplog)
    assert "alpha_obs_closure_catchment = 0.780, below 0.90" in message
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 2
    assert "0.777" in infos[0].getMessage()


def test_the_alpha_warning_says_it_in_two_sentences(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=stream_geometry.__name__):
        stream_geometry._report_poor_alpha(0.780, 0.90)

    (message,) = _warnings(caplog)
    assert message.count(". ") == 1
    assert message.endswith(".")
