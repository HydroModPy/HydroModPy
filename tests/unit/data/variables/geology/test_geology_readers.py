"""Offline tests of the geology readers, processing helpers and BRGM cache builders."""

from __future__ import annotations

import zipfile
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from hydromodpy.data.variables.geology import io as geo_io
from hydromodpy.data.variables.geology import processing as proc
from hydromodpy.data.variables.geology.apis import brgm_1m, brgm_50k
from hydromodpy.data.variables.geology.apis.fgeol import bbox_hash, find_fgeol_shp

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (12, "12"),
        (np.int64(3), "3"),
        (12.0, "12"),
        (12.5, "12.5"),
        (np.float32(4.0), "4"),
        (float("nan"), "nan"),
        ("  A31 ", "A31"),
    ],
)
def test_normalize_zone_key(raw, expected):
    assert proc.normalize_zone_key(raw) == expected


def test_encode_numeric_raster_skips_nodata_and_nan():
    raw = np.array([[5.0, 5.0, np.nan], [-1.0, 2.0, 2.0]])
    codes, mapping = proc.encode_numeric_raster(raw, nodata_value=-1)
    assert codes.dtype == np.int32
    assert codes.tolist() == [[2, 2, 0], [0, 1, 1]]
    assert mapping == {1: "2", 2: "5"}


def test_encode_numeric_raster_all_invalid_and_bad_ndim():
    codes, mapping = proc.encode_numeric_raster(np.full((2, 2), np.nan))
    assert not codes.any()
    assert mapping == {}
    with pytest.raises(ValueError, match="2D array"):
        proc.encode_numeric_raster(np.ones(3))


def test_landsea_override_reuses_or_adds_zone():
    codes = np.array([[1, 2], [1, 2]])
    sea = np.array([[0.0, 1.0], [np.nan, 1.0]])
    out, mapping = proc.apply_landsea_override(
        codes, encoded_to_zone={1: "A", 2: "B"}, landsea_array=sea
    )
    assert out.tolist() == [[3, 2], [1, 2]]
    assert mapping == {1: "A", 2: "B", 3: "1"}
    out, mapping = proc.apply_landsea_override(
        codes, encoded_to_zone={1: "A", 2: "B"}, landsea_array=sea, override_zone_key="B"
    )
    assert out.tolist() == [[2, 2], [1, 2]]
    assert mapping == {1: "A", 2: "B"}
    assert codes.tolist() == [[1, 2], [1, 2]]


def test_landsea_override_without_sea_cell_and_shape_mismatch():
    codes = np.array([[1, 2]])
    out, mapping = proc.apply_landsea_override(
        codes, encoded_to_zone={1: "A"}, landsea_array=np.array([[5.0, 5.0]])
    )
    assert out.tolist() == [[1, 2]]
    assert mapping == {1: "A"}
    with pytest.raises(ValueError, match="must match encoded_codes shape"):
        proc.apply_landsea_override(codes, encoded_to_zone={}, landsea_array=np.zeros((2, 2)))


@pytest.fixture
def zones():
    return gpd.GeoDataFrame(
        {"zone_key": ["a", "b", "c"], "kind": ["land", " Sea ", "SEA"]},
        geometry=[box(0, 0, 1, 1)] * 3,
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"enabled": False}, "disabled"),
        ({"zone_key_column": "nope"}, "missing_zone_key_column:nope"),
        ({"zone_key_column": " "}, "missing_zone_key_column:"),
        ({"sea_field": "nofield"}, "missing_field:nofield"),
        ({"sea_value": "lake"}, "no_matching_sea_polygon"),
        ({}, "ok"),
    ],
)
def test_uniformize_sea_zone(zones, kwargs, reason):
    args = {"sea_field": "kind", "sea_value": "sea", "sea_zone_key": "SEA"} | kwargs
    out, info = proc.uniformize_sea_zone_on_dataframe(zones, **args)
    applied = reason == "ok"
    assert info["applied"] is applied
    assert info["reason"] == reason
    assert out["zone_key"].tolist() == (["a", "SEA", "SEA"] if applied else ["a", "b", "c"])
    assert info["count"] == (2 if applied else 0)


def test_build_zone_class_index(zones):
    out, counts = proc.build_zone_class_index_on_dataframe(zones)
    assert out["class_idx"].tolist() == [0.0, 1.0, 2.0]
    assert counts.to_dict() == {"a": 1, "b": 1, "c": 1}
    blank = zones.assign(zone_key=["a", " ", "b"])
    out, _ = proc.build_zone_class_index_on_dataframe(blank, class_index_column="cls")
    assert len(out) == 2
    assert "cls" in out.columns


