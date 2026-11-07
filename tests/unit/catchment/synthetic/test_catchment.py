"""The synthetic runtime: an analytical support that stands where a delineation would."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.synthetic.catchment import build_synthetic_geographic
from hydromodpy.catchment.synthetic.synthetic_config import (
    FlatTopography,
    LinearTopography,
    RadialIslandTopography,
    SyntheticGeographicConfig,
    SyntheticGridConfig,
)
from hydromodpy.catchment.synthetic.topography import build_topography_values


def _build(tmp_path: Path, topography, *, case_id: str = "case", **grid):
    config = SyntheticGeographicConfig(
        case_id=case_id, grid=SyntheticGridConfig(**grid), topography=topography
    )
    return build_synthetic_geographic(config=config, output_dir=tmp_path / case_id)


def test_a_flat_surface_is_constant_and_a_rebuild_replaces_its_files(tmp_path) -> None:
    grid = {"length_x": "60 m", "length_y": "40 m", "nx": 6, "ny": 4}
    _build(tmp_path, FlatTopography(base_elevation=10.0), **grid)
    geographic = _build(tmp_path, FlatTopography(base_elevation=20.0), **grid)
    surface = geographic.surface_topo.as_array()
    assert surface.shape == (4, 6)
    assert np.allclose(surface, 20.0)
    assert Path(geographic.watershed_box_buff_dem).exists()
    assert Path(geographic.watershed_shp).exists()


def test_a_linear_surface_rises_from_right_to_left(tmp_path) -> None:
    law = LinearTopography(base_elevation=20.0, right_to_left_amplitude=5.0)
    surface = _build(tmp_path, law, length_x="0.05 km", length_y="30 m", nx=5, ny=3)
    section = _build(tmp_path, law, case_id="section", length_x="10 m", length_y="30 m", nx=1, ny=3)
    values = surface.surface_topo.as_array()
    assert np.allclose(values[:, -1], 20.0)
    assert np.allclose(values[:, 0], 25.0)
    assert np.all(np.diff(values[0]) <= 0.0)
    assert np.allclose(section.surface_topo.as_array(), 20.0)


def test_a_radial_island_is_emerged_at_its_centre_and_submerged_offshore(tmp_path) -> None:
    law = RadialIslandTopography(base_elevation=-1.0, crest_elevation=6.0, island_radius="35 m")
    geographic = _build(tmp_path, law, length_x="120 m", length_y="120 m", nx=12, ny=12)
    surface = geographic.surface_topo.as_array()
    assert surface.shape == (12, 12)
    assert float(surface[6, 6]) > 5.0
    assert float(surface[0, 0]) == float(surface[-1, -1]) == -1.0
    assert np.count_nonzero(surface > 0.0) > 0 and np.count_nonzero(surface <= 0.0) > 0


def test_the_domain_context_is_uniform_and_reads_the_synthetic_surface(tmp_path) -> None:
    grid = dict(length_x="100 m", length_y="100 m", nx=2, ny=2, xmin=100.0, ymin=200.0)
    geographic = _build(tmp_path, FlatTopography(base_elevation=20.0), **grid)
    context = geographic.get_domain_geographic_context()
    features = geographic.get_geographic_derived_features()
    assert (context.zone_kind, context.catch_def) == ("uniform", "synthetic")
    assert context.catchment_area_km2 == 0.01
    np.testing.assert_allclose(context.surface_topo.as_array(), np.full((2, 2), 20.0))
    assert (features.catch_def, features.zone_kind) == ("synthetic", "uniform")
    assert features.rivers.river_mesh_trace is None
    np.testing.assert_allclose(features.surface_topo.as_array(), np.full((2, 2), 20.0))


def test_the_runtime_exposes_what_the_launchers_read_and_its_wgs84_centroid(tmp_path) -> None:
    x, y = 265_525.0, 6_783_450.0  # Lambert-93, west of Greenwich
    grid = dict(length_x="2 km", length_y="2 km", nx=2, ny=2, xmin=x - 1e3, ymin=y - 1e3)
    geographic = _build(tmp_path, FlatTopography(), **grid)
    assert geographic.nodata == -9999.0
    assert geographic.watershed_box_shp.endswith("watershed_box.shp")
    assert geographic.box_buff.endswith("watershed_box_buff.shp")
    assert geographic.watershed_contour_shp.endswith("watershed_contour.shp")
    assert Path(geographic.watershed_contour_tif).exists()
    longitude, latitude = geographic.centroid_long_lat
    assert longitude == pytest.approx(-2.83, abs=0.01)
    assert geographic.centroid_long_lat_Greenwich == pytest.approx([360.0 + longitude, latitude])
    georef = geographic.build_georeferencing()
    assert (georef["xmin"], georef["ymin"]) == pytest.approx((x - 1e3, y - 1e3))


def test_the_runtime_refuses_what_is_not_a_synthetic_config_or_law(tmp_path) -> None:
    with pytest.raises(TypeError, match="SyntheticGeographicConfig"):
        build_synthetic_geographic(config=SimpleNamespace(), output_dir=tmp_path)
    with pytest.raises(ValueError, match="Unsupported synthetic topography"):
        build_topography_values(topography=SimpleNamespace(), grid=SyntheticGridConfig())
