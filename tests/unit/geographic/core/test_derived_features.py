"""The bundle of geographic products handed to the workflow and to the domain."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic.core.derived_features import (
    DomainGeographicContext,
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
    attach_reference_hydrographic_network,
    coerce_geographic_derived_features,
    resolve_river_mesh_trace,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from tests._helpers.geographic_cases import hydrography_load_result, write_features, write_lines

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


def test_attaching_the_reference_attaches_its_permanent_part(tmp_path: Path) -> None:
    full = write_lines(tmp_path / "streams.shp", 3)
    permanent = write_lines(tmp_path / "streams_permanent.shp", 1)
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, -50.0, 1000.0, 400.0)])
    features = _features(str(watershed))
    result = hydrography_load_result(vector_path=full, permanent_vector_path=permanent)
    updated = attach_reference_hydrographic_network(features, result)
    assert updated is not features
    assert updated.generated_hydrographic_network is GENERATED
    assert updated.reference_hydrographic_network.vector_path == str(full)
    assert updated.reference_permanent_hydrographic_network.vector_path == str(permanent)
    roles = [n.role for n in updated.hydrographic_networks.iter_available()]
    assert roles == ["reference", "reference_permanent", "generated"]
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
    assert (context.x_outlet, context.y_outlet, context.regional_dem_path) == (1.0, 2.0, "dem.tif")
    assert lifted.boundaries == features.boundaries
    assert lifted.catchment_area_km2 == 3.5
    assert lifted.rivers.enabled is False
    assert lifted.to_domain_geographic_context() == context
    bare = _features().to_domain_geographic_context()
    assert (bare.x_outlet, bare.regional_dem_path) == (None, None)


BUNDLE = _features(catch_def="features")
DUCK = SimpleNamespace(rivers=1, to_domain_geographic_context=id)
VIEW = _features(catch_def="dem").to_domain_geographic_context()


@pytest.mark.parametrize(
    ("given", "found"),
    [
        ({"geographic_features": BUNDLE}, BUNDLE),
        ({"geographic_features": DUCK}, DUCK),
        ({"geographic": SimpleNamespace(get_geographic_derived_features=lambda: None)}, None),
        ({"geographic": SimpleNamespace(get_domain_geographic_context=lambda: VIEW)}, "dem"),
        ({"geographic": SimpleNamespace(get_geographic_derived_features=lambda: BUNDLE)}, BUNDLE),
        ({"domain_geographic": VIEW}, "dem"),
        ({"domain_geographic": object()}, None),
        ({}, None),
    ],
    ids=[
        "the bundle",
        "a bundle-like object",
        "a runtime with no bundle",
        "a runtime with a domain view",
        "a runtime with the bundle",
        "a domain view",
        "not a domain view",
        "nothing",
    ],
)
def test_the_bundle_is_found_on_whatever_runtime_object_carries_it(given, found) -> None:
    bundle = coerce_geographic_derived_features(**given)
    if isinstance(found, str):
        assert bundle.catch_def == found
    else:
        assert bundle is found


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