@pytest.mark.parametrize(
    ("zone_keys", "kwargs", "error", "match"),
    [
        (["a", "b", "c"], {"zone_key_column": ""}, ValueError, "cannot be empty"),
        (["a", "b", "c"], {"zone_key_column": "missing"}, KeyError, "Missing zone key column"),
        ([" ", " ", " "], {}, ValueError, "No non-empty zone key"),
        (["x", "x", "x"], {}, ValueError, "Only one geology class"),
    ],
)
def test_build_zone_class_index_errors(zones, zone_keys, kwargs, error, match):
    with pytest.raises(error, match=match):
        proc.build_zone_class_index_on_dataframe(zones.assign(zone_key=zone_keys), **kwargs)


@pytest.mark.parametrize(
    ("path", "kind", "expected"),
    [
        ("a.TIF", "auto", "raster"),
        ("a.tiff", "auto", "raster"),
        ("a.shp", "auto", "vector"),
        ("a.geojson", "auto", "vector"),
        ("a.csv", " Raster ", "raster"),
    ],
)
def test_infer_source_kind(path, kind, expected):
    assert geo_io.infer_source_kind(path, kind) == expected


def test_infer_source_kind_unknown_extension():
    with pytest.raises(ValueError, match="Cannot infer source kind from extension '.csv'"):
        geo_io.infer_source_kind("a.csv")


def test_resolve_data_path(tmp_path):
    absolute = tmp_path / "x.tif"
    assert geo_io.resolve_data_path(str(absolute)) == str(absolute)
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "local_geo.tif").write_bytes(b"")
    found = geo_io.resolve_data_path("local_geo.tif", config_path=cfg_dir / "run.toml")
    assert found == str((cfg_dir / "local_geo.tif").resolve())
    missing = geo_io.resolve_data_path("no_such_geo.tif", config_path=cfg_dir / "run.toml")
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


def test_vector_grid_other_crs_and_clip(tmp_path, raster, clip_file):
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
    sea[9, :] = 0.0
    landsea = {"enabled": True, "path": write_tif(tmp_path / "sea.tif", sea), "override_code": "99"}
    out = geo_io.load_geology_encoded_grid({"source": {"path": raster}, "landsea": landsea})
    assert out["encoded_to_zone"] == {1: "7", 2: "12", 3: "99"}
    assert (out["encoded_codes"][9] == 3).all()
    assert (out["encoded_codes"][:9] != 3).all()


def test_landsea_clip_masks_cells_outside_polygon(tmp_path, clip_file):
    lsm = geo_io._load_landsea_raster(
        write_tif(tmp_path / "sea.tif", np.zeros((N, N))),
        target_shape=(N, N),
        target_transform=from_origin(X0, Y0, RES, RES),
        target_crs=rasterio.crs.CRS.from_string(CRS),
        clip_polygon_path=clip_file,
    )
    assert np.isnan(lsm[:, 5:]).all()
    assert (lsm[:, :5] == 0).all()


def test_unsupported_kind_and_no_zone(tmp_path):
    with pytest.raises(ValueError, match="Unsupported source kind 'csv'"):
        geo_io.load_geology_encoded_grid({"source": {"path": "x.txt", "kind": "csv"}})
    empty = write_tif(tmp_path / "empty.tif", np.full((N, N), -9999), nodata=-9999)
    with pytest.raises(ValueError, match="produced no valid zone code"):
        geo_io.load_geology_encoded_grid({"source": {"path": empty}})


def test_vector_without_usable_code(tmp_path, raster):
    vec = write_vector(tmp_path / "v.gpkg", ["", "  "])
    cfg = {"source": {"path": vec, "code_field": "CODE", "reference_raster_path": raster}}
    with pytest.raises(ValueError, match="No valid vector geology feature with usable code"):
        geo_io.load_geology_encoded_grid(cfg)


