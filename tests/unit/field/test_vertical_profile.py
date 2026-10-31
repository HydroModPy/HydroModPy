"""The depth factor of a field parameter, :mod:`hydromodpy.spatial.field.vertical_profile`."""

import numpy as np
import pytest

from hydromodpy.spatial.field.field_param import FieldParam


@pytest.mark.parametrize(
    ("profile", "depths", "factors"),
    [
        (None, [0.0, 50.0], [1.0, 1.0]),
        ({"mode": "none"}, [0.0, 50.0], [1.0, 1.0]),
        ({"mode": "exponential", "characteristic_depth": 20.0}, [0.0, 20.0], [1.0, np.exp(-1.0)]),
        ({"mode": "exponential", "characteristic_depth": "0.02 km"}, [10.0], [np.exp(-0.5)]),
        ({"mode": "exponential", "characteristic_depth": 5.0, "min_factor": 0.2}, [0.0, 1000.0], [1.0, 0.2]),
        ({"mode": "tabulated", "depths": [0.0, 20.0, 40.0], "factors": [1.0, 0.5, 0.25]},
         [10.0, 30.0, 80.0], [0.75, 0.375, 0.25]),
        ({"mode": "tabulated", "depths": [0, 10], "factors": [1, 0.5], "interpolation": "step"},
         [0.0, 5.0, 10.0, 20.0], [1.0, 1.0, 0.5, 0.5]),
    ],
    ids=["no-profile", "none", "exponential", "depth-in-km", "floor", "tabulated", "step"],
)  # fmt: skip
def test_a_vertical_profile_scales_the_surface_value_with_depth(profile, depths, factors):
    param = FieldParam(identifier="K", kind="homogeneous", value=10.0, vertical_profile=profile)

    assert param.has_vertical_variation is (profile is not None and profile["mode"] != "none")
    np.testing.assert_allclose(param.vertical_factor(np.array(depths)), factors)
    np.testing.assert_allclose(
        param.to_array(shape=(len(depths),), depth=np.array(depths)), 10.0 * np.array(factors)
    )
    assert float(param.to_array(depth=depths[-1])) == pytest.approx(10.0 * factors[-1])


def _tabulated(**override) -> dict:
    return {"mode": "tabulated", "depths": [0.0, 10.0], "factors": [1.0, 0.5]} | override


@pytest.mark.parametrize(
    ("profile", "error", "match"),
    [
        (["exponential"], TypeError, "must be a mapping"),
        ({"mode": "linear"}, ValueError, "Unsupported vertical profile mode 'linear'"),
        ({"mode": "exponential"}, KeyError, "requires 'characteristic_depth'"),
        ({"mode": "exponential", "characteristic_depth": None}, ValueError, "cannot be None"),
        ({"mode": "exponential", "characteristic_depth": True}, TypeError, "rejects boolean"),
        ({"mode": "exponential", "characteristic_depth": " "}, ValueError, "empty length string"),
        ({"mode": "exponential", "characteristic_depth": [1]}, TypeError, "unsupported length"),
        ({"mode": "exponential", "characteristic_depth": 0.0}, ValueError, "must be > 0"),
        ({"mode": "exponential", "characteristic_depth": 9, "min_factor": "nan"}, ValueError, "finite"),
        ({"mode": "exponential", "characteristic_depth": 9, "min_factor": 1.2}, ValueError, r"\[0, 1\]"),
        ({"mode": "tabulated", "factors": [1.0]}, KeyError, "requires 'depths'"),
        ({"mode": "tabulated", "depths": [0.0]}, KeyError, "requires 'factors'"),
        (_tabulated(depths=[], factors=[]), ValueError, "cannot be empty"),
        (_tabulated(depths=[0.0]), ValueError, "same length"),
        (_tabulated(factors=[1.0, np.inf]), ValueError, "must be finite"),
        (_tabulated(depths=[-1.0, 10.0]), ValueError, "must be >= 0"),
        (_tabulated(depths=[0.0, 0.0]), ValueError, "strictly increasing"),
        (_tabulated(depths=[1.0, 10.0]), ValueError, "first depth must be 0.0"),
        (_tabulated(factors=[0.9, 0.5]), ValueError, "factor at depth 0.0 must be 1.0"),
        (_tabulated(interpolation="cubic"), ValueError, "interpolation 'cubic'"),
    ],
)  # fmt: skip
def test_a_vertical_profile_it_cannot_apply_is_refused(profile, error, match):
    with pytest.raises(error, match=match):
        FieldParam(identifier="K", kind="homogeneous", value=10.0, vertical_profile=profile)
