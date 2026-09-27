"""The permanent part of the mapped network travels under its own role.

The hydrography loader names the file in its load result; the geographic
bundle lifts it as ``reference_permanent`` beside ``reference``, and a run
read back later answers for it by that role. A consumer picks the role and
never learns which provider said which reach flows all year.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
    attach_reference_hydrographic_network,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
    canonical_feature_name_for_role,
    default_vector_filename_for_role,
)

pytestmark = pytest.mark.fast


def _lines(path: Path, n: int) -> Path:
    gpd.GeoDataFrame(
        {"permanence": ["permanent"] * n},
        geometry=[LineString([(0.0, 100.0 * i), (1000.0, 100.0 * i)]) for i in range(n)],
        crs="EPSG:2154",
    ).to_file(path)
    return path


def _load_result(*, vector_path: Path, permanent_vector_path: Path | None) -> LoadResult:
    array = np.zeros((2, 2))
    record = FieldRecord(
        variable=HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
        source="hydrography",
        unit="",
        data=xr.Dataset({HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME: (("y", "x"), array)}),
        bbox=(0.0, 0.0, 2.0, 2.0),
        crs="EPSG:2154",
        metadata={
            "vector_path": str(vector_path),
            "permanent_vector_path": (
                str(permanent_vector_path) if permanent_vector_path is not None else None
            ),
        },
    )
    return LoadResult(fields=[record])


def test_the_role_has_its_own_feature_and_file_names() -> None:
    assert (
        canonical_feature_name_for_role("reference_permanent")
        == HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME
    )
    assert default_vector_filename_for_role("reference_permanent") == "streams_permanent.shp"
    HydrographicNetwork(role="reference_permanent", source_kind="hydrography_loaded")


def test_the_permanent_part_is_lifted_with_its_own_length(tmp_path: Path) -> None:
    full = _lines(tmp_path / "streams.shp", 3)
    permanent = _lines(tmp_path / "streams_permanent.shp", 1)

    network = HydrographicNetwork.permanent_from_hydrography_load_result(
        _load_result(vector_path=full, permanent_vector_path=permanent)
    )

    assert network is not None
    assert network.role == "reference_permanent"
    assert network.vector_path == str(permanent)
    assert network.crs == "EPSG:2154"
    assert network.metrics["network_total_length_m"] == pytest.approx(1000.0)


def test_a_load_result_without_a_permanent_part_lifts_none(tmp_path: Path) -> None:
    """Never the full network under this role: that would be a wrong answer."""
    full = _lines(tmp_path / "streams.shp", 3)

    assert (
        HydrographicNetwork.permanent_from_hydrography_load_result(
            _load_result(vector_path=full, permanent_vector_path=None)
        )
        is None
    )
    assert (
        HydrographicNetwork.permanent_from_hydrography_load_result(
            _load_result(vector_path=full, permanent_vector_path=tmp_path / "gone.shp")
        )
        is None
    )


def test_attaching_the_reference_attaches_its_permanent_part(tmp_path: Path) -> None:
    full = _lines(tmp_path / "streams.shp", 3)
    permanent = _lines(tmp_path / "streams_permanent.shp", 1)
    watershed = tmp_path / "watershed.shp"
    gpd.GeoDataFrame(geometry=[box(0.0, -50.0, 1000.0, 400.0)], crs="EPSG:2154").to_file(watershed)
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed),
            watershed_box_shp="watershed_box.shp",
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(),
    )

    updated = attach_reference_hydrographic_network(
        features, _load_result(vector_path=full, permanent_vector_path=permanent)
    )

    assert updated.reference_hydrographic_network is not None
    assert updated.reference_permanent_hydrographic_network is not None
    assert updated.reference_permanent_hydrographic_network.vector_path == str(permanent)
    assert [n.role for n in updated.hydrographic_networks.iter_available()] == [
        "reference",
        "reference_permanent",
    ]