def test_vector_missing_field_and_disjoint_clip(tmp_path, raster):
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    cfg = {"source": {"path": vec, "code_field": "NOPE", "reference_raster_path": raster}}
    with pytest.raises(KeyError, match="Missing vector field 'NOPE'"):
        geo_io.load_geology_encoded_grid(cfg)
    far = tmp_path / "far.gpkg"
    gpd.GeoDataFrame(geometry=[box(5e5, 5e5, 5e5 + 10, 5e5 + 10)], crs=CRS).to_file(
        far, driver="GPKG"
    )
    cfg = {
        "source": {"path": vec, "code_field": "CODE", "reference_raster_path": raster},
        "clip_polygon_path": str(far),
    }
    with pytest.raises(ValueError, match="intersects clip polygon"):
        geo_io.load_geology_encoded_grid(cfg)


def test_clip_polygon_file_without_valid_geometry(tmp_path):
    empty = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=CRS)).to_file(empty, driver="GPKG")
    with pytest.raises(ValueError, match="has no geometry"):
        geo_io._load_clip_gdf(str(empty))
    blank = tmp_path / "blank.gpkg"
    gpd.GeoDataFrame(geometry=[Polygon()], crs=CRS).to_file(blank, driver="GPKG")
    with pytest.raises(ValueError, match="only empty geometries"):
        geo_io._load_clip_gdf(str(blank))


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


@pytest.mark.parametrize(
    ("source", "error", "match"),
    [
        ({}, KeyError, "source.path"),
        ({"path": "a.tif"}, ValueError, "requires source.kind='vector'"),
        ({"path": "VEC", "code_field": " "}, KeyError, "'code_field' is required"),
        ({"path": "VEC", "code_field": "NOPE"}, KeyError, "Missing vector field 'NOPE'"),
    ],
)
def test_vector_dataframe_loader_errors(tmp_path, source, error, match):
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    source = {k: (vec if v == "VEC" else v) for k, v in source.items()}
    with pytest.raises(error, match=match):
        geo_io.load_vector_geology_dataframe({"source": source})


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
    bad = {"source": {"path": "a", "kind": "x"}}
    with pytest.raises(ValueError, match="Unsupported source kind"):
        geo_io.load_geology_encoded_grid_on_raster_support(bad, raster_support=support())


def test_grid_from_raster_support_errors():
    with pytest.raises(ValueError, match="raster_support is required"):
        geo_io._grid_from_raster_support(None)
    with pytest.raises(ValueError, match="missing required grid metadata: xmin, ymax, dx, dy"):
        geo_io._grid_from_raster_support(SimpleNamespace(nrows=1, ncols=1))


def test_data_source_facade(tmp_path, raster):
    src = geo_io.default_geology_data_source()
    assert isinstance(src, geo_io.GeologyDataIO)
    assert src.normalize_zone_key(3.0) == "3"
    assert src.resolve_data_path(raster) == raster
    cfg = {"source": {"path": raster}}
    assert src.load_encoded_grid(cfg)["encoded_to_zone"] == {1: "7", 2: "12"}
    on_support = src.load_encoded_grid_on_raster_support(cfg, raster_support=support())
    assert on_support["source_kind"] == "raster"
    vec = write_vector(tmp_path / "v.gpkg", ["A", "B"])
    frame = src.load_vector_dataframe({"source": {"path": vec, "code_field": "CODE"}})
    assert len(frame["gdf"]) == 2


def fgeol_gdf(crs=CRS):
    geoms = [box(1000, 1000, 2000, 2000), box(3000, 3000, 4000, 4000)]
    return gpd.GeoDataFrame({"CODE_LEG": ["a", "b"]}, geometry=geoms, crs=CRS).to_crs(crs)


def make_zip(path, tmp_path, *, name="X_S_FGEOL_2154", crs=CRS):
    shp_dir = tmp_path / f"shp_{path.stem}"
    shp_dir.mkdir()
    fgeol_gdf(crs).to_file(shp_dir / f"{name}.shp")
    with zipfile.ZipFile(path, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)
    return path


def test_fgeol_helpers(tmp_path):
    assert bbox_hash((0, 1, 2, 3)) == bbox_hash((0.001, 1.0, 2.0, 3.004))
    assert bbox_hash((0, 1, 2, 3)) != bbox_hash((0, 1, 2, 4))
    assert find_fgeol_shp(tmp_path) is None
    (tmp_path / "sub").mkdir()
    shp = tmp_path / "sub" / "D_S_FGEOL_2154.shp"
    shp.write_bytes(b"")
    assert find_fgeol_shp(tmp_path) == shp


