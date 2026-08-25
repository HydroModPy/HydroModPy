"""The isolated api solve gets a wall-clock timeout so a stuck (non-converging)
libmf6 solve cannot wedge a parallel calibration."""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.solver.modflow6.modflow6_config import Modflow6RuntimeConfig
from hydromodpy.solver.modflow6.run import (
    _API_ISOLATION_DEFAULT_TIMEOUT_S,
    _api_isolation_timeout_s,
)


def _model(runtime: Modflow6RuntimeConfig) -> SimpleNamespace:
    # The runner reads the override off model.modflow_config.runtime, the shape
    # production actually builds (not a fabricated model.runtime).
    return SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))


def test_default_timeout_when_no_override() -> None:
    assert _api_isolation_timeout_s(_model(Modflow6RuntimeConfig())) == (
        _API_ISOLATION_DEFAULT_TIMEOUT_S
    )


def test_missing_runtime_uses_default() -> None:
    assert _api_isolation_timeout_s(SimpleNamespace()) == _API_ISOLATION_DEFAULT_TIMEOUT_S


def test_positive_override_is_honored() -> None:
    runtime = Modflow6RuntimeConfig(mf6_api_timeout_s=600.0)
    assert _api_isolation_timeout_s(_model(runtime)) == 600.0


def test_field_survives_extra_forbid() -> None:
    # mf6_api_timeout_s is a real config field, so the override reaches the runner
    # instead of being rejected at TOML load by extra="forbid".
    runtime = Modflow6RuntimeConfig(mf6_api_timeout_s=600.0)
    assert runtime.mf6_api_timeout_s == 600.0
