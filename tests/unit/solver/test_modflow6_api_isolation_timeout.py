"""The isolated api solve gets a wall-clock timeout so a stuck (non-converging)
libmf6 solve cannot wedge a parallel calibration."""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.solver.modflow6.run import (
    _API_ISOLATION_DEFAULT_TIMEOUT_S,
    _api_isolation_timeout_s,
)


def test_default_timeout_when_no_override() -> None:
    model = SimpleNamespace(runtime=SimpleNamespace())
    assert _api_isolation_timeout_s(model) == _API_ISOLATION_DEFAULT_TIMEOUT_S


def test_missing_runtime_uses_default() -> None:
    assert _api_isolation_timeout_s(SimpleNamespace()) == _API_ISOLATION_DEFAULT_TIMEOUT_S


def test_positive_override_is_honored() -> None:
    model = SimpleNamespace(runtime=SimpleNamespace(mf6_api_timeout_s=600.0))
    assert _api_isolation_timeout_s(model) == 600.0


def test_non_positive_override_disables_the_timeout() -> None:
    model = SimpleNamespace(runtime=SimpleNamespace(mf6_api_timeout_s=0))
    assert _api_isolation_timeout_s(model) is None
