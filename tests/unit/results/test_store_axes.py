"""The axis vocabulary of a run store, and the one place it is duplicated.

``dimension_names`` is what lets a reader tell the time axis of a field from
its layer axis. The names come from ``results.field_registry``, except in the
two particle extractors: the layer matrix forbids ``solver`` importing
``results``, so they repeat the strings. This pins the repetition.
"""

from __future__ import annotations

import pytest

from hydromodpy.results import field_registry
from hydromodpy.solver.modflow6.extractors import prt
from hydromodpy.solver.modflow_nwt.extractors import modpath


def test_every_descriptor_declares_axes_its_coordinates_agree_with() -> None:
    for name, descriptor in field_registry.FIELD_REGISTRY.items():
        assert descriptor.coordinates.split() == list(descriptor.dimensions), name
        assert all(descriptor.dimensions), name


def test_field_descriptor_rank_matches_its_shape_signature() -> None:
    expected = {
        field_registry.SHAPE_TIME_LAYER_FACE: 3,
        field_registry.SHAPE_TIME_FACE: 2,
        field_registry.SHAPE_LAYER_FACE: 2,
        field_registry.SHAPE_FACE: 1,
        field_registry.SHAPE_PARTICLES: 2,
    }
    for name, descriptor in field_registry.FIELD_REGISTRY.items():
        assert len(descriptor.dimensions) == expected[descriptor.shape], name


@pytest.mark.parametrize("module", [prt, modpath])
def test_the_particle_extractors_repeat_the_registry_axis_names(module) -> None:
    assert module._TRACK_AXES == (field_registry.AXIS_PARTICLE, field_registry.AXIS_TRACK_STEP)


def test_the_endpoint_extractor_repeats_the_registry_axis_name() -> None:
    assert modpath._ENDPOINT_AXES == (field_registry.AXIS_ENDPOINT,)


def test_timed_and_static_fields_name_the_same_spatial_axes() -> None:
    assert field_registry.timed_field_dimensions(2) == ("time", "face")
    assert field_registry.timed_field_dimensions(3) == ("time", "layer", "face")
    assert field_registry.static_field_dimensions(1) == ("face",)
    assert field_registry.static_field_dimensions(2) == ("layer", "face")
    with pytest.raises(ValueError):
        field_registry.timed_field_dimensions(1)
    with pytest.raises(ValueError):
        field_registry.static_field_dimensions(3)


def test_a_private_axis_set_never_collides_with_a_sibling() -> None:
    assert field_registry.per_array_dimensions("watershed_dem", 2) == (
        "watershed_dem_dim0",
        "watershed_dem_dim1",
    )
    assert field_registry.per_array_dimensions("watershed_fill", 2) != (
        field_registry.per_array_dimensions("watershed_dem", 2)
    )
