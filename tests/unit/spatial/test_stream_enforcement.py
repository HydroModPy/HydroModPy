"""Burn the observed stream network into the routing DEM before D8 routing."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.stream_enforcement import (
    burn_streams_into_routing_dem,
    check_catchment_area_drift,
    streams_from_config,
)

_N = 20
_RES = 10.0
_TRANSFORM = from_origin(0.0, _N * _RES, _RES, _RES)  # top-left (0, 200), 10 m cells
# Plane sloping from 100 m (north) to 60 m (south): one row step is 40/19 m, which
# is the drop a trench along a north-south line has to clear.
_ROW_DROP = 40.0 / (_N - 1)
_DEM = np.tile((100.0 - 40.0 * np.arange(_N) / (_N - 1))[:, None], (1, _N)).astype("float32")
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])


def _write_dem(path: str) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(_DEM, 1)


def _burn(tmp_path, **kwargs):
    raw = str(tmp_path / "raw.tif")
    out = str(tmp_path / "routing.tif")
    _write_dem(raw)
    report = burn_streams_into_routing_dem(
        dem_in_path=raw,
        dem_out_path=out,
        stream_lines=kwargs.pop("stream_lines", [_STREAM]),
        **kwargs,
    )
    with rasterio.open(out) as src:
        return report, src.read(1), src.crs


def test_constant_burn_lowers_only_the_mapped_cells(tmp_path) -> None:
    report, burned, crs = _burn(tmp_path, mode="constant", depth_m=30.0)

    trench = np.isclose(burned, _DEM - 30.0)
    assert report.stream_cells == _N
    assert report.depth_m == pytest.approx(30.0)
    # Exactly one column, all its rows, and nothing else moved.
    assert trench.sum() == _N
    assert np.array_equal(np.unique(np.where(trench)[1]), np.array([10]))
    assert np.allclose(burned[~trench], _DEM[~trench])
    assert str(crs) == "EPSG:2154"


def test_raw_dem_is_never_modified(tmp_path) -> None:
    raw = str(tmp_path / "raw.tif")
    _write_dem(raw)

    burn_streams_into_routing_dem(
        dem_in_path=raw,
        dem_out_path=str(tmp_path / "routing.tif"),
        stream_lines=[_STREAM],
        depth_m=30.0,
    )

    with rasterio.open(raw) as src:
        assert np.allclose(src.read(1), _DEM)


def test_an_oblique_trace_keeps_every_cell_it_clips(tmp_path) -> None:
    # all_touched: a one-cell-wide trace must not lose the cells it only clips.
    # This one spans 20 columns while dropping 4 rows, so it grazes many corners.
    oblique = LineString([(5.0, 195.0), (195.0, 155.0)])

    report, burned, _ = _burn(tmp_path, stream_lines=[oblique], depth_m=5.0)

    lowered = np.isclose(burned, _DEM - 5.0)
    assert report.stream_cells == lowered.sum()
    # One cell per column would be 20; the clipped corners bring more.
    assert report.stream_cells > _N


def test_adaptive_depth_comes_from_the_measured_relief(tmp_path) -> None:
    report, burned, _ = _burn(tmp_path, mode="adaptive", adaptive_percentile=95.0)

    # Every stream cell but the southernmost sits exactly one row step above its
    # lowest off-stream neighbour, so the 95th percentile is that row step.
    assert report.relief_p95_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert report.depth_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert np.isclose(burned, _DEM - report.depth_m).sum() == _N


def test_relief_is_reported_even_in_constant_mode(tmp_path) -> None:
    # The measurement is what tells the user whether their depth is deep enough.
    report, _, _ = _burn(tmp_path, mode="constant", depth_m=30.0)

    assert report.relief_p95_m == pytest.approx(_ROW_DROP, rel=1e-5)
    assert report.relief_max_m == pytest.approx(_ROW_DROP, rel=1e-5)


def test_a_depth_below_the_local_relief_warns(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _burn(tmp_path, mode="constant", depth_m=0.5)

    assert "shallower than the 95th percentile" in caplog.text


def test_unknown_mode_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unknown stream burn mode"):
        _burn(tmp_path, mode="fill_burn")


def test_no_geometry_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="no stream geometry"):
        _burn(tmp_path, stream_lines=[])


def test_geometry_outside_the_dem_raises(tmp_path) -> None:
    far_away = LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])

    with pytest.raises(ValueError, match="rasterize to no valid DEM cell"):
        _burn(tmp_path, stream_lines=[far_away])


class _Enforce:
    def __init__(
        self,
        *,
        enabled: bool = True,
        max_catchment_area_drift: float = 0.05,
        stream_geometry_path: Path | str | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_catchment_area_drift = max_catchment_area_drift
        self.stream_geometry_path = stream_geometry_path


class _Config:
    def __init__(self, enforce):
        self.enforce_streams = enforce


def test_area_drift_within_the_limit_passes() -> None:
    check_catchment_area_drift(
        config=_Config(_Enforce()),
        reference_area_km2=100.0,
        burned_area_km2=103.0,
    )


def test_area_drift_above_the_limit_raises() -> None:
    with pytest.raises(ValueError, match="moved the delineated"):
        check_catchment_area_drift(
            config=_Config(_Enforce()),
            reference_area_km2=100.0,
            burned_area_km2=180.0,
        )


def test_area_drift_is_not_checked_without_a_reference() -> None:
    # Burning off: nothing was measured, so nothing is claimed.
    check_catchment_area_drift(
        config=_Config(_Enforce(enabled=False)),
        reference_area_km2=None,
        burned_area_km2=180.0,
    )


def test_an_empty_reference_catchment_raises() -> None:
    with pytest.raises(ValueError, match="empty catchment"):
        check_catchment_area_drift(
            config=_Config(_Enforce()),
            reference_area_km2=0.0,
            burned_area_km2=100.0,
        )


# ---------------------------------------------------------------------------
# Where the mapped network is read from
# ---------------------------------------------------------------------------
#
# The trench is cut from the file this path names, so reading it from the
# directory the run was launched from burns whatever file of that name happens
# to sit there. The value is anchored once, when the configuration loads.

# The two copies of "streams.gpkg" differ only by where they are: the geometry
# says which one was opened.
_PROJECT_LINE = LineString([(105.0, 195.0), (105.0, 5.0)])
_DECOY_LINE = LineString([(15.0, 195.0), (15.0, 5.0)])

_PROJECT_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{project}"
project_root = "{project}"

[geographic.catchment]
catch_def = "dem"
dem_init_path = "dem.tif"

[geographic.enforce_streams]
enabled = true
stream_geometry_path = "{declared}"
"""


