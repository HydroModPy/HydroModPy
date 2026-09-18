"""One constructor of a domain geometry, and what it owes its callers.

``Domain(...)`` was written out at four sites. Three of them copied the declared
section and armed the binder zone ids before constructing, each in its own
spelling; the fourth armed nothing. What they now share is small and was never
the hard part, which is exactly why it is worth pinning: a copy that stops
happening leaves a project whose ``[domain]`` carries ``catchment`` and
``geology`` as if the user had written them, and nothing downstream would say
so.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.domain.build import build_domain, domain_config_for_build
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.surface import Surface


def _surface() -> Surface:
    return Surface(name="surface_topo", values=np.full((4, 4), 120.0))


def test_the_declared_section_is_not_the_one_the_domain_is_built_from() -> None:
    declared = DomainConfig.with_thickness(40.0)

    domain = build_domain(declared, surface_topo=_surface())

    assert declared.zone_ids == []
    assert domain.config is not declared
    assert domain.config.zone_ids == ["catchment", "geology"]


def test_a_requested_support_is_armed_beside_the_binder_ids() -> None:
    domain = build_domain(DomainConfig(), surface_topo=_surface(), zone_ids=("field_geology",))

    assert domain.config.zone_ids == ["catchment", "geology", "field_geology"]


def test_a_mapping_is_validated_into_the_section_it_claims_to_be() -> None:
    domain = build_domain(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 90.0}},
        surface_topo=_surface(),
    )

    assert domain.substratum is not None
    np.testing.assert_allclose(domain.substratum.as_array(), 90.0)


def test_no_configuration_at_all_builds_the_default_geometry() -> None:
    """The bundle exporter passes ``None`` when a caller declared nothing."""
    domain = build_domain(None, surface_topo=_surface())

    assert domain.config.depth_model.kind == "constant_thickness"
    assert domain.substratum is not None


def test_something_that_is_neither_a_section_nor_a_mapping_is_refused() -> None:
    with pytest.raises(TypeError, match="DomainConfig instance or a mapping"):
        domain_config_for_build(object())  # type: ignore[arg-type]


def test_the_depth_model_decides_the_bottom_and_the_surface_is_untouched() -> None:
    surface = _surface()

    domain = build_domain(DomainConfig.with_thickness(40.0), surface_topo=surface)

    assert domain.surface_topo is surface
    assert domain.substratum is not None
    np.testing.assert_allclose(domain.substratum.as_array(), 80.0)
