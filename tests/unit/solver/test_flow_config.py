"""Flow regime and calibrated parameter list of a FlowConfig."""

from __future__ import annotations

from hydromodpy.model.flow_config import FlowConfig


def test_steady_constructor():
    cfg = FlowConfig.steady(K=5e-5)
    assert cfg.flow_regime == "steady"
    assert cfg.param_list == ["K"]
