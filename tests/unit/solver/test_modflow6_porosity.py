"""WP8 - effective porosity drives MST and PRT, not specific yield.

Pore velocity is v = q / n, where n is total porosity. Specific yield Sy is the
gravity-drainable fraction and is smaller than n, so using Sy overstates solute
and particle speed. A configured porosity wins; the Sy fallback warns.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.transport.transport_config import ConcentrationTransportParametersConfig
from hydromodpy.solver.modflow6.prt import _PRT_DEFAULT_POROSITY, Modflow6Prt
from hydromodpy.solver.modflow6.transport import Modflow6Transport


def test_concentration_config_porosity_field_validates() -> None:
    assert ConcentrationTransportParametersConfig().porosity is None
    assert ConcentrationTransportParametersConfig(porosity=0.3).porosity == 0.3
    for bad in (0.0, 1.5):
        with pytest.raises(Exception):
            ConcentrationTransportParametersConfig(porosity=bad)
    with pytest.raises(Exception):
        ConcentrationTransportParametersConfig(unknown_key=1.0)


def _gwt(porosity, *, nlay, ncpl, sy) -> Modflow6Transport:
    transport_solver = object.__new__(Modflow6Transport)
    transport_solver.porosity = porosity
    transport_solver.model_modflow = SimpleNamespace(nlay=nlay, ncpl=ncpl, sy=np.asarray(sy))
    return transport_solver


def test_mf6_gwt_mst_uses_configured_porosity_not_sy() -> None:
    solver = _gwt(0.30, nlay=2, ncpl=3, sy=np.full((2, 3), 0.05))
    assert solver._resolve_mst_porosity() == pytest.approx(0.30)


def test_mf6_gwt_mst_falls_back_to_sy_with_warning() -> None:
    solver = _gwt(None, nlay=1, ncpl=3, sy=np.full((1, 3), 0.12))
    with pytest.warns(UserWarning):
        porosity = solver._resolve_mst_porosity()
    assert np.asarray(porosity).shape == (1, 3)
    np.testing.assert_allclose(porosity, 0.12)


def _prt(porosity, *, nlay, ncpl, sy) -> Modflow6Prt:
    prt_solver = object.__new__(Modflow6Prt)
    prt_solver.porosity = porosity
    prt_solver.model_modflow = SimpleNamespace(nlay=nlay, ncpl=ncpl, sy=np.asarray(sy))
    return prt_solver


def test_mf6_prt_porosity_warns_on_sy_fallback_and_uses_named_default() -> None:
    # A: no porosity, non-positive Sy -> named default, with a warning.
    solver_a = _prt(None, nlay=1, ncpl=2, sy=np.zeros((1, 2)))
    with pytest.warns(UserWarning):
        out_a = solver_a._build_porosity()
    np.testing.assert_allclose(out_a, _PRT_DEFAULT_POROSITY)
    assert out_a.shape == (1, 2)

    # B: no porosity, positive Sy -> Sy, with a warning.
    solver_b = _prt(None, nlay=1, ncpl=2, sy=np.full((1, 2), 0.18))
    with pytest.warns(UserWarning):
        out_b = solver_b._build_porosity()
    np.testing.assert_allclose(out_b, 0.18)

    # C: configured porosity -> no warning, no Sy.
    import warnings as _warnings

    solver_c = _prt(0.25, nlay=1, ncpl=2, sy=np.full((1, 2), 0.05))
    with _warnings.catch_warnings():
        _warnings.simplefilter("error")
        out_c = solver_c._build_porosity()
    np.testing.assert_allclose(out_c, 0.25)
    assert out_c.shape == (1, 2)
