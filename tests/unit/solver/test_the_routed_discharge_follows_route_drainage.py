"""The routed discharge takes the drain budget only when the network does not route the drainage.

With ``route_drainage`` the hillslope drainage reaches the network, so the routed
series is the catchment discharge and already holds the runoff. Without it the
drainage stays in DRAIN, the routed series would leave it out, and the discharge
is the routed series plus the drain budget of the catchment.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.solver.modflow_common import observable_extraction as extraction

_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")
_ROUTED = pd.Series([1.0, 1.0, 1.0], index=_INDEX)
_DRAIN = pd.Series([0.25, 0.25, 0.25], index=_INDEX)


def _model(*, route_drainage: bool | None) -> SimpleNamespace:
    payload = {} if route_drainage is None else {"route_drainage": route_drainage}
    return SimpleNamespace(flow=SimpleNamespace(sinks_sources={"sfr": {"net": payload}}))


def _serve(model: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[str]]:
    calls: list[str] = []

    def routed_reader(output_dir, model_name, time_index):
        calls.append("routed")
        return _ROUTED

    def drain_sum(output_dir, model_name, time_index, *, catchment_mask):
        calls.append("drain")
        return _DRAIN

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", drain_sum)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, unserved = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        model,
        [request],
        time_index=_INDEX,
        routed_discharge_reader=routed_reader,
    )
    assert unserved == []
    return served["catchment"], calls


def test_a_network_that_routes_the_drainage_serves_the_routed_series(monkeypatch) -> None:
    result, calls = _serve(_model(route_drainage=True), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, _ROUTED.to_numpy())


def test_a_network_that_does_not_say_routes_the_drainage(monkeypatch) -> None:
    result, calls = _serve(_model(route_drainage=None), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True


def test_a_network_that_keeps_the_drainage_out_adds_the_drain_budget(monkeypatch) -> None:
    result, calls = _serve(_model(route_drainage=False), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


def test_a_drain_budget_that_cannot_be_read_leaves_the_routed_series(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise NotImplementedError("a mover record is in the budget")

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", refuse)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, _ = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        _model(route_drainage=False),
        [request],
        time_index=_INDEX,
        routed_discharge_reader=lambda *args: _ROUTED,
    )

    np.testing.assert_allclose(served["catchment"].values, _ROUTED.to_numpy())
