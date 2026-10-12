"""A run that declares wells but kept no well field says which key to set.

The overlay reads the well budget field, which a run keeps unless
``[simulation.results] keep_per_cell_budget`` is false and no consumer asked
for it. Without it the overlay used to vanish with one INFO line, and a reader
took the wells for absent.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from hydromodpy.display.maps.overlays import OverlayUnavailable, apply_overlays, draw_wells

WELLS = {"W1": {"location": {"kind": "absolute_xy", "x": 1.0, "y": 2.0}, "flux": -0.01}}


def _run(snapshot: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        sim_id="sim-wells",
        has_field=lambda variable, **_: False,
        config_snapshot=snapshot,
    )


def test_a_run_that_declares_wells_is_told_the_key_to_set() -> None:
    run = _run({"flow": {"sinks_sources": {"wells": WELLS}}})

    with pytest.raises(OverlayUnavailable) as raised:
        draw_wells(None, run)

    assert raised.value.actionable
    assert "[simulation.results] keep_per_cell_budget = true" in str(raised.value)
    assert "declares wells" in str(raised.value)


def test_the_skip_is_a_warning_when_the_user_can_fix_it(caplog) -> None:
    run = _run({"flow": {"sinks_sources": {"wells": WELLS}}})

    with caplog.at_level(logging.INFO):
        drawn = apply_overlays(None, run, ["wells"])

    assert drawn == []
    (record,) = [r for r in caplog.records if "Overlay 'wells'" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "keep_per_cell_budget = true" in record.getMessage()


@pytest.mark.parametrize(
    "snapshot",
    [None, {}, {"flow": {"sinks_sources": {}}}, {"flow": {"sinks_sources": {"wells": {}}}}],
)
def test_a_run_without_wells_stays_a_quiet_skip(caplog, snapshot) -> None:
    with caplog.at_level(logging.INFO):
        drawn = apply_overlays(None, _run(snapshot), ["wells"])

    assert drawn == []
    (record,) = [r for r in caplog.records if "Overlay 'wells'" in r.getMessage()]
    assert record.levelno == logging.INFO
    assert "keep_per_cell_budget" not in record.getMessage()
