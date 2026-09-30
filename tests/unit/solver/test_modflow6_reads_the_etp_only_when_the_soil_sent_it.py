"""MODFLOW 6 draws ETP from the water table only when the soil marked it.

Outside soil mode ``"etp"`` in ``flow.active_sinks_sources`` has never driven a
MODFLOW 6 package: this stays true, with one warning added so a project that
lists it is not silently ignored.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from hydromodpy.solver.modflow6.builders.recharge import (
    ETP_IGNORED_OUTSIDE_SOIL_MODE,
    bind_soil_etp_from_flow,
)


class _Quantity:
    """Minimal stand-in for the pint quantity ``surface_offset``/``extinction_depth`` hold."""

    def __init__(self, magnitude: float) -> None:
        self._magnitude = magnitude

    def to(self, unit: str) -> _Quantity:
        assert unit == "m"
        return self

    @property
    def magnitude(self) -> float:
        return self._magnitude


def _model(*, active: list[str], etp_cfg: object | None) -> SimpleNamespace:
    sinks_sources = {} if etp_cfg is None else {"etp": etp_cfg}
    return SimpleNamespace(
        flow=SimpleNamespace(active_sinks_sources=active, sinks_sources=sinks_sources)
    )


def test_an_unmarked_etp_is_ignored_and_warned_about(caplog: pytest.LogCaptureFixture) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source="a grid")
    model = _model(active=["etp"], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text


def test_the_soil_marked_etp_is_bound(caplog: pytest.LogCaptureFixture) -> None:
    source = object()
    etp_cfg = SimpleNamespace(
        from_soil_reservoir=True,
        heterogeneous_source=source,
        interpolation_method="linear",
        surface_offset=_Quantity(0.3),
        extinction_depth=_Quantity(1.5),
    )
    model = _model(active=["etp"], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is source
    assert model._soil_etp_interpolation_method == "linear"
    assert model._soil_evt_surface_offset_m == pytest.approx(0.3)
    assert model._soil_evt_extinction_depth_m == pytest.approx(1.5)
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE not in caplog.text


def test_an_inactive_etp_binds_nothing_and_warns_nothing(caplog: pytest.LogCaptureFixture) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=object())
    model = _model(active=[], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert caplog.text == ""


def test_a_soil_marked_etp_without_its_grid_is_a_bug() -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=None)
    model = _model(active=["etp"], etp_cfg=etp_cfg)

    with pytest.raises(RuntimeError, match="without its grid"):
        bind_soil_etp_from_flow(model)
