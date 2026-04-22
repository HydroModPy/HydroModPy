from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial import CatchmentZonesField, RasterSupport, Surface
from hydromodpy.spatial.domain import (
    Domain,
    DomainConfig,
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
)
from hydromodpy.spatial.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
)


def _build_domain() -> Domain:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=5.0,
        dy=10.0,
        xmin=10.0,
        xmax=30.0,
        ymin=100.0,
        ymax=120.0,
        nrows=2,
        ncols=4,
    )
    surface = Surface(
        name="surface_topo",
        values=np.zeros((2, 4), dtype=float),
        support=support,
    )
    return Domain(
        config=DomainConfig.model_validate({"zone_ids": ["catchment"]}),
        surface_topo=surface,
    )


def _build_context(domain: Domain) -> SupportBuildContext:
    return SupportBuildContext(
        cfg=SimpleNamespace(),
        raw_toml={},
        workspace=None,
        geographic=None,
        domain_geographic=None,
        domain=domain,
        flow=None,
        loaded_data=None,
        time_grid=None,
    )


def test_generated_bands_provider_builds_relative_breaks_from_domain_extent() -> None:
    registry = build_default_spatial_support_provider_registry()
    provider = registry.get("generated_bands")
    domain = _build_domain()
    config = GeneratedBandsSupportConfig(
        provider="generated_bands",
        axis="x",
        coordinate_mode="relative",
        breaks=[0.5],
        labels=["left", "right"],
    )

    support = provider.build(
        support_id="halves",
        config=config,
        context=_build_context(domain),
    )

    assert support.identifier == "halves"
    assert support.breaks_abs == [20.0]
    np.testing.assert_array_equal(
        support.zone_id(np.array([12.0, 25.0]), np.array([110.0, 110.0])),
        np.array(["left", "right"], dtype=object),
    )


def test_generated_bands_provider_rejects_breaks_outside_domain_extent() -> None:
    registry = build_default_spatial_support_provider_registry()
    provider = registry.get("generated_bands")
    domain = _build_domain()
    config = GeneratedBandsSupportConfig(
        provider="generated_bands",
        axis="x",
        coordinate_mode="absolute",
        breaks=[35.0],
        labels=["left", "right"],
    )

    with pytest.raises(ValueError, match="strictly inside the domain x extent"):
        provider.build(
            support_id="halves",
            config=config,
            context=_build_context(domain),
        )


def test_generated_rings_provider_builds_relative_radii_from_domain_extent() -> None:
    registry = build_default_spatial_support_provider_registry()
    provider = registry.get("generated_rings")
    domain = _build_domain()
    config = GeneratedRingsSupportConfig(
        provider="generated_rings",
        coordinate_mode="relative",
        radii=[0.5],
        labels=["inner", "outer"],
    )

    support = provider.build(
        support_id="rings",
        config=config,
        context=_build_context(domain),
    )

    assert support.identifier == "rings"
    assert support.radii_abs == [5.0]
    np.testing.assert_array_equal(
        support.zone_id(np.array([20.0, 27.0]), np.array([110.0, 110.0])),
        np.array(["inner", "outer"], dtype=object),
    )


def test_generated_rings_provider_rejects_radii_outside_inscribed_circle() -> None:
    registry = build_default_spatial_support_provider_registry()
    provider = registry.get("generated_rings")
    domain = _build_domain()
    config = GeneratedRingsSupportConfig(
        provider="generated_rings",
        coordinate_mode="absolute",
        radii=[10.0],
        labels=["inner", "outer"],
    )

    with pytest.raises(ValueError, match="strictly inside the largest inscribed circle"):
        provider.build(
            support_id="rings",
            config=config,
            context=_build_context(domain),
        )


def test_catchment_zones_provider_wraps_existing_domain_zone() -> None:
    registry = build_default_spatial_support_provider_registry()
    provider = registry.get("catchment_zones")
    domain = _build_domain()
    domain.set_zone(
        "catchment",
        CatchmentZonesField(
            identifier="catchment_zones",
            encoded_codes=np.array([[1, 1, 2, 3], [1, 2, 2, 3]], dtype=np.uint8),
            encoded_to_zone={1: "domain", 2: "buffer", 3: "core"},
        ),
    )
    config = CatchmentZonesSupportConfig(provider="catchment_zones")

    support = provider.build(
        support_id="catchment_support",
        config=config,
        context=_build_context(domain),
    )

    assert support.identifier == "catchment_support"
    assert support.zone_keys == ("domain", "buffer", "core")
