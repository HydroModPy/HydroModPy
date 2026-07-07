"""Vertical anisotropy resolution for the MF6 k33 field.

A direct per-cell Kv field or the uniform kh/vka ratio, mutually exclusive, with
guardrails against the ratio-versus-value footgun and Kv > Kh.
"""

from __future__ import annotations

import numpy as np
import pytest

import hydromodpy.solver.modflow6.property_mapping as pm
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.solver.modflow6.property_mapping import resolve_k33_field


def test_uniform_ratio_divides_kh() -> None:
    hk = np.array([1e-4, 1e-5, 1e-6])
    np.testing.assert_allclose(resolve_k33_field(hk, None, 10.0), hk / 10.0)


def test_ratio_one_is_vertically_isotropic() -> None:
    hk = np.array([1e-4, 2e-5])
    np.testing.assert_allclose(resolve_k33_field(hk, None, 1.0), hk)


def test_direct_kv_field_takes_precedence() -> None:
    hk = np.full(3, 1e-4)
    kv = np.array([1e-5, 2e-5, 3e-5])
    np.testing.assert_allclose(resolve_k33_field(hk, kv, 1.0), kv)


def test_kv_field_and_nonunit_vka_is_a_conflict() -> None:
    with pytest.raises(ConfigError, match="one or the other"):
        resolve_k33_field(np.full(1, 1e-4), np.full(1, 1e-5), 5.0)


def test_kv_shape_mismatch_raises() -> None:
    with pytest.raises(ConfigError, match="does not match"):
        resolve_k33_field(np.zeros(3), np.zeros(2), 1.0)


def test_nonpositive_vka_raises() -> None:
    with pytest.raises(ConfigError, match="must be > 0"):
        resolve_k33_field(np.full(2, 1e-4), None, 0.0)


def test_kv_above_kh_warns(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    hk = np.full(2, 1e-4)
    kv = np.array([1e-5, 2e-4])  # second cell has Kv > Kh
    resolve_k33_field(hk, kv, 1.0)
    assert any("exceeds Kh" in str(c[0]) for c in calls)


def test_vka_below_one_warns_once(monkeypatch) -> None:
    pm._VKA_WARNED.clear()
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)  # deduped
    assert sum("< 1" in str(c[0]) for c in calls) == 1
