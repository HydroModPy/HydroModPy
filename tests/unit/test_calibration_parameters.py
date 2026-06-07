"""Unit tests for hydromodpy.calibration.parameters."""

from __future__ import annotations

import math

import pytest
from pydantic import BaseModel, Field

from hydromodpy.calibration.parameters import (
    CalibParameter,
    Calibrable,
    ParameterSpace,
    discover_calibrable,
)


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

    def test_from_toml_uses_annotations_when_bounds_missing(self):
        ann = {"K": Calibrable(bounds=(1e-6, 1e-3), transform="log")}
        decls = {"K": {}}
        space = ParameterSpace.from_toml_mapping(decls, annotations=ann)
        assert space["K"].lower == 1e-6
        assert space["K"].transform == "log"

    def test_toml_overrides_annotation(self):
        ann = {"K": Calibrable(bounds=(1e-6, 1e-3), transform="log")}
        decls = {"K": {"bounds": [1e-8, 1e-4]}}
        space = ParameterSpace.from_toml_mapping(decls, annotations=ann)
        assert space["K"].lower == 1e-8
        assert space["K"].upper == 1e-4

    def test_from_toml_fails_without_bounds(self):
        with pytest.raises(ValueError, match="no bounds"):
            ParameterSpace.from_toml_mapping({"K": {}})

    def test_transformed_bounds(self):
        space = ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-3, transform="log")])
        tb = space.transformed_bounds
        assert math.isclose(tb["k"][0], -6.0)
        assert math.isclose(tb["k"][1], -3.0)


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------


class _Leaf(BaseModel):
    k_aquifer: float = Field(
        default=1e-4,
        json_schema_extra={
            "calibrable": Calibrable(bounds=(1e-7, 1e-2), transform="log"),
        },
    )
    not_calibrable: float = 0.1


class _Root(BaseModel):
    leaf: _Leaf = Field(default_factory=_Leaf)
    other: float = Field(
        default=0.0,
        json_schema_extra={
            "calibrable": {"bounds": (0.0, 1.0), "transform": "identity"},
        },
    )


class TestAutoDiscovery:
    def test_walks_nested_models(self):
        found = discover_calibrable(_Root)
        assert "leaf.k_aquifer" in found
        assert "other" in found
        assert "leaf.not_calibrable" not in found

    def test_discover_from_instance(self):
        root = _Root()
        found = discover_calibrable(root)
        assert found["leaf.k_aquifer"].bounds == (1e-7, 1e-2)
        assert found["leaf.k_aquifer"].transform == "log"

    def test_accepts_dict_hint(self):
        found = discover_calibrable(_Root)
        assert found["other"].transform == "identity"
