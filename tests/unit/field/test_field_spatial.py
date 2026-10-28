"""The support interface and its zone fractions, :mod:`hydromodpy.spatial.field.core.field_spatial`.

A support that does not build itself from a mapping says so by its class name,
and a discretization refuses a mesh or zone list it cannot carry
(:mod:`hydromodpy.spatial.field.core.field_spatial_weighted_discretization`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.core.field_spatial import Field, FieldDiscretization
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from tests._helpers.field_cases import write_text

MESH = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")


class _Bands(Field):
    def on_mesh(self, cell_mesh, *, cell_samples_per_axis: int = 10):
        raise AssertionError("never sampled here")


def test_the_two_base_classes_are_abstract():
    with pytest.raises(TypeError):
        Field(identifier="abstract_only")
    with pytest.raises(TypeError):
        FieldDiscretization(mesh=MESH, field_id="field_square")


def _weighted(mesh=MESH, field_id="geology", keys=("a",), fractions=None):
    fractions = {"a": np.ones(9)} if fractions is None else fractions
    return WeightedAverageFieldDiscretization(
        mesh=mesh, field_id=field_id, zone_keys=keys, fractions_by_zone=fractions
    )


@pytest.mark.parametrize(
    ("call", "error", "match"),
    [
        (lambda tmp: _Bands(identifier=" "), ValueError, "identifier must be a non-empty"),
        (lambda tmp: _Bands.from_dict({}), NotImplementedError, "_Bands.from_dict is not implemented"),
        (lambda tmp: _Bands.from_toml(tmp, section="bands"), NotImplementedError, "_Bands.from_dict"),
        (lambda tmp: _Bands.from_toml(tmp, section="other"), KeyError, "Missing TOML section 'other'"),
        (lambda tmp: _Bands.from_toml(tmp, section="bands.id"), ValueError, "'bands.id' must be a mapping"),
        (lambda tmp: _weighted(mesh=object()), TypeError, "must be a PlanarCellMesh"),
        (lambda tmp: _weighted(field_id=" "), ValueError, "field_id must be a non-empty"),
        (lambda tmp: _weighted(keys=()), ValueError, "zone_keys cannot be empty"),
        (lambda tmp: _weighted(keys=("a", " ")), ValueError, "cannot contain empty names"),
        (lambda tmp: _weighted(keys=("a", "b")), ValueError, "missing key 'b'"),
    ],
    ids=["blank-id", "no-from-dict", "toml-reaches-from-dict", "no-section", "section-not-a-table",
         "not-a-cell-mesh", "blank-field-id", "no-zone", "blank-zone", "zone-without-fractions"],
)  # fmt: skip
def test_a_support_or_discretization_it_cannot_build_is_refused(tmp_path: Path, call, error, match):
    toml = write_text(tmp_path / "bands.toml", '[bands]\nid = "bands"')

    with pytest.raises(error, match=match):
        call(toml)


def test_a_weighted_discretization_strips_its_names_and_reads_its_fractions_as_floats():
    discretization = _weighted(field_id=" geology ", keys=(" a ",), fractions={"a": [1] * 9})

    keys, fractions = discretization.weighted_components()

    assert (discretization.field_id, keys) == ("geology", ("a",))
    assert discretization.aggregation == "weighted_average"
    assert fractions["a"].dtype == float
