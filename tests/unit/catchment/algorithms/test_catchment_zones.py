"""The zone rasters: catchment core, buffer ring and outside, or one uniform zone."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from shapely.geometry import Polygon, box

from hydromodpy.catchment.algorithms.catchment_zones import (
    CatchmentZoneCode,
    build_catchment_zone_codes,
)
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff


def _zones(tmp_path: Path, **options):
    triangle = write_features(
        tmp_path / "watershed.shp", [Polygon([(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0)])]
    )
    ring = write_features(tmp_path / "buff.shp", [box(-100.0, -100.0, 1100.0, 1100.0)])
    frame = write_features(tmp_path / "box_buff.shp", [box(-200.0, -200.0, 1200.0, 1200.0)])
    # Cover [-300, 1300] x [-300, 1300] with 100 m cells.
    reference = write_geotiff(
        tmp_path / "reference.tif", np.ones((16, 16), "uint8"), origin=(-300.0, 1300.0), cell=100.0
    )
    return build_catchment_zone_codes(
        catchment_shp=triangle,
        watershed_buff_shp=ring,
        watershed_box_buff_shp=frame,
        reference_raster_path=reference,
        **options,
    )


def test_the_core_lies_inside_the_ring_inside_the_domain_and_the_rest_is_outside(tmp_path):
    products = _zones(tmp_path, zone_codes_tif_path=tmp_path / "out" / "zones.tif")
    # Without an output path the zones stay in memory.
    assert _zones(tmp_path / "memory").zone_codes_tif is None
    codes = products.zone_codes
    with rasterio.open(products.zone_codes_tif) as src:
        np.testing.assert_array_equal(src.read(1), codes)
        assert src.nodata == 0
    # Row 0 and column 0 lie outside the buffered box, rows 1 and 14 in the frame.
    assert (codes[0, :] == 0).all() and (codes[:, 0] == 0).all()
    assert codes[1, 1] == CatchmentZoneCode.DOMAIN_OUTSIDE_BUFFER
    assert codes[2, 13] == CatchmentZoneCode.BUFFER_RING
    assert codes[11, 4] == CatchmentZoneCode.CATCHMENT_CORE
    core = int((codes == CatchmentZoneCode.CATCHMENT_CORE).sum())
    ring = int((codes == CatchmentZoneCode.BUFFER_RING).sum())
    assert 0 < core < core + ring <= 12 * 12


@pytest.mark.parametrize("missing", ["gone.shp", "empty.shp"])
def test_a_zone_polygon_file_missing_or_empty_is_refused(tmp_path, missing):
    reference = write_geotiff(tmp_path / "reference.tif", np.ones((2, 2)))
    if missing == "empty.shp":
        write_features(tmp_path / missing, [])
    polygon = tmp_path / missing
    shapes = dict(catchment_shp=polygon, watershed_buff_shp=polygon, watershed_box_buff_shp=polygon)
    with pytest.raises((FileNotFoundError, ValueError), match="polygon shapefile"):
        build_catchment_zone_codes(**shapes, reference_raster_path=reference)
