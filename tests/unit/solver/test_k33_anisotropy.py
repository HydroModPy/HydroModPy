"""Vertical anisotropy resolution for the MF6 k33 field.

A direct per-cell Kv field or the uniform kh/vka ratio, mutually exclusive, with
guardrails against the ratio-versus-value footgun and Kv > Kh.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.solver.modflow6.support.property_mapping as pm
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.solver.modflow6.support.property_mapping import resolve_k33_field
from hydromodpy.solver.modflow6.support.runtime_reuse import (
    refresh_reused_runtime_property_packages,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.core.field_param import FieldParam
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


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


class _Array:
    def __init__(self) -> None:
        self.data = None

    def set_data(self, data) -> None:
        self.data = np.asarray(data, dtype=float)


def _reused_model(*, kv: float | None, vka: float):
    parameters = {"K": FieldParam(identifier="K", kind="homogeneous", value=1e-4)}
    if kv is not None:
        parameters["Kv"] = FieldParam(identifier="Kv", kind="homogeneous", value=kv)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.stack([np.full((2, 3), 5.0), np.zeros((2, 3))]),
    )
    return SimpleNamespace(
        flow=SimpleNamespace(parameters=parameters),
        domain=SimpleNamespace(zones={}),
        solver_mesh=solver_mesh,
        flow_regime="steady",
        modflow_config=SimpleNamespace(process_specific=SimpleNamespace(vka=vka)),
        npf=SimpleNamespace(k=_Array(), k33=_Array()),
        sto=None,
        drn=None,
        lak=None,
    )


@pytest.mark.parametrize(("kv", "vka", "expected"), [(2e-5, 1.0, 2e-5), (None, 4.0, 2.5e-5)])
def test_a_reused_runtime_keeps_the_k33_rule_of_the_first_build(kv, vka, expected) -> None:
    """A calibration trial refreshes k33 like the build: a Kv field wins over k / vka."""
    model = _reused_model(kv=kv, vka=vka)

    updated = refresh_reused_runtime_property_packages(model, flow_runtime_overrides=None)

    assert updated == ("npf",)
    assert model.npf.k.data.shape == (2, 6)
    np.testing.assert_allclose(model.npf.k.data, 1e-4)
    np.testing.assert_allclose(model.npf.k33.data, expected)
