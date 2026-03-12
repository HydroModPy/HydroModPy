from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.geographic.synthetic import (
    SyntheticGeographicConfig,
    SyntheticGridConfig,
    SyntheticTopographyConfig,
    build_synthetic_geographic,
)


def test_flat_surface_is_constant_at_requested_elevation(tmp_path: Path) -> None:
    config = SyntheticGeographicConfig(
        case_id="flat20",
        grid=SyntheticGridConfig(
            length_x="60 m",
            length_y="40 m",
            nx=6,
            ny=4,
            xmin=0.0,
            ymin=0.0,
        ),
        topography=SyntheticTopographyConfig(
            kind="flat",
            base_elevation=20.0,
            right_to_left_amplitude=0.0,
        ),
    )

    geographic = build_synthetic_geographic(config=config, output_dir=tmp_path / "flat")
    surface = geographic.surface_topo.as_array()

    assert surface.shape == (4, 6)
    assert np.allclose(surface, 20.0)
    assert Path(geographic.watershed_box_buff_dem).exists()
    assert Path(geographic.watershed_shp).exists()


def test_linear_surface_rises_from_right_to_left(tmp_path: Path) -> None:
    config = SyntheticGeographicConfig(
        case_id="linear",
        grid=SyntheticGridConfig(
            length_x="0.05 km",
            length_y="30 m",
            nx=5,
            ny=3,
            xmin=0.0,
            ymin=0.0,
        ),
        topography=SyntheticTopographyConfig(
            kind="linear",
            base_elevation=20.0,
            right_to_left_amplitude=5.0,
        ),
    )

    geographic = build_synthetic_geographic(config=config, output_dir=tmp_path / "linear")
    surface = geographic.surface_topo.as_array()

    assert np.allclose(surface[:, -1], 20.0)
    assert np.allclose(surface[:, 0], 25.0)
    assert np.all(np.diff(surface[0]) <= 0.0)


def test_domain_context_is_uniform_and_uses_synthetic_surface(tmp_path: Path) -> None:
    config = SyntheticGeographicConfig(
        grid=SyntheticGridConfig(
            length_x="100 m",
            length_y="100 m",
            nx=2,
            ny=2,
            xmin=100.0,
            ymin=200.0,
        ),
        topography=SyntheticTopographyConfig(kind="flat", base_elevation=20.0),
    )

    geographic = build_synthetic_geographic(config=config, output_dir=tmp_path / "context")
    context = geographic.get_domain_geographic_context()

    assert context.zone_kind == "uniform"
    assert context.catch_def == "synthetic"
    assert context.catchment_area_km2 == 0.01
    np.testing.assert_allclose(context.surface_topo.as_array(), np.full((2, 2), 20.0))


def test_radial_island_surface_is_emerged_at_center_and_submerged_offshore(tmp_path: Path) -> None:
    config = SyntheticGeographicConfig(
        case_id="radial-island",
        grid=SyntheticGridConfig(
            length_x="120 m",
            length_y="120 m",
            nx=12,
            ny=12,
            xmin=0.0,
            ymin=0.0,
        ),
        topography=SyntheticTopographyConfig(
            kind="radial_island",
            base_elevation=-1.0,
            crest_elevation=6.0,
            island_radius="35 m",
        ),
    )

    geographic = build_synthetic_geographic(config=config, output_dir=tmp_path / "radial")
    surface = geographic.surface_topo.as_array()

    assert surface.shape == (12, 12)
    assert float(surface[6, 6]) > 5.0
    assert float(surface[0, 0]) == -1.0
    assert float(surface[-1, -1]) == -1.0
    assert np.count_nonzero(surface > 0.0) > 0
    assert np.count_nonzero(surface <= 0.0) > 0


def test_synthetic_runtime_exposes_launcher_compatibility_metadata(tmp_path: Path) -> None:
    geographic = build_synthetic_geographic(
        config=SyntheticGeographicConfig(),
        output_dir=tmp_path / "compat",
    )

    assert geographic.nodata == -9999.0
    assert geographic.watershed_box_shp.endswith("watershed_box.shp")
    assert geographic.box_buff.endswith("watershed_box_buff.shp")
    assert geographic.watershed_contour_shp.endswith("watershed_contour.shp")
    assert Path(geographic.watershed_contour_tif).exists()
    assert geographic.centroid_long_lat is not None
    assert geographic.centroid_long_lat_Greenwich is not None


def test_grid_lengths_accept_unit_strings_and_derive_cell_size() -> None:
    grid = SyntheticGridConfig(
        length_x="0.1 km",
        length_y="2 m",
        nx=100,
        ny=2,
    )

    assert grid.ncol == 100
    assert grid.nrow == 2
    assert grid.dx == 1.0
    assert grid.dy == 1.0
