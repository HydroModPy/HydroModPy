"""One constructor of a domain geometry, and what it owes its callers.

``Domain(...)`` was written out at four sites. Three of them copied the declared
section and armed the binder zone ids before constructing, each in its own
spelling; the fourth armed nothing. A copy that stops happening leaves a project
whose ``[domain]`` carries ``catchment`` and ``geology`` as if the user had
written them, and nothing downstream would say so.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.spatial.domain.build import (
    build_domain,
    domain_config_for_build,
    read_layer_base_sources,
    read_substratum_source,
)
from hydromodpy.spatial.domain.depth_model_config import RasterSubstratumDepthModel
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.domain.zone_arming import BINDER_ZONE_IDS, arm_runtime_zone_ids
from hydromodpy.spatial.surface import Surface
from tests._helpers.domain_cases import tilted_top
from tests._helpers.geotiffs import write_geotiff


def _surface() -> Surface:
    return Surface(name="surface_topo", values=np.full((4, 4), 120.0))


def test_the_declared_section_is_not_the_one_the_domain_is_built_from() -> None:
    declared = DomainConfig.with_thickness(40.0)

    domain = build_domain(declared, surface_topo=_surface())

    assert declared.zone_ids == []
    assert domain.config is not declared
    assert domain.config.zone_ids == list(BINDER_ZONE_IDS)


def test_a_mapping_is_validated_into_the_section_it_claims_to_be() -> None:
    domain = build_domain(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 90.0}},
        surface_topo=_surface(),
    )

    np.testing.assert_allclose(domain.substratum.as_array(), 90.0)


def test_no_configuration_at_all_builds_the_default_geometry() -> None:
    """The bundle exporter passes ``None`` when a caller declared nothing."""
    domain = build_domain(None, surface_topo=_surface())

    assert domain.config.depth_model.kind == DomainConfig().depth_model.kind
    assert domain.substratum is not None


def test_something_that_is_neither_a_section_nor_a_mapping_is_refused() -> None:
    with pytest.raises(TypeError, match="DomainConfig instance or a mapping"):
        domain_config_for_build(object())  # type: ignore[arg-type]


def test_the_depth_model_decides_the_bottom_and_the_surface_is_untouched() -> None:
    surface = _surface()

    domain = build_domain(DomainConfig.with_thickness(40.0), surface_topo=surface)

    assert domain.surface_topo is surface
    np.testing.assert_allclose(domain.substratum.as_array(), 80.0)


@pytest.mark.parametrize(
    ("declared", "requested", "armed"),
    [
        ([], (), ["catchment", "geology"]),
        ([], ("field_geology",), ["catchment", "geology", "field_geology"]),
        (["lithofacies"], (), ["lithofacies", "catchment", "geology"]),
        (["geology"], ("field_geology", " Field_Geology "), ["geology", "catchment", "field_geology"]),
    ],
    ids=["empty", "requested_support", "project_zonation_first", "never_twice"],
)  # fmt: skip
def test_the_binder_and_requested_ids_are_armed_once_after_the_project_ones(
    declared, requested, armed
):
    cfg = DomainConfig(zone_ids=declared)

    arm_runtime_zone_ids(cfg, requested)
    arm_runtime_zone_ids(cfg, requested)

    assert cfg.zone_ids == armed


@pytest.mark.parametrize(
    ("zone_ids", "armed"),
    [(None, ["catchment", "geology"]), (("geology",), ["geology", "catchment"])],
    ids=["none", "tuple"],
)
def test_a_section_without_a_list_of_zone_ids_receives_one(zone_ids, armed):
    section = SimpleNamespace(zone_ids=zone_ids)

    assert arm_runtime_zone_ids(section) is section
    assert section.zone_ids == armed


def test_an_armed_domain_takes_the_binder_and_support_zones_and_refuses_a_typo():
    """The reason ``domain.zone_ids = ['geology']`` used to be mandatory."""
    domain = build_domain(None, surface_topo=_surface(), zone_ids=("field_geology",))

    for zone_id in (*BINDER_ZONE_IDS, "field_geology"):
        domain.set_zone(zone_id, object())
    with pytest.raises(ValueError, match="is not declared in domain.zone_ids"):
        domain.set_zone("typo_zone", object())


def _sources(**rasters: object) -> SimpleNamespace:
    return SimpleNamespace(
        sources=[SimpleNamespace(name=name, path=path, default_crs=None) for name, path in rasters.items()]
    )  # fmt: skip


def test_a_raster_depth_model_reads_the_first_substratum_source(tmp_path):
    path = write_geotiff(tmp_path / "sub.tif", np.full((3, 4), 42.0))

    surface = read_substratum_source(
        RasterSubstratumDepthModel(kind="raster_substratum"), SimpleNamespace(substratum=_sources(a=path))
    )  # fmt: skip

    assert surface.name == "substratum_source"
    np.testing.assert_array_equal(surface.as_array(), 42.0)


def test_another_depth_model_reads_nothing_and_a_raster_one_without_source_is_refused():
    assert read_substratum_source(DomainConfig().depth_model, None) is None
    with pytest.raises(ConfigError, match=r"\[data.substratum\]"):
        read_substratum_source(RasterSubstratumDepthModel(kind="raster_substratum"), None)


def test_the_layer_bases_are_read_by_the_names_the_layering_reads(tmp_path):
    layers = VerticalGridConfig.model_validate(
        {"genmtd_lay": "surfaces", "layer": [{"name": "a", "surface": "rock"}, {"name": "b", "surface": "clay"}, {"name": "c"}]}
    )  # fmt: skip
    path = write_geotiff(tmp_path / "rock.tif", np.full((3, 4), 10.0))

    read = read_layer_base_sources(
        layers, SimpleNamespace(layer_base=_sources(rock=path, extra=path))
    )

    assert list(read) == ["rock"]
    assert read["rock"].name == "rock_source"
    assert read_layer_base_sources(layers, None) == {}
    assert read_layer_base_sources(VerticalGridConfig(), None) == {}


def test_a_domain_built_with_active_cells_only_checks_those_cells():
    top = tilted_top()
    active = np.zeros(top.as_array().shape, dtype=bool)
    active[:, :4] = True
    half = Surface(name="raw", values=np.full((6, 4), 50.0), support=tilted_top(6, 4).support)

    domain = build_domain(
        {"depth_model": {"kind": "raster_substratum"}},
        surface_topo=top,
        substratum_source=half,
        active_cells=active,
    )

    np.testing.assert_array_equal(domain.substratum.as_array()[active], 50.0)
