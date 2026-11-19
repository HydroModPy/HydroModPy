"""The depth factor of a field parameter, :mod:`hydromodpy.model.properties.vertical_profile`."""

import numpy as np
import pytest

from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.vertical_profile import (
    layer_profile_depths,
    normalize_vertical_profile,
)


@pytest.mark.parametrize(
    ("profile", "depths", "factors"),
    [
        (None, [0.0, 50.0], [1.0, 1.0]),
        ({"kind": "none"}, [0.0, 50.0], [1.0, 1.0]),
        ({"kind": "exponential", "characteristic_depth": 20.0}, [0.0, 20.0], [1.0, np.exp(-1.0)]),
        ({"kind": "exponential", "characteristic_depth": "0.02 km"}, [10.0], [np.exp(-0.5)]),
        ({"kind": "exponential", "characteristic_depth": 5.0, "min_factor": 0.2}, [0.0, 1000.0], [1.0, 0.2]),
        ({"kind": "tabulated", "depths": [0.0, 20.0, 40.0], "factors": [1.0, 0.5, 0.25]},
         [10.0, 30.0, 80.0], [0.75, 0.375, 0.25]),
        ({"kind": "tabulated", "depths": [0, 10], "factors": [1, 0.5], "interpolation": "step"},
         [0.0, 5.0, 10.0, 20.0], [1.0, 1.0, 0.5, 0.5]),
    ],
    ids=["no-profile", "none", "exponential", "depth-in-km", "floor", "tabulated", "step"],
)  # fmt: skip
def test_a_vertical_profile_scales_the_surface_value_with_depth(profile, depths, factors):
    param = FieldParam(identifier="K", kind="homogeneous", value=10.0, vertical_profile=profile)

    assert param.has_vertical_variation is (profile is not None and profile["kind"] != "none")
    np.testing.assert_allclose(param.vertical_factor(np.array(depths)), factors)
    np.testing.assert_allclose(
        param.to_array(shape=(len(depths),), depth=np.array(depths)), 10.0 * np.array(factors)
    )
    assert float(param.to_array(depth=depths[-1])) == pytest.approx(10.0 * factors[-1])


_GRADED = {
    "kind": "exponential",
    "characteristic_depth": 15.0,
    "characteristic_depth_high": 1.0,
    "ground_low": 93.0,
    "ground_high": 136.0,
}
"""A decay length of 15 m at and below 93 m of ground, 1 m at and above 136 m."""


def _tabulated(**override) -> dict:
    return {"kind": "tabulated", "depths": [0.0, 10.0], "factors": [1.0, 0.5]} | override


