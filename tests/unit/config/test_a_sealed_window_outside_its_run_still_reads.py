"""A sealed config whose ``[metrics] window`` misses its run still reads.

A file the user loads is refused when its window shares no day with the run.
A run sealed before that refusal existed carries such a window (example 04,
``nancon_api_daily`` of 2026-10-16): re-reading it for a rerun or for
``Run.hydromodpy_config`` warns and keeps the run, which has no score.
"""

from __future__ import annotations

import logging
import tomllib

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.results.run import Run

pytestmark = pytest.mark.unit

SEALED = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "sealed_window_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[metrics]
window = { start = "2001-01-01", end = "2002-12-31" }
"""


def _snapshot() -> dict:
    return tomllib.loads(SEALED)


def test_a_user_document_with_the_window_is_still_refused() -> None:
    with pytest.raises(ConfigValidationError, match=r"\[metrics\] window"):
        HydroModPyConfig.from_dict(_snapshot())


def test_a_snapshot_reads_with_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        cfg = HydroModPyConfig.from_snapshot(_snapshot())

    assert cfg.metrics.window.start.isoformat() == "2001-01-01"
    assert "shares no day" in caplog.text


def test_a_sealed_run_rebuilds_its_config(monkeypatch, caplog) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(Run, "config_snapshot", property(lambda self: snapshot))
    run = Run.__new__(Run)
    run._sim_id = "0123456789abcdef"

    with caplog.at_level(logging.WARNING):
        cfg = run.hydromodpy_config

    assert cfg.metrics.window.end.isoformat() == "2002-12-31"
    assert "shares no day" in caplog.text


def test_the_provider_reads_a_sealed_document() -> None:
    cfg = get_root_config_provider().from_dict(_snapshot(), sealed=True)

    assert cfg.simulation.time.end_datetime.year == 2020
