"""The lake polygons of ``[geographic.enforce_lakes]`` are read from the data folder."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from hydromodpy.catchment.algorithms.ground_inputs import lakes_from_config
from tests._helpers.geographic_cases import write_features


def _setup(tmp_path: Path) -> SimpleNamespace:
    dem = tmp_path / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"")
    return SimpleNamespace(dem_path=str(dem), crs_project="EPSG:2154")


def test_lake_file_location(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    lakes = write_features(
        tmp_path / "data" / "lake_geometry" / "lakes.gpkg",
        [box(0, 0, 10, 10), box(20, 0, 30, 10)],
        crs="EPSG:4326",
    )
    beside = lakes_from_config(SimpleNamespace(lake_geometry_path=Path("lakes.gpkg")), setup)
    as_given = lakes_from_config(SimpleNamespace(lake_geometry_path=lakes), setup)
    assert len(beside) == len(as_given) == 2
    # The polygons come back in the project CRS.
    assert beside[0].bounds[0] > 1.0e5


@pytest.mark.parametrize(
    ("declared", "error", "reason"),
    [(None, ValueError, "lake_geometry_path is unset"), ("gone.gpkg", FileNotFoundError, "gone")],
)
def test_refusals(tmp_path, declared, error, reason) -> None:
    with pytest.raises(error, match=reason):
        lakes_from_config(SimpleNamespace(lake_geometry_path=declared), _setup(tmp_path))
