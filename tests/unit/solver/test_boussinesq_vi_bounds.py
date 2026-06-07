from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtimes.vi_bounds import variable_bounds
from tests._helpers.mesh_doubles import _MiniMesh


def test_vi_bounds_relax_upper_obstacle_for_explicit_cauchy_drainage() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    _, upper_without_drainage, _ = variable_bounds(mesh, None)
    _, upper_with_drainage, _ = variable_bounds(
        mesh,
        None,
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(upper_without_drainage, mesh.z_top_m)
    assert np.all(upper_with_drainage > 1.0e20)


def test_vi_bounds_keep_upper_obstacle_when_drainage_conductance_is_zero() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    _, upper_with_zero_drainage, _ = variable_bounds(
        mesh,
        None,
        drainage_conductance_m2_s=0.0,
    )

    np.testing.assert_allclose(upper_with_zero_drainage, mesh.z_top_m)


def test_vi_bounds_keep_prescribed_heads_fixed_with_relaxed_drainage() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    lower, upper, mask = variable_bounds(
        mesh,
        np.asarray([np.nan, 2.5], dtype=float),
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(lower, np.asarray([0.0, 2.5]))
    assert upper[0] > 1.0e20
    assert upper[1] == pytest.approx(2.5)
    np.testing.assert_array_equal(mask, np.asarray([False, True]))
