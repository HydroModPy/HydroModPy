"""One constructor of a domain geometry, and what it owes its callers.

Three of the four former call sites copied the declared section and armed the binder zone ids,
each in its own spelling, and the fourth armed nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.model.domain.build import (
    BINDER_ZONE_IDS,
    arm_runtime_zone_ids,
    build_domain,
    domain_config_for_build,
    read_layer_base_sources,
    read_substratum_source,
)
from hydromodpy.model.domain.depth_model_config import RasterSubstratumDepthModel
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from tests._helpers.geotiffs import write_geotiff

RASTER_KIND = RasterSubstratumDepthModel(kind="raster_substratum")


def _surface() -> Surface:
    return Surface(name="surface_topo", values=np.full((4, 4), 120.0))


def test_the_depth_model_decides_the_bottom_on_a_copy_of_the_section_armed_with_the_binder_zones():
    declared, surface = DomainConfig.with_thickness(40.0), _surface()

    domain = build_domain(declared, surface_topo=surface)

    assert declared.zone_ids == []
    assert domain.config is not declared
    assert domain.config.zone_ids == list(BINDER_ZONE_IDS)
    assert domain.surface_topo is surface
    np.testing.assert_allclose(domain.substratum.as_array(), 80.0)
    armed = build_domain(None, surface_topo=_surface(), zone_ids=("field_geology",))
    for zone_id in (*BINDER_ZONE_IDS, "field_geology"):
        armed.set_zone(zone_id, object())
    with pytest.raises(ValueError, match="is not declared in domain.zone_ids"):
        armed.set_zone("typo_zone", object())


def test_a_mapping_or_nothing_is_validated_into_a_section_and_anything_else_is_refused():
    """The bundle exporter passes ``None`` when a caller declared nothing."""
    mapping = {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 90.0}}
    np.testing.assert_allclose(build_domain(mapping, surface_topo=_surface()).substratum.as_array(), 90.0)  # fmt: skip

    domain = build_domain(None, surface_topo=_surface())

    assert domain.config.depth_model.kind == DomainConfig().depth_model.kind
    assert domain.substratum is not None
    with pytest.raises(TypeError, match="DomainConfig instance or a mapping"):
        domain_config_for_build(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("section", "declared", "requested", "armed"),
    [
        (DomainConfig, [], (), ["catchment", "geology"]),
        (DomainConfig, [], ("field_geology",), ["catchment", "geology", "field_geology"]),
        (DomainConfig, ["lithofacies"], (), ["lithofacies", "catchment", "geology"]),
        (DomainConfig, ["geology"], ("field_geology", " Field_Geology "), ["geology", "catchment", "field_geology"]),
        (SimpleNamespace, None, (), ["catchment", "geology"]),
        (SimpleNamespace, ("geology",), (), ["geology", "catchment"]),
    ],
    ids=["empty", "requested_support", "project_zonation_first", "never_twice", "section_without_ids", "section_with_a_tuple"],
)  # fmt: skip
def test_the_binder_and_requested_ids_are_armed_once_after_the_project_ones(section, declared, requested, armed):  # fmt: skip
    cfg = section(zone_ids=declared)

    assert arm_runtime_zone_ids(cfg, requested) is cfg
    arm_runtime_zone_ids(cfg, requested)

    assert cfg.zone_ids == armed


def _sources(**rasters: object) -> SimpleNamespace:
    return SimpleNamespace(sources=[SimpleNamespace(name=name, path=path, default_crs=None) for name, path in rasters.items()])  # fmt: skip


def test_a_raster_depth_model_reads_the_first_substratum_source_and_another_reads_nothing(tmp_path):  # fmt: skip
    path = write_geotiff(tmp_path / "sub.tif", np.full((3, 4), 42.0))

    surface = read_substratum_source(RASTER_KIND, SimpleNamespace(substratum=_sources(a=path)))

    assert surface.name == "substratum_source"
    np.testing.assert_array_equal(surface.as_array(), 42.0)
    assert read_substratum_source(DomainConfig().depth_model, None) is None
    with pytest.raises(ConfigError, match=r"\[data.substratum\]"):
        read_substratum_source(RASTER_KIND, None)


def test_the_layer_bases_are_read_by_the_names_the_layering_reads(tmp_path):
    layers = VerticalGridConfig.model_validate({"genmtd_lay": "surfaces", "layer": [{"name": "a", "surface": "rock"}, {"name": "b", "surface": "clay"}, {"name": "c"}]})  # fmt: skip
    path = write_geotiff(tmp_path / "rock.tif", np.full((3, 4), 10.0))

    read = read_layer_base_sources(layers, SimpleNamespace(layer_base=_sources(rock=path, extra=path)))  # fmt: skip

    assert list(read) == ["rock"]
    assert read["rock"].name == "rock_source"
    assert read_layer_base_sources(layers, None) == {}
    assert read_layer_base_sources(VerticalGridConfig(), None) == {}
