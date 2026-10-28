"""The bundle of geographic products handed to the workflow and to the domain."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.derived_features import (
    DomainGeographicContext,
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
    attach_reference_hydrographic_network,
    coerce_geographic_derived_features,
    resolve_river_mesh_trace,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from tests._helpers.geographic_cases import write_features

FIELD = HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME
GENERATED = HydrographicNetwork(
    role="generated", source_kind="geographic_generated", vector_path="river_network.shp"
)


def _features(watershed: str = "watershed.shp", **fields) -> GeographicDerivedFeatures:
    return GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=watershed, watershed_box_shp="watershed_box.shp", box_buff_shp="bb.shp"
        ),
        hydrographic_networks=HydrographicNetworks(generated=GENERATED),
        **fields,
    )


def _lines(path: Path, n: int) -> Path:
    return write_features(
        path, [LineString([(0.0, 100.0 * i), (1000.0, 100.0 * i)]) for i in range(n)]
    )


def test_attaching_the_reference_attaches_its_permanent_part(tmp_path: Path) -> None:
    full = _lines(tmp_path / "streams.shp", 3)
    permanent = _lines(tmp_path / "streams_permanent.shp", 1)
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, -50.0, 1000.0, 400.0)])
    features = _features(str(watershed))
    result = LoadResult(
        fields=[
            FieldRecord(
                variable=FIELD,
                source="hydrography",
                unit="",
                data=xr.Dataset({FIELD: (("y", "x"), np.zeros((2, 2)))}),
                bbox=(0.0, 0.0, 2.0, 2.0),
                crs="EPSG:2154",
                metadata={"vector_path": str(full), "permanent_vector_path": str(permanent)},
            )
        ]
    )

    updated = attach_reference_hydrographic_network(features, result)

    assert updated is not features
    assert updated.generated_hydrographic_network is GENERATED
    assert updated.reference_hydrographic_network.vector_path == str(full)
    assert updated.reference_permanent_hydrographic_network.vector_path == str(permanent)
    assert [n.role for n in updated.hydrographic_networks.iter_available()] == [
        "reference",
        "reference_permanent",
        "generated",
    ]
    assert attach_reference_hydrographic_network(features, None) is features


def test_the_domain_view_and_its_lift_carry_the_same_boundaries_and_outlet() -> None:
    features = _features(
        catchment_area_km2=3.5,
        catch_def="from_outlet_coord",
        x_outlet=1,
        y_outlet=2,
        regional_dem_path=Path("dem.tif"),
    )

    context = features.to_domain_geographic_context()
    lifted = GeographicDerivedFeatures.from_domain_geographic_context(context)

    assert isinstance(context, DomainGeographicContext)
    assert (context.x_outlet, context.y_outlet) == (1.0, 2.0)
    assert context.regional_dem_path == "dem.tif"
    assert lifted.boundaries == features.boundaries
    assert lifted.catchment_area_km2 == 3.5
    assert lifted.rivers.enabled is False
    assert lifted.to_domain_geographic_context() == context
    bare = _features().to_domain_geographic_context()
    assert (bare.x_outlet, bare.regional_dem_path) == (None, None)


def _context() -> DomainGeographicContext:
    return _features(catch_def="dem").to_domain_geographic_context()


@pytest.mark.parametrize(
    ("given", "catch_def"),
    [
        ({"geographic_features": "features"}, "features"),
        (
            {"geographic_features": SimpleNamespace(rivers=1, to_domain_geographic_context=id)},
            "duck",
        ),
        ({"geographic": SimpleNamespace(get_geographic_derived_features=lambda: None)}, None),
        (
            {"geographic": SimpleNamespace(get_domain_geographic_context=_context)},
            "dem",
        ),
        ({"domain_geographic": "context"}, "dem"),
        ({"domain_geographic": object()}, None),
        ({}, None),
    ],
    ids=[
        "the bundle",
        "a bundle-like object",
        "a runtime with no bundle",
        "a runtime with a domain view",
        "a domain view",
        "not a domain view",
        "nothing",
    ],
)
def test_the_bundle_is_found_on_whatever_runtime_object_carries_it(given, catch_def) -> None:
    features = _features(catch_def="features")
    given = {
        key: features if value == "features" else _context() if value == "context" else value
        for key, value in given.items()
    }

    found = coerce_geographic_derived_features(**given)

    if catch_def is None:
        assert found is None
    elif catch_def == "duck":
        assert found is given["geographic_features"]
    else:
        assert found.catch_def == catch_def


def test_a_runtime_that_holds_the_bundle_hands_it_over() -> None:
    features = _features()
    runtime = SimpleNamespace(get_geographic_derived_features=lambda: features)

    assert coerce_geographic_derived_features(geographic=runtime) is features


def test_the_river_trace_is_read_on_the_bundle_when_the_network_drew_one() -> None:
    trace = RiverMeshTrace.from_geometries(
        source_kind="geographic_generated",
        crs_wkt="EPSG:2154",
        geometries=[LineString([(0, 0), (1, 0)])],
    )

    with_trace = _features(rivers=RiverNetworkProducts(enabled=True, river_mesh_trace=trace))

    assert resolve_river_mesh_trace(geographic_features=with_trace) is trace
    assert resolve_river_mesh_trace(geographic_features=_features()) is None
    assert resolve_river_mesh_trace() is None