def test_brgm_1m_builds_from_local_archive_and_crops(tmp_path):
    out = tmp_path / "cache"
    out.mkdir()
    make_zip(out / "FR_vecteur.zip", tmp_path, crs="EPSG:4326")
    full = brgm_1m.fetch_brgm_1m(output_dir=out)
    assert full.name == "geology_brgm_1m_france.gpkg"
    gdf = gpd.read_file(full)
    assert gdf.crs.to_epsg() == 2154
    assert len(gdf) == 2
    bbox = (900, 900, 1500, 1500)
    cropped = brgm_1m.fetch_brgm_1m(output_dir=out, bbox=bbox)
    assert cropped.name == f"geology_brgm_1m_{bbox_hash(bbox)}.gpkg"
    assert gpd.read_file(cropped)["CODE_LEG"].tolist() == ["a"]
    assert brgm_1m.fetch_brgm_1m(output_dir=out, bbox=bbox) == cropped
    with pytest.raises(ValueError, match="intersects the requested bbox"):
        brgm_1m.fetch_brgm_1m(output_dir=out, bbox=(10, 10, 20, 20))


def test_brgm_1m_archive_without_fgeol_layer(tmp_path):
    zip_path = make_zip(tmp_path / "FR_vecteur.zip", tmp_path, name="OTHER_LAYER")
    with pytest.raises(FileNotFoundError, match="S_FGEOL_2154.shp"):
        brgm_1m._build_national_gpkg(zip_path, tmp_path / "out.gpkg")


def test_brgm_50k_department_from_local_archive(tmp_path):
    make_zip(tmp_path / "GEO050K_HARM_022.zip", tmp_path, crs="EPSG:4326")
    built = brgm_50k._download_department("22", cache_dir=tmp_path)
    assert built == tmp_path / "GEO050K_HARM_022" / "geology_50k_022.gpkg"
    assert gpd.read_file(built).crs.to_epsg() == 2154
    assert brgm_50k._download_department("22", cache_dir=tmp_path) == built


def test_brgm_50k_bad_archives_return_none(tmp_path):
    def build(zip_path, code):
        return brgm_50k._build_department_gpkg(
            "http://invalid.test/x.zip", zip_path, tmp_path / code, tmp_path / code / "d.gpkg", code
        )

    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert build(bad, "001") is None
    assert not bad.exists()
    no_layer = make_zip(tmp_path / "nolayer.zip", tmp_path, name="OTHER")
    assert build(no_layer, "002") is None


def test_brgm_50k_download_failure_returns_none(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(brgm_50k.urllib.request, "urlretrieve", boom)
    result = brgm_50k._build_department_gpkg(
        "http://invalid.test/x.zip",
        tmp_path / "z.zip",
        tmp_path / "d",
        tmp_path / "d" / "g.gpkg",
        "003",
    )
    assert result is None


def test_brgm_50k_merge_and_crop_from_cached_departments(tmp_path, monkeypatch):
    from hydromodpy.catchment.administrative import france

    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: ["022", "029"])
    dept_dir = tmp_path / "out" / "departments_50k"
    for code, shift in (("022", 0), ("029", 5000)):
        d = dept_dir / f"GEO050K_HARM_{code}"
        d.mkdir(parents=True)
        gdf = fgeol_gdf()
        gdf["geometry"] = gdf.translate(shift, 0)
        gdf["CODE_LEG"] = [f"{code}a", f"{code}b"]
        gdf.to_file(d / f"geology_50k_{code}.gpkg", driver="GPKG")
    bbox = (900, 900, 6000, 2500)
    merged = brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=bbox)
    gdf = gpd.read_file(merged)
    assert sorted(gdf["CODE_LEG"]) == ["022a", "029a"]
    assert gdf.crs.to_epsg() == 2154
    assert brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=bbox) == merged
    with pytest.raises(ValueError, match="No geology feature intersects"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path / "out", bbox=(10, 10, 20, 20))


def test_brgm_50k_without_department(tmp_path, monkeypatch):
    from hydromodpy.catchment.administrative import france

    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: [])
    with pytest.raises(ValueError, match="No department found overlapping bbox"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path, bbox=(0, 0, 1, 1))
    monkeypatch.setattr(france, "find_departments_in_bbox", lambda bbox: ["022"])
    monkeypatch.setattr(brgm_50k, "_download_department", lambda *a, **k: None)
    with pytest.raises(ValueError, match="No 50K geology data could be downloaded"):
        brgm_50k.fetch_brgm_50k(output_dir=tmp_path, bbox=(0, 0, 1, 1))