@pytest.mark.parametrize(
    ("profile", "error", "match"),
    [
        (["exponential"], TypeError, "must be a mapping"),
        ({"kind": "linear"}, ValueError, "Unsupported vertical profile mode 'linear'"),
        ({"kind": "exponential"}, KeyError, "requires 'characteristic_depth'"),
        ({"kind": "exponential", "characteristic_depth": None}, ValueError, "cannot be None"),
        ({"kind": "exponential", "characteristic_depth": True}, TypeError, "rejects boolean"),
        ({"kind": "exponential", "characteristic_depth": " "}, ValueError, "empty length string"),
        ({"kind": "exponential", "characteristic_depth": [1]}, TypeError, "unsupported length"),
        ({"kind": "exponential", "characteristic_depth": 0.0}, ValueError, "must be > 0"),
        ({"kind": "exponential", "characteristic_depth": 9, "min_factor": "nan"}, ValueError, "finite"),
        ({"kind": "exponential", "characteristic_depth": 9, "min_factor": 1.2}, ValueError, r"\[0, 1\]"),
        ({"kind": "tabulated", "factors": [1.0]}, KeyError, "requires 'depths'"),
        ({"kind": "tabulated", "depths": [0.0]}, KeyError, "requires 'factors'"),
        (_tabulated(depths=[], factors=[]), ValueError, "cannot be empty"),
        (_tabulated(depths=[0.0]), ValueError, "same length"),
        (_tabulated(factors=[1.0, np.inf]), ValueError, "must be finite"),
        (_tabulated(depths=[-1.0, 10.0]), ValueError, "must be >= 0"),
        (_tabulated(depths=[0.0, 0.0]), ValueError, "strictly increasing"),
        (_tabulated(depths=[1.0, 10.0]), ValueError, "first depth must be 0.0"),
        (_tabulated(factors=[0.9, 0.5]), ValueError, "factor at depth 0.0 must be 1.0"),
        (_tabulated(interpolation="cubic"), ValueError, "interpolation 'cubic'"),
        (_tabulated(depth_at="bottom"), ValueError, "depth_at 'bottom'"),
        ({"kind": "exponential", "characteristic_depth": 9, "ground_low": 90}, KeyError, "together"),
        (_GRADED | {"ground_high": 80.0}, ValueError, "above ground_low"),
        (_GRADED | {"characteristic_depth_high": 0.0}, ValueError, "must be > 0"),
        (_tabulated(characteristic_depth_high=1.0, ground_low=0.0, ground_high=1.0), ValueError,
         "exponential profile only"),
    ],
)  # fmt: skip
def test_a_vertical_profile_it_cannot_apply_is_refused(profile, error, match):
    with pytest.raises(error, match=match):
        FieldParam(identifier="K", kind="homogeneous", value=10.0, vertical_profile=profile)


# Ground at 10 m, two layers: 10 to 6 m and 6 to 0 m, on two cells.
INTERFACES = np.array([[10.0, 10.0], [6.0, 6.0], [0.0, 0.0]])


@pytest.mark.parametrize(
    ("depth_at", "expected"),
    [
        ("middle", [2.0, 7.0]),
        ("top", [0.0, 4.0]),
        ("base", [4.0, 10.0]),
        ("surface_then_base", [0.0, 10.0]),
    ],
)
def test_a_layer_reads_the_profile_at_its_middle_its_top_or_its_base(depth_at, expected):
    profile = {"kind": "exponential", "characteristic_depth": 20.0, "depth_at": depth_at}
    depths = layer_profile_depths(normalize_vertical_profile(profile), INTERFACES)
    np.testing.assert_allclose(depths, np.array([expected, expected]).T)


def test_the_middle_is_the_default_and_a_depth_is_never_negative():
    # A base above the ground, as a nodata pixel can make, gives no depth below zero.
    interfaces = np.array([[10.0, 10.0], [6.0, 12.0], [0.0, 14.0]])
    depths = layer_profile_depths(normalize_vertical_profile({"kind": "none"}), interfaces)
    assert depths[0, 0] == pytest.approx(2.0)
    assert (depths >= 0.0).all()


def test_a_graded_decay_length_follows_the_ground_elevation():
    # Ground at 93, 114.5 and 136 m: decay lengths of 15 m, 8 m and 1 m.
    profile = normalize_vertical_profile(_GRADED)
    ground = np.array([93.0, 114.5, 136.0])
    interfaces = np.vstack([ground, ground - 10.0])
    depths = layer_profile_depths(profile, interfaces)
    factor = FieldParam(
        identifier="K", kind="homogeneous", value=1.0, vertical_profile=_GRADED
    ).vertical_factor(depths[0])
    np.testing.assert_allclose(factor, np.exp(-5.0 / np.array([15.0, 8.0, 1.0])))


def test_a_graded_profile_keeps_its_keys_and_depth_at_through_the_normalization():
    profile = normalize_vertical_profile(_GRADED | {"depth_at": "base", "ground_low": "93 m"})
    assert profile["ground_low"] == pytest.approx(93.0)
    assert profile["depth_at"] == "base"
    assert "depth_at" not in normalize_vertical_profile(_GRADED)