class _Setup:
    """The run context ``streams_from_config`` reads the target CRS from."""

    crs_project = "EPSG:2154"


def _plant_network(path: Path, line: LineString) -> None:
    """Write a one-feature network file whose geometry names the copy."""
    import geopandas as gpd

    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs="EPSG:2154").to_file(path, driver="GPKG")


def _line_in(path: Path) -> LineString:
    """The geometry the file on disk holds, read back from disk."""
    import geopandas as gpd

    return gpd.read_file(path).geometry.iloc[0]


@pytest.fixture
def project_and_decoy(tmp_path):
    """A project holding its network where the field documents it, and a trap.

    The trap is a directory holding a different file of the same name, both as a
    bare name and under the same ``data/hydrography/`` sub-path.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / "dem.tif").touch()
    _plant_network(project / "data" / "hydrography" / "streams.gpkg", _PROJECT_LINE)

    decoy = tmp_path / "elsewhere"
    _plant_network(decoy / "streams.gpkg", _DECOY_LINE)
    _plant_network(decoy / "data" / "hydrography" / "streams.gpkg", _DECOY_LINE)
    return project, decoy


def _resolved_network(project: Path, declared: str) -> Path:
    """Load the project config and return the network path it holds."""
    from hydromodpy.config import HydroModPyConfig

    cfg_path = project / "project.toml"
    cfg_path.write_text(
        _PROJECT_TOML.format(project=project.as_posix(), declared=declared),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(cfg_path)
    return Path(cfg.geographic.enforce_streams.stream_geometry_path)


@pytest.mark.parametrize("declared", ["streams.gpkg", "data/hydrography/streams.gpkg"])
def test_the_network_is_the_same_file_from_any_working_directory(
    project_and_decoy, monkeypatch, declared
) -> None:
    project, decoy = project_and_decoy

    monkeypatch.chdir(decoy)
    from_decoy = _resolved_network(project, declared)
    seen_from_decoy = _line_in(from_decoy)
    monkeypatch.chdir(project)
    from_project = _resolved_network(project, declared)
    seen_from_project = _line_in(from_project)

    assert from_decoy == from_project
    # Both copies exist under that name; only the project's holds this geometry.
    assert seen_from_decoy.equals(_PROJECT_LINE)
    assert seen_from_project.equals(_PROJECT_LINE)


def test_the_burn_opens_the_resolved_file_not_the_one_underfoot(
    project_and_decoy, monkeypatch
) -> None:
    project, decoy = project_and_decoy
    enforce = _Enforce(stream_geometry_path=_resolved_network(project, "streams.gpkg"))
    monkeypatch.chdir(decoy)

    lines = streams_from_config(enforce, _Setup())

    assert len(lines) == 1
    assert lines[0].equals(_PROJECT_LINE)


def test_a_network_that_points_to_nothing_names_the_field(tmp_path) -> None:
    missing = tmp_path / "data" / "hydrography" / "streams.gpkg"

    with pytest.raises(FileNotFoundError, match=r"enforce_streams\.stream_geometry_path"):
        streams_from_config(_Enforce(stream_geometry_path=missing), _Setup())


def test_an_unset_network_names_the_field() -> None:
    with pytest.raises(ValueError, match=r"enforce_streams\.stream_geometry_path is unset"):
        streams_from_config(_Enforce(), _Setup())


def test_a_relative_network_says_it_depends_on_the_working_directory(
    project_and_decoy, monkeypatch, caplog
) -> None:
    # A configuration built without the loader keeps the declared value. It is
    # still read, but the working-directory read is announced, not silent.
    _project, decoy = project_and_decoy
    monkeypatch.chdir(decoy)

    with caplog.at_level(logging.WARNING):
        lines = streams_from_config(_Enforce(stream_geometry_path="streams.gpkg"), _Setup())

    assert lines[0].equals(_DECOY_LINE)
    assert "read from the working directory" in caplog.text
