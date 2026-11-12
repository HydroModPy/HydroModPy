"""Geology maps read from a raster or a vector file onto a grid of zone codes.

Coordinates are Lambert-93 meters on a 10 m pixel grid of 10 x 10 cells. The
left half of the test raster holds zone 7, the right half zone 12, and the
corner cell is nodata.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from hydromodpy.data.variables.geology import io as geo_io
from hydromodpy.data.variables.geology.io import (
    geology_field_from_config,
    geology_field_from_toml,
)
from tests._helpers import field_cases as cases

CRS = "EPSG:2154"
X0, Y0, RES, N = 1000.0, 2000.0, 10.0, 10


def write_tif(path, array, *, nodata=None, crs=CRS):
    array = np.asarray(array, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(X0, Y0, RES, RES),
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
    return str(path)


def write_vector(path, codes, *, crs=CRS, field="CODE"):
    """Two squares covering the left and right halves of the raster grid."""
    geoms = [box(X0, Y0 - 100, X0 + 50, Y0), box(X0 + 50, Y0 - 100, X0 + 100, Y0)]
    gdf = gpd.GeoDataFrame({field: codes}, geometry=geoms, crs=CRS).to_crs(crs)
    gdf.to_file(path, driver="GPKG")
    return str(path)


def support(**over):
    """A raster support of 5 x 5 cells of 20 m on the same origin."""
    base = {"nrows": 5, "ncols": 5, "xmin": X0, "ymax": Y0, "dx": 20.0, "dy": 20.0, "crs": CRS}
    return SimpleNamespace(**(base | over))


@pytest.fixture
def raster(tmp_path):
    arr = np.full((N, N), 7.0)
    arr[:, 5:] = 12.0
    arr[0, 0] = -9999
    return write_tif(tmp_path / "geo.tif", arr, nodata=-9999)


@pytest.fixture
def clip_file(tmp_path):
    path = tmp_path / "clip.gpkg"
    gpd.GeoDataFrame(geometry=[box(X0, Y0 - 100, X0 + 50, Y0)], crs=CRS).to_file(
        path, driver="GPKG"
    )
    return str(path)


def test_field_from_a_config_mapping(tmp_path: Path):
    source = {"path": str(cases.geology_raster(tmp_path / "geology.tif")), "kind": "raster"}

    field = geology_field_from_config(
        {"id": "field_geology", "source": source, "cell_samples_per_axis": 8}
    )

    assert field.as_dict() == {
        "id": "field_geology",
        "source_kind": "raster",
        "shape": (4, 4),
        "zone_keys": ("1", "2"),
        "default_cell_samples_per_axis": 8,
    }


def test_field_from_a_toml_section(tmp_path: Path):
    path = cases.geology_raster(tmp_path / "geology.tif")
    toml = cases.write_text(
        tmp_path / "geology.toml",
        "[geology]\n"
        'id = "field_geology"\n'
        "cell_samples_per_axis = 6\n"
        f'source = {{ path = "{path}", kind = "raster" }}',
    )

    field = geology_field_from_toml(toml)

    assert field.as_dict() == {
        "id": "field_geology",
        "source_kind": "raster",
        "shape": (4, 4),
        "zone_keys": ("1", "2"),
        "default_cell_samples_per_axis": 6,
    }


def test_resolve_data_path(tmp_path):
    absolute = tmp_path / "x.tif"
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "local_geo.tif").write_bytes(b"")
    config_path = cfg_dir / "run.toml"

    assert geo_io.resolve_data_path(str(absolute)) == str(absolute)
    found = geo_io.resolve_data_path("local_geo.tif", config_path=config_path)
    assert found == str((cfg_dir / "local_geo.tif").resolve())
    missing = geo_io.resolve_data_path("no_such_geo.tif", config_path=config_path)
    assert missing.endswith("no_such_geo.tif")
    assert str(cfg_dir) not in missing


def test_raster_grid_encodes_values_and_clips(raster, clip_file):
    out = geo_io.load_geology_encoded_grid({"source": {"path": raster}})

    assert out["source_kind"] == "raster"
    assert out["encoded_to_zone"] == {1: "7", 2: "12"}
    assert out["encoded_codes"].shape == (N, N)
    assert out["encoded_codes"][0, 0] == 0
    assert out["crs"] == rasterio.crs.CRS.from_string(CRS)

    cfg = {"source": {"path": raster}, "clip_polygon_path": clip_file}
    clipped = geo_io.load_geology_encoded_grid(cfg)
    assert clipped["encoded_codes"].shape == (N, 5)
    assert clipped["encoded_to_zone"] == {1: "7"}


def test_vector_grid_rasterizes_on_reference(tmp_path, raster):
    vec = write_vector(tmp_path / "v.gpkg", ["B", "A"])
    cfg = {"source": {"path": vec, "code_field": "CODE", "reference_raster_path": raster}}

    out = geo_io.load_geology_encoded_grid(cfg)

    assert out["source_kind"] == "vector"
    assert out["encoded_to_zone"] == {1: "B", 2: "A"}
    assert set(np.unique(out["encoded_codes"][:, :5])) == {1}
    assert set(np.unique(out["encoded_codes"][:, 5:])) == {2}


def test_vector_grid_in_another_crs_and_clip(tmp_path, raster, clip_file):
    vec = write_vector(tmp_path / "v.gpkg", [1, 2], crs="EPSG:4326")
    cfg = {
        "source": {"path": vec, "code_field": "CODE", "reference_raster_path": raster},
        "clip_polygon_path": clip_file,
    }

    out = geo_io.load_geology_encoded_grid(cfg)

    assert out["encoded_to_zone"][1] == "1"
    assert (out["encoded_codes"][:, :4] == 1).all()
    assert out["encoded_codes"][:, 6:].max() == 0


def test_landsea_is_applied_on_the_grid(tmp_path, raster):
    sea = np.ones((N, N))
    sea[9, :] = 0.0  # the last row is the sea
    landsea = {"enabled": True, "path": write_tif(tmp_path / "sea.tif", sea), "override_code": "99"}

    out = geo_io.load_geology_encoded_grid({"source": {"path": raster}, "landsea": landsea})

    assert out["encoded_to_zone"] == {1: "7", 2: "12", 3: "99"}
    assert (out["encoded_codes"][9] == 3).all()
    assert (out["encoded_codes"][:9] != 3).all()


def test_landsea_clip_masks_cells_outside_polygon(tmp_path, clip_file):
    mask = geo_io._load_landsea_raster(
        write_tif(tmp_path / "sea.tif", np.zeros((N, N))),
        target_shape=(N, N),
        target_transform=from_origin(X0, Y0, RES, RES),
        target_crs=rasterio.crs.CRS.from_string(CRS),
        clip_polygon_path=clip_file,
    )

    assert np.isnan(mask[:, 5:]).all()
    assert (mask[:, :5] == 0).all()


def test_vector_dataframe_loader(tmp_path, clip_file):
    vec = write_vector(tmp_path / "v.gpkg", ["A", " "])
    cfg = {"id": "g", "source": {"path": vec, "code_field": "CODE"}}

    out = geo_io.load_vector_geology_dataframe(cfg, zone_key_column="zk")

    assert out["gdf"]["zk"].tolist() == ["A"]
    assert (out["field_id"], out["code_field"], out["source_kind"]) == ("g", "CODE", "vector")
    clipped = geo_io.load_vector_geology_dataframe(cfg | {"clip_polygon_path": clip_file})
    assert clipped["gdf"].total_bounds.tolist() == [X0, Y0 - 100, X0 + 50, Y0]
    default_id = geo_io.load_vector_geology_dataframe({"source": cfg["source"]})["field_id"]
    assert default_id == "field_geology"


def test_raster_on_raster_support_reprojects_nearest(raster, tmp_path):
    cfg = {"source": {"path": raster}}

    out = geo_io.load_geology_encoded_grid_on_raster_support(cfg, raster_support=support())

    assert out["encoded_codes"].shape == (5, 5)
    assert out["encoded_to_zone"] == {1: "7", 2: "12"}
    assert out["transform"] == from_origin(X0, Y0, 20.0, 20.0)
    assert (out["encoded_codes"][:, :2] == 1).all()

    sea = write_tif(tmp_path / "sea.tif", np.zeros((N, N)))
    cfg["landsea"] = {"enabled": True, "path": sea}
    both = geo_io.load_geology_encoded_grid_on_raster_support(cfg, raster_support=support())
    assert (both["encoded_codes"] == 3).all()
    assert both["encoded_to_zone"][3] == "1"


def test_vector_on_raster_support(tmp_path):
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"], crs="EPSG:4326")
    cfg = {"source": {"path": vec, "code_field": "CODE"}}

    out = geo_io.load_geology_encoded_grid_on_raster_support(cfg, raster_support=support())

    assert out["encoded_to_zone"] == {1: "A", 2: "B"}
    assert out["encoded_codes"][:, 0].tolist() == [1] * 5
    assert out["encoded_codes"][:, 4].tolist() == [2] * 5


def test_the_module_surface(tmp_path, raster):
    # The functions that a facade class once packed are read on the module itself.
    assert geo_io.resolve_data_path(str(raster)) == str(raster)
    assert geo_io.normalize_zone_key(3.0) == "3"
    cfg = {"source": {"path": raster}}
    assert geo_io.load_geology_encoded_grid(cfg)["encoded_to_zone"] == {1: "7", 2: "12"}
    on_support = geo_io.load_geology_encoded_grid_on_raster_support(cfg, raster_support=support())
    assert on_support["source_kind"] == "raster"
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    frame = geo_io.load_vector_geology_dataframe({"source": {"path": vec, "code_field": "CODE"}})
    assert len(frame["gdf"]) == 2


def test_unknown_extension_is_refused():
    with pytest.raises(ValueError, match="Cannot infer source kind from extension '.csv'"):
        geo_io.infer_source_kind("a.csv")


def test_unsupported_kind_and_empty_raster_are_refused(tmp_path):
    empty_raster = write_tif(tmp_path / "empty.tif", np.full((N, N), -9999), nodata=-9999)

    with pytest.raises(ValueError, match="Unsupported source kind 'csv'"):
        geo_io.load_geology_encoded_grid({"source": {"path": "x.txt", "kind": "csv"}})
    with pytest.raises(ValueError, match="produced no valid zone code"):
        geo_io.load_geology_encoded_grid({"source": {"path": empty_raster}})


def test_blank_vector_codes_are_refused(tmp_path, raster):
    blank_codes = write_vector(tmp_path / "v.gpkg", ["", "  "])
    source = {"path": blank_codes, "code_field": "CODE", "reference_raster_path": raster}

    with pytest.raises(ValueError, match="No valid vector geology feature with usable code"):
        geo_io.load_geology_encoded_grid({"source": source})


def test_missing_vector_field_and_disjoint_clip_are_refused(tmp_path, raster):
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    far = tmp_path / "far.gpkg"
    gpd.GeoDataFrame(geometry=[box(5e5, 5e5, 5e5 + 10, 5e5 + 10)], crs=CRS).to_file(
        far, driver="GPKG"
    )

    def vector(code_field, **extra):
        source = {"path": vec, "code_field": code_field, "reference_raster_path": raster}
        return {"source": source, **extra}

    with pytest.raises(KeyError, match="Missing vector field 'NOPE'"):
        geo_io.load_geology_encoded_grid(vector("NOPE"))
    with pytest.raises(ValueError, match="intersects clip polygon"):
        geo_io.load_geology_encoded_grid(vector("CODE", clip_polygon_path=str(far)))


def test_clip_file_without_valid_geometry_is_refused(tmp_path):
    no_geometry = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=CRS)).to_file(no_geometry, driver="GPKG")
    blank_geometry = tmp_path / "blank.gpkg"
    gpd.GeoDataFrame(geometry=[Polygon()], crs=CRS).to_file(blank_geometry, driver="GPKG")

    with pytest.raises(ValueError, match="has no geometry"):
        geo_io._load_clip_gdf(str(no_geometry))
    with pytest.raises(ValueError, match="only empty geometries"):
        geo_io._load_clip_gdf(str(blank_geometry))


def test_raster_support_refusals():
    with pytest.raises(ValueError, match="Unsupported source kind"):
        geo_io.load_geology_encoded_grid_on_raster_support(
            {"source": {"path": "a", "kind": "x"}}, raster_support=support()
        )
    with pytest.raises(ValueError, match="raster_support is required"):
        geo_io._grid_from_raster_support(None)
    with pytest.raises(ValueError, match="missing required grid metadata: xmin, ymax, dx, dy"):
        geo_io._grid_from_raster_support(SimpleNamespace(nrows=1, ncols=1))


VECTOR_SOURCE_REFUSALS = [
    pytest.param({}, KeyError, "source.path", id="no path"),
    pytest.param({"path": "a.tif"}, ValueError, "requires source.kind='vector'", id="raster path"),
    pytest.param(
        {"path": "VEC", "code_field": " "},
        KeyError,
        "'code_field' is required",
        id="blank code field",
    ),
    pytest.param(
        {"path": "VEC", "code_field": "NOPE"},
        KeyError,
        "Missing vector field 'NOPE'",
        id="unknown code field",
    ),
]


@pytest.mark.parametrize(("source", "error", "match"), VECTOR_SOURCE_REFUSALS)
def test_vector_dataframe_refusals(tmp_path, source, error, match):
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    source = {k: (vec if v == "VEC" else v) for k, v in source.items()}

    with pytest.raises(error, match=match):
        geo_io.load_vector_geology_dataframe({"source": source})
