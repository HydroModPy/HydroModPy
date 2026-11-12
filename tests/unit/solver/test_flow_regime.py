from __future__ import annotations

from hydromodpy.model.flow_config import FlowConfig


class _Window:
    start = None


class _TimeGrid:
    period_lengths_seconds = [86400.0, 86400.0]
    window = _Window()


def test_flow_config_steady_constructor_returns_steady_config() -> None:
    cfg = FlowConfig.steady(K=5e-5)
    assert cfg.flow_regime == "steady"
    assert cfg.param_list == ["K"]
