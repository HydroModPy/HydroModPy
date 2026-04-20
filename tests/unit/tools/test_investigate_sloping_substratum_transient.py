from __future__ import annotations

import numpy as np

from tools import investigate_sloping_substratum_transient as case


def test_sloping_profiles_keep_positive_thickness() -> None:
    x = np.linspace(0.0, case.LENGTH_X_M, 41, dtype=float)
    top = case.build_topography_profile(x)
    bottom = case.build_bottom_profile(x)
    assert top.shape == x.shape
    assert bottom.shape == x.shape
    assert np.all(top > bottom)


def test_sloping_profiles_match_declared_boundary_values() -> None:
    top = case.build_topography_profile(np.asarray([0.0, case.LENGTH_X_M], dtype=float))
    bottom = case.build_bottom_profile(np.asarray([0.0, case.LENGTH_X_M], dtype=float))
    assert np.isclose(top[1], case.TOPOGRAPHY_BASE_ELEVATION_M)
    assert np.isclose(bottom[1], case.BOTTOM_BASE_ELEVATION_M)
    assert np.isclose(top[0] - top[1], case.TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M)
    assert np.isclose(bottom[0] - bottom[1], case.BOTTOM_RIGHT_TO_LEFT_AMPLITUDE_M)


def test_structured_sloping_surfaces_match_declared_shape_and_ordering() -> None:
    top = case._build_structured_topography_array()
    bottom = case._build_structured_bottom_array()
    assert top.shape == (case.STRUCTURED_NY, case.STRUCTURED_NX)
    assert bottom.shape == (case.STRUCTURED_NY, case.STRUCTURED_NX)
    assert np.all(top > bottom)
