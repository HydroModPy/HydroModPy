"""Unit tests for hydromodpy.calibration.optim.parameters."""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


class TestCalibParameter:
    def test_identity_transform_roundtrip(self):
        p = CalibParameter(name="x", lower=0.0, upper=10.0, transform="identity")
        assert p.to_transformed(5.0) == 5.0
        assert p.to_physical(5.0) == 5.0

    def test_log_transform_roundtrip(self):
        p = CalibParameter(name="k", lower=1e-6, upper=1e-3, transform="log")
        assert math.isclose(p.lower_transformed, -6.0)
        assert math.isclose(p.upper_transformed, -3.0)
        y = p.to_transformed(1e-4)
        assert math.isclose(y, -4.0)
        assert math.isclose(p.to_physical(y), 1e-4)

    def test_log_rejects_nonpositive(self):
        p = CalibParameter(name="k", lower=1e-6, upper=1.0, transform="log")
        with pytest.raises(ValueError):
            p.to_transformed(0.0)

    def test_logit_transform_roundtrip(self):
        p = CalibParameter(name="s", lower=0.05, upper=0.5, transform="logit")
        x = 0.2
        y = p.to_transformed(x)
        assert math.isclose(p.to_physical(y), x, rel_tol=1e-9)


class TestParameterSpace:
    def test_dim_and_names(self):
        space = ParameterSpace(
            [
                CalibParameter(name="a", lower=0.0, upper=1.0),
                CalibParameter(name="b", lower=-1.0, upper=1.0),
            ]
        )
        assert space.dim == 2
        assert space.names == ("a", "b")

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValueError, match="Duplicate"):
            ParameterSpace(
                [
                    CalibParameter(name="a", lower=0, upper=1),
                    CalibParameter(name="a", lower=0, upper=2),
                ]
            )

    def test_from_toml_fails_without_bounds(self):
        with pytest.raises(ValueError, match="no bounds"):
            ParameterSpace.from_toml_mapping({"K": {}})

    def test_transformed_bounds(self):
        space = ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-3, transform="log")])
        tb = space.transformed_bounds
        assert math.isclose(tb["k"][0], -6.0)
        assert math.isclose(tb["k"][1], -3.0)
