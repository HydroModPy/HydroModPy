from __future__ import annotations

import numpy as np

from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig


def test_domain_depth_model_default_is_constant_thickness():
    cfg = DomainConfig()
    assert cfg.depth_model.type == "constant_thickness"
    assert float(cfg.depth_model.thickness) == 50.0
    assert cfg.supports == {}
    assert cfg.zone_ids == []


def test_domain_config_accepts_geology_supports() -> None:
    cfg = DomainConfig.model_validate(
        {
            "supports": {
                "field_geology": {
                    "provider": "geology",
                }
            }
        }
    )

    assert cfg.supports["field_geology"].provider == "geology"


def test_domain_config_accepts_generated_supports() -> None:
    cfg = DomainConfig.model_validate(
        {
            "supports": {
                "halves": {
                    "provider": "generated_bands",
                    "axis": "x",
                    "breaks": [0.5],
                    "labels": ["left", "right"],
                }
            }
        }
    )

    assert cfg.supports["halves"].provider == "generated_bands"


def test_domain_config_accepts_generated_rings_supports() -> None:
    cfg = DomainConfig.model_validate(
        {
            "supports": {
                "rings": {
                    "provider": "generated_rings",
                    "coordinate_mode": "relative",
                    "radii": [0.4, 0.7],
                    "labels": ["inner", "middle", "outer"],
                }
            }
        }
    )

    assert cfg.supports["rings"].provider == "generated_rings"


def test_domain_config_accepts_mixed_support_providers() -> None:
    cfg = DomainConfig.model_validate(
        {
            "supports": {
                "field_geology": {
                    "provider": "geology",
                },
                "halves": {
                    "provider": "generated_bands",
                    "axis": "x",
                    "breaks": [0.5],
                    "labels": ["left", "right"],
                },
            }
        }
    )

    assert cfg.supports["field_geology"].provider == "geology"
    assert cfg.supports["halves"].provider == "generated_bands"


def test_domain_config_rejects_legacy_support_key() -> None:
    with np.testing.assert_raises(ValueError):
        DomainConfig.model_validate({"support_mode": "zones"})


def test_domain_builds_top_and_bottom_with_constant_thickness():
    dem = np.array([[110.0, 120.0], [100.0, 90.0]], dtype=float)
    cfg = DomainConfig.model_validate(
        {
            "depth_model": {
                "type": "constant_thickness",
                "thickness": 30.0,
            }
        }
    )

    domain = Domain(config=cfg, surface_topo=Surface(name="surface_topo", values=dem))
    assert (domain.substratum.as_array() < domain.surface_topo.as_array()).all()
    np.testing.assert_allclose(domain.surface_topo.as_array(), dem)
    np.testing.assert_allclose(domain.substratum.as_array(), dem - 30.0)


def test_domain_builds_top_and_bottom_with_constant_thickness_unit_string():
    dem = np.array([[110.0, 120.0], [100.0, 90.0]], dtype=float)
    cfg = DomainConfig.model_validate(
        {
            "depth_model": {
                "type": "constant_thickness",
                "thickness": "30.0 m",
            }
        }
    )

    domain = Domain(config=cfg, surface_topo=Surface(name="surface_topo", values=dem))
    assert (domain.surface_topo.as_array() - domain.substratum.as_array() == 30.0).all()
    np.testing.assert_allclose(domain.surface_topo.as_array(), dem)
    np.testing.assert_allclose(domain.substratum.as_array(), dem - 30.0)


def test_domain_builds_flat_substratum():
    dem = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=float)
    cfg = DomainConfig.model_validate(
        {
            "depth_model": {
                "type": "flat_substratum",
                "substratum_elevation": -12.5,
            }
        }
    )

    domain = Domain(config=cfg, surface_topo=Surface(name="surface_topo", values=dem))
    assert np.unique(domain.substratum.as_array()).tolist() == [-12.5]
    np.testing.assert_allclose(domain.surface_topo.as_array(), dem)
    np.testing.assert_allclose(
        domain.substratum.as_array(),
        np.full_like(dem, -12.5),
    )


def test_domain_flat_substratum_must_be_below_topography_everywhere():
    dem = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=float)
    cfg = DomainConfig.model_validate(
        {
            "depth_model": {
                "type": "flat_substratum",
                "substratum_elevation": 6.0,
            }
        }
    )

    try:
        Domain(config=cfg, surface_topo=Surface(name="surface_topo", values=dem))
    except ValueError as exc:
        assert "strictly below" in str(exc)
    else:
        raise AssertionError("Expected ValueError when substratum is not below topography")


def test_surface_shifted_down_by():
    support = RasterSupport(crs="EPSG:2154", dx=50.0, dy=60.0, nrows=1, ncols=2)
    top = Surface(
        name="surface_topo",
        values=np.array([[10.0, 12.0]], dtype=float),
        support=support,
    )
    substratum = top.shifted_down_by(3.5)

    assert substratum.name == "substratum"
    assert substratum.support is support
    np.testing.assert_allclose(substratum.as_array(), np.array([[6.5, 8.5]], dtype=float))


def test_surface_flat_like_validates_position():
    support = RasterSupport(crs="EPSG:2154", dx=50.0, dy=60.0, nrows=1, ncols=2)
    top = Surface(
        name="surface_topo",
        values=np.array([[10.0, 12.0]], dtype=float),
        support=support,
    )
    substratum = top.flat_like(2.0)
    assert substratum.support is support
    np.testing.assert_allclose(substratum.as_array(), np.array([[2.0, 2.0]], dtype=float))

    try:
        top.flat_like(11.0)
    except ValueError as exc:
        assert "strictly below" in str(exc)
    else:
        raise AssertionError("Expected ValueError when flat substratum is not below topography")


def test_domain_uses_surface_support_as_default_georeferencing():
    support = RasterSupport(
        crs="EPSG:2154",
        dx=50.0,
        dy=60.0,
        xmin=100.0,
        xmax=200.0,
        ymin=300.0,
        ymax=400.0,
        nrows=1,
        ncols=2,
    )
    top = Surface(
        name="surface_topo",
        values=np.array([[10.0, 12.0]], dtype=float),
        support=support,
    )

    domain = Domain(
        config=DomainConfig(),
        surface_topo=top,
    )

    assert domain.georeferencing == {
        "crs": "EPSG:2154",
        "dx": 50.0,
        "dy": 60.0,
        "xmin": 100.0,
        "xmax": 200.0,
        "ymin": 300.0,
        "ymax": 400.0,
    }


def test_surface_from_geographic_dem_uses_explicit_values_and_support():
    support = RasterSupport(
        crs="EPSG:2154",
        dx=25.0,
        dy=30.0,
        xmin=0.0,
        xmax=50.0,
        ymin=100.0,
        ymax=125.0,
        nrows=1,
        ncols=2,
    )
    surface = Surface.from_geographic_dem(
        [[1.0, 2.0]],
        support=support,
        name="surface_topo",
    )

    assert surface.support is support
    np.testing.assert_allclose(surface.as_array(), np.array([[1.0, 2.0]], dtype=float))
