"""Exhaustive tests for the hydrography variable manager.

Covers:

- Config validation (HydrographySourceConfig, HydrographyConfig)
  - All four source types: custom, osm, bdtopage, euhydro
  - Profile annotations on every field
  - Field defaults, constraints, extra="forbid"
  - Model validator (custom requires path)
  - Serialization round-trips (model_dump / model_validate)

- DataManagersConfig integration
  - Typed field (HydrographyConfig, not dict)
  - from_toml_section path resolution
  - Forward reference resolution (_rebuild_forward_refs)

- Custom loader
  - Reads SHP / GPKG / GeoJSON
  - Directory auto-detection
  - Missing file / empty dir errors

- API modules (mocked HTTP)
  - OSM: Overpass query construction, parsing, empty response, custom waterway_types
  - BD Topage: WFS hits, pagination, empty bbox, custom typename/page_size
  - EU-Hydro: MapServer discovery, layer group fallback, pagination guard, empty

- HydrographyManager pipeline (mocked backend)
  - CRS reprojection
  - Clip to watershed
  - Synthetic FID field creation
  - Geometry type dispatch (Line, Polygon, Point)
  - Result dataclass contract

- HydrographyResult
  - Dataclass fields and types

- Catalog registration (SQL)
  - Register hydrography entry
  - find_cached lookup
  - Upsert behaviour
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Annotated, Literal, get_args, get_origin
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from hydromodpy.core.config.profile import Profile
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.data.variables.hydrography.result import HydrographyResult

# =====================================================================
# Helpers
# =====================================================================


def _make_lines_gdf(crs="EPSG:4326", n=3):
    """Create a small GeoDataFrame with LineString geometries."""
    lines = [LineString([(i, 48.0), (i + 0.01, 48.01)]) for i in range(n)]
    return gpd.GeoDataFrame(
        {"waterway": ["river"] * n, "id": list(range(n))},
        geometry=lines,
        crs=crs,
    )


def _make_polygon_gdf(crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs=crs,
    )


def _make_point_gdf(crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs=crs,
    )


def _watershed_gdf(crs="EPSG:2154"):
    """Fake watershed polygon big enough to contain test data once reprojected."""
    return gpd.GeoDataFrame(
        geometry=[
            Polygon(
                [
                    (300000, 6700000),
                    (400000, 6700000),
                    (400000, 6800000),
                    (300000, 6800000),
                ]
            )
        ],
        crs=crs,
    )


def _fake_geographic(tmp_path, crs="EPSG:2154"):
    """Mock geographic object with required attributes."""
    ws_path = tmp_path / "watershed.shp"
    _watershed_gdf(crs).to_file(ws_path)

    dem_path = tmp_path / "dem.tif"
    _write_dummy_tif(dem_path, crs=crs)

    geo = MagicMock()
    geo.watershed_shp = str(ws_path)
    geo.watershed_dem = str(dem_path)
    geo.crs_proj = crs
    return geo


def _write_dummy_tif(path, crs="EPSG:2154", shape=(100, 100)):
    """Write a minimal GeoTIFF for backend calls."""
    import rasterio
    from rasterio.transform import from_bounds

    transform = from_bounds(300000, 6700000, 400000, 6800000, shape[1], shape[0])
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
    ) as ds:
        ds.write(np.ones(shape, dtype=np.float32), 1)


class WhiteboxStubBackend:
    """Deterministic in-test substitute for the Whitebox backend.

    Records each call and produces real synthetic raster/vector outputs so
    the manager pipeline can be exercised end-to-end without the real
    Whitebox runtime. Tests probe ``calls`` to verify dispatch decisions
    instead of relying on tautological MagicMock ``assert_called_once``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def vector_lines_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self.calls.append(("vector_lines_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def vector_polygons_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self.calls.append(("vector_polygons_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def vector_points_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self.calls.append(("vector_points_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def set_nodata_value(self, src: str, dst: str, *, back_value: float) -> None:
        import shutil

        self.calls.append(("set_nodata_value", src, dst, back_value))
        if str(src) != str(dst):
            shutil.copy(src, dst)

    def raster_to_vector_points(self, tif: str, out_shp: str) -> None:
        self.calls.append(("raster_to_vector_points", tif, out_shp))
        Path(out_shp).parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[Point(350000, 6750000)],
            crs="EPSG:2154",
        ).to_file(out_shp)

    def method_names(self) -> list[str]:
        return [c[0] for c in self.calls]


# =====================================================================
# 1. Config - HydrographySourceConfig
# =====================================================================


@pytest.mark.fast
class TestSourceConfigValidation:
    """All source types, defaults, constraints, extra=forbid."""

    # -- Custom --
    def test_custom_valid(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        assert cfg.source == "custom"
        assert cfg.path == tmp_path / "s.shp"
        assert cfg.rasterize_field == "FID"

    def test_custom_requires_path(self):
        with pytest.raises(ValidationError, match="path"):
            HydrographySourceConfig(source="custom")

    def test_custom_with_rasterize_field(self, tmp_path):
        cfg = HydrographySourceConfig(
            source="custom", path=tmp_path / "s.gpkg", rasterize_field="CODE"
        )
        assert cfg.rasterize_field == "CODE"

    # -- OSM --
    def test_osm_defaults(self):
        cfg = HydrographySourceConfig(source="osm")
        assert cfg.waterway_types == ["river", "stream"]
        assert cfg.path is None

    def test_osm_custom_waterways(self):
        cfg = HydrographySourceConfig(source="osm", waterway_types=["canal", "drain", "ditch"])
        assert cfg.waterway_types == ["canal", "drain", "ditch"]

    # -- BD Topage --
    def test_bdtopage_defaults(self):
        cfg = HydrographySourceConfig(source="bdtopage")
        assert cfg.typename == "sa:CoursEau_FXX_Topage2025"
        assert cfg.page_size == 2000

    def test_bdtopage_custom_typename(self):
        cfg = HydrographySourceConfig(
            source="bdtopage",
            typename="sa:CoursEau_FXX_Topage2019",
            page_size=500,
        )
        assert cfg.typename == "sa:CoursEau_FXX_Topage2019"
        assert cfg.page_size == 500

    # -- EU-Hydro --
    def test_euhydro_defaults(self):
        cfg = HydrographySourceConfig(source="euhydro")
        assert cfg.group_name == "River_Net_lines"
        assert cfg.euhydro_page_size == 1000

    def test_euhydro_custom_group(self):
        cfg = HydrographySourceConfig(
            source="euhydro", group_name="Canal_lines", euhydro_page_size=200
        )
        assert cfg.group_name == "Canal_lines"
        assert cfg.euhydro_page_size == 200

    # -- Rejection --
    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            HydrographySourceConfig(source="nasa")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            HydrographySourceConfig(source="osm", magic_option=42)

    # -- Serialization round-trip --
    def test_model_dump_round_trip(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        dumped = cfg.model_dump(mode="python")
        restored = HydrographySourceConfig.model_validate(dumped)
        assert restored.source == cfg.source
        assert restored.path == cfg.path

    def test_json_round_trip(self, tmp_path):
        cfg = HydrographySourceConfig(source="custom", path=tmp_path / "s.shp")
        json_str = cfg.model_dump_json()
        restored = HydrographySourceConfig.model_validate_json(json_str)
        assert restored.source == "custom"


# =====================================================================
# 2. Config - Profile annotations
# =====================================================================


@pytest.mark.fast
class TestSourceConfigParamLevels:
    """Every field must carry a Profile annotation."""

    @staticmethod
    def _get_param_level(model_cls: type[BaseModel], field_name: str) -> str | None:
        info = model_cls.model_fields[field_name]
        for meta in info.metadata:
            if isinstance(meta, Profile):
                return meta.name.lower()
        return None

    @pytest.mark.parametrize(
        "field,expected_level",
        [
            ("source", "user"),
            ("path", "user"),
            ("rasterize_field", "user"),
            ("force_refresh", "dev"),
            ("typename", "dev"),
            ("page_size", "dev"),
            ("group_name", "dev"),
            ("euhydro_page_size", "dev"),
            ("waterway_types", "dev"),
        ],
    )
    def test_source_config_param_levels(self, field, expected_level):
        level = self._get_param_level(HydrographySourceConfig, field)
        assert level == expected_level, (
            f"Field '{field}' expected Profile('{expected_level}'), got '{level}'"
        )

    def test_config_sources_field_is_user(self):
        level = self._get_param_level(HydrographyConfig, "sources")
        assert level == "user"


# =====================================================================
# 3. Config - HydrographyConfig (container)
# =====================================================================


@pytest.mark.fast
class TestHydrographyConfigContainer:
    def test_single_source(self, tmp_path):
        cfg = HydrographyConfig(sources=[{"source": "custom", "path": str(tmp_path / "s.shp")}])
        assert len(cfg.sources) == 1

    def test_multi_source_all_types(self, tmp_path):
        cfg = HydrographyConfig(
            sources=[
                {"source": "custom", "path": str(tmp_path / "s.shp")},
                {"source": "osm"},
                {"source": "bdtopage"},
                {"source": "euhydro"},
            ]
        )
        assert len(cfg.sources) == 4
        assert [s.source for s in cfg.sources] == ["custom", "osm", "bdtopage", "euhydro"]

    def test_empty_sources_rejected(self):
        with pytest.raises(ValidationError):
            HydrographyConfig(sources=[])

    def test_extra_field_on_config_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            HydrographyConfig(
                sources=[{"source": "osm"}],
                unknown_key="x",
            )

    def test_config_extra_forbid(self):
        assert HydrographyConfig.model_config.get("extra") == "forbid"


# =====================================================================
# 4. DataManagersConfig integration
# =====================================================================


@pytest.mark.fast
class TestDataManagersConfigIntegration:
    def test_hydrography_field_is_typed(self):
        """The hydrography field on DataManagersConfig should be HydrographyConfig."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        info = DataManagersConfig.model_fields["hydrography"]
        # The annotation is Annotated[HydrographyConfig | None, ...]
        assert "HydrographyConfig" in str(info.annotation)

    def test_model_validate_with_hydrography(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        payload = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [{"source": "bdtopage"}],
            },
        }
        cfg = DataManagersConfig.model_validate(payload)
        assert cfg.hydrography is not None
        assert isinstance(cfg.hydrography, HydrographyConfig)
        assert cfg.hydrography.sources[0].source == "bdtopage"

    def test_from_toml_section_accepts_relative_path(self, tmp_path):
        """Relative paths in nested source configs are kept as-is by the
        top-level resolver (only top-level Path fields are resolved).
        The Pydantic model still accepts the relative string."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": "relative/streams.shp"},
                ],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
        assert cfg.hydrography.sources[0].path is not None

    def test_hydrography_in_typed_sections(self):
        """HydrographyConfig is registered in _TYPED_SECTIONS dict."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        # from_toml_section validates hydrography as typed - just check it doesn't error
        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography is not None

    def test_hydrography_not_in_types_but_section_present(self, tmp_path):
        """If hydrography is not in types but section is present, it should still validate."""
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["geology"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography is not None
        assert "hydrography" not in cfg.types

    def test_with_resolved_types_adds_hydrography(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": [],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        resolved = cfg.with_resolved_types(["hydrography"])
        assert "hydrography" in resolved.types


# =====================================================================
# 5. Result dataclass
# =====================================================================


@pytest.mark.fast
class TestHydrographyResult:
    def test_fields(self):
        names = {f.name for f in dc_fields(HydrographyResult)}
        assert names == {"streams", "tif_streams", "streams_array"}

    def test_construction(self, tmp_path):
        arr = np.zeros((10, 10))
        r = HydrographyResult(
            streams=str(tmp_path / "s.shp"),
            tif_streams=str(tmp_path / "s.tif"),
            streams_array=arr,
        )
        assert r.streams.endswith("s.shp")
        assert r.tif_streams.endswith("s.tif")
        assert r.streams_array.shape == (10, 10)


# =====================================================================
# 6. Custom loader
# =====================================================================


@pytest.mark.fast
class TestCustomLoader:
    def _write_shp(self, path: Path, gdf=None):
        if gdf is None:
            gdf = _make_lines_gdf()
        path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(path)
        return path

    def test_load_shp_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        shp = self._write_shp(tmp_path / "rivers.shp")
        cfg = HydrographySourceConfig(source="custom", path=shp)
        gdf = load_custom(cfg)
        assert not gdf.empty
        assert gdf.crs is not None

    def test_load_gpkg_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        gpkg = tmp_path / "rivers.gpkg"
        _make_lines_gdf().to_file(gpkg, driver="GPKG")
        cfg = HydrographySourceConfig(source="custom", path=gpkg)
        gdf = load_custom(cfg)
        assert not gdf.empty

    def test_load_geojson_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        gj = tmp_path / "rivers.geojson"
        _make_lines_gdf().to_file(gj, driver="GeoJSON")
        cfg = HydrographySourceConfig(source="custom", path=gj)
        gdf = load_custom(cfg)
        assert not gdf.empty

    def test_directory_auto_detection(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "data"
        subdir.mkdir()
        self._write_shp(subdir / "streams.shp")
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        gdf = load_custom(cfg)
        assert not gdf.empty

    def test_directory_empty_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cfg = HydrographySourceConfig(source="custom", path=empty_dir)
        with pytest.raises(FileNotFoundError, match="No vector or raster file"):
            load_custom(cfg)


# =====================================================================
# 7. OSM API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestOsmApi:
    BBOX = (-2.5, 47.5, -2.0, 48.0)

    def _overpass_response(self, n=5, waterway="river"):
        elements = []
        for i in range(n):
            elements.append(
                {
                    "type": "way",
                    "id": 1000 + i,
                    "tags": {"waterway": waterway},
                    "geometry": [
                        {"lat": 47.6 + i * 0.01, "lon": -2.3},
                        {"lat": 47.6 + i * 0.01, "lon": -2.2},
                    ],
                }
            )
        return {"elements": elements}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_parses_features(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps(self._overpass_response(5, "river"))
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 5
        assert str(gdf.crs) == "EPSG:4326"
        assert "waterway" in gdf.columns
        assert "intermit" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_empty_response(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps({"elements": []})
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_waterway_types_in_query(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps(self._overpass_response(2, "canal"))
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm", waterway_types=["canal"])
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 2
        # Verify query was built with "canal"
        call_params = mock_get.call_args
        query_data = (
            call_params[1]["params"]["data"] if "params" in call_params[1] else call_params[0][1]
        )
        assert "canal" in str(call_params)

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_intermittent_flag(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        elements = [
            {
                "type": "way",
                "id": 1,
                "tags": {"waterway": "stream", "intermittent": "yes"},
                "geometry": [
                    {"lat": 47.6, "lon": -2.3},
                    {"lat": 47.7, "lon": -2.2},
                ],
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"waterway": "stream"},
                "geometry": [
                    {"lat": 47.8, "lon": -2.3},
                    {"lat": 47.9, "lon": -2.2},
                ],
            },
        ]
        resp = MagicMock()
        resp.text = json.dumps({"elements": elements})
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm", waterway_types=["stream"])
        gdf = fetch(cfg, self.BBOX)
        assert gdf.iloc[0]["intermit"] == 2  # intermittent
        assert gdf.iloc[1]["intermit"] == 1  # permanent


# =====================================================================
# 8. BD Topage API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestBdTopageApi:
    BBOX = (-2.5, 47.5, -2.0, 48.0)

    def _hits_xml(self, n):
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <wfs:FeatureCollection numberMatched="{n}"
              xmlns:wfs="http://www.opengis.net/wfs/2.0"/>
        """).encode()

    def _features_json(self, n):
        features = []
        for i in range(n):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-2.3 + i * 0.01, 47.6], [-2.2 + i * 0.01, 47.7]],
                    },
                    "properties": {"gid": i, "CdOH": f"R{i:04d}"},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_with_features(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(3)
        hits_resp.raise_for_status = MagicMock()

        data_resp = MagicMock()
        data_resp.json.return_value = self._features_json(3)
        data_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, data_resp]

        cfg = HydrographySourceConfig(source="bdtopage")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3
        assert str(gdf.crs) == "EPSG:4326"
        assert "gid" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_zero_hits(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        resp = MagicMock()
        resp.content = self._hits_xml(0)
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="bdtopage")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_pagination(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(5)
        hits_resp.raise_for_status = MagicMock()

        page1_resp = MagicMock()
        page1_resp.json.return_value = self._features_json(2)
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.json.return_value = self._features_json(1)  # < page_size → stop
        page2_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, page1_resp, page2_resp]

        cfg = HydrographySourceConfig(source="bdtopage", page_size=2)
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3  # 2 + 1
        assert mock_get.call_count == 3  # hits + 2 pages

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_typename(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(1)
        hits_resp.raise_for_status = MagicMock()

        data_resp = MagicMock()
        data_resp.json.return_value = self._features_json(1)
        data_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, data_resp]

        cfg = HydrographySourceConfig(source="bdtopage", typename="sa:CoursEau_FXX_Topage2019")
        fetch(cfg, self.BBOX)

        # Verify typename was used in both calls
        for call in mock_get.call_args_list:
            params = call[1].get("params", call[0][1] if len(call[0]) > 1 else {})
            if "typeNames" in params:
                assert params["typeNames"] == "sa:CoursEau_FXX_Topage2019"


# =====================================================================
# 9. EU-Hydro API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestEuHydroApi:
    BBOX = (10.0, 45.0, 11.0, 46.0)

    def _mapserver_json(self, group_name="River_Net_lines", layer_ids=(5, 6)):
        layers = [
            {"id": 0, "name": group_name, "type": "Group Layer", "parentLayerId": -1},
        ]
        for lid in layer_ids:
            layers.append(
                {
                    "id": lid,
                    "name": f"Strahler_{lid}",
                    "type": "Feature Layer",
                    "parentLayerId": 0,
                }
            )
        return {"layers": layers}

    def _layer_query_json(self, n=3):
        features = []
        for i in range(n):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[10.0 + i * 0.01, 45.5], [10.1 + i * 0.01, 45.6]],
                    },
                    "properties": {"OBJECTID": i, "STRAHLER": 3},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_two_layers(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = self._mapserver_json(layer_ids=(5, 6))
        ms_resp.raise_for_status = MagicMock()

        name5_resp = MagicMock()
        name5_resp.json.return_value = {"name": "Strahler_5"}
        name5_resp.raise_for_status = MagicMock()

        name6_resp = MagicMock()
        name6_resp.json.return_value = {"name": "Strahler_6"}
        name6_resp.raise_for_status = MagicMock()

        data5_resp = MagicMock()
        data5_resp.json.return_value = self._layer_query_json(2)
        data5_resp.raise_for_status = MagicMock()

        data6_resp = MagicMock()
        data6_resp.json.return_value = self._layer_query_json(1)
        data6_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ms_resp, name5_resp, name6_resp, data5_resp, data6_resp]

        cfg = HydrographySourceConfig(source="euhydro")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3  # 2 + 1
        assert "layer_id" in gdf.columns
        assert "layer_name" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_no_layers_found(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = {"layers": []}
        ms_resp.raise_for_status = MagicMock()
        mock_get.return_value = ms_resp

        cfg = HydrographySourceConfig(source="euhydro")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_strahler_fallback(self, mock_get):
        """When group_name doesn't match, fallback finds layers with 'Strahler' in name."""
        from hydromodpy.data.variables.hydrography.apis.euhydro import (
            _feature_layer_ids_in_group,
        )

        ms = {
            "layers": [
                {"id": 0, "name": "Other_Group", "type": "Group Layer", "parentLayerId": -1},
                {
                    "id": 10,
                    "name": "Strahler_Order_3",
                    "type": "Feature Layer",
                    "parentLayerId": 99,
                },
            ]
        }
        ids = _feature_layer_ids_in_group(ms, "River_Net_lines")
        assert 10 in ids

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_group_and_page_size(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = self._mapserver_json(group_name="Canal_lines", layer_ids=(7,))
        ms_resp.raise_for_status = MagicMock()

        name7_resp = MagicMock()
        name7_resp.json.return_value = {"name": "Canal_7"}
        name7_resp.raise_for_status = MagicMock()

        data7_resp = MagicMock()
        data7_resp.json.return_value = self._layer_query_json(1)
        data7_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ms_resp, name7_resp, data7_resp]

        cfg = HydrographySourceConfig(
            source="euhydro", group_name="Canal_lines", euhydro_page_size=50
        )
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 1


# =====================================================================
# 10. HydrographyManager pipeline (mocked backend)
# =====================================================================


@pytest.mark.fast
class TestHydrographyManager:
    def _make_manager(self, tmp_path, sources, crs="EPSG:2154"):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path, crs=crs)
        cfg = HydrographyConfig(sources=sources)
        return HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

    def test_data_folder_created(self, tmp_path):
        mgr = self._make_manager(tmp_path, [{"source": "osm"}])
        assert (tmp_path / ".solver_scratch/_preprocessing" / "hydrography").is_dir()

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_load_pipeline_line_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        """Full pipeline with LineString data and stub backend."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        # Prepare fetched data in project CRS
        lines_gdf = _make_lines_gdf(crs="EPSG:2154", n=3)
        # Shift coords into watershed bbox
        lines_gdf.geometry = [
            LineString([(350000 + i * 100, 6750000), (350000 + i * 100, 6751000)]) for i in range(3)
        ]
        mock_fetch.return_value = lines_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()

        assert isinstance(result, HydrographyResult)
        assert result.streams.endswith("streams.shp")
        assert result.tif_streams.endswith("streams.tif")
        assert isinstance(result.streams_array, np.ndarray)

        # Stub backend dispatched to the line rasteriser, not polygon/point.
        method_names = backend.method_names()
        assert "vector_lines_to_raster" in method_names
        assert "vector_polygons_to_raster" not in method_names
        assert "vector_points_to_raster" not in method_names

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_load_pipeline_polygon_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        poly_gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[
                Polygon(
                    [
                        (350000, 6750000),
                        (351000, 6750000),
                        (351000, 6751000),
                        (350000, 6751000),
                    ]
                )
            ],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = poly_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_polygons_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, HydrographyResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_load_pipeline_point_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        pt_gdf = gpd.GeoDataFrame(
            {"id": [1, 2]},
            geometry=[Point(350000, 6750000), Point(351000, 6751000)],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = pt_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_points_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, HydrographyResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_synthetic_fid_field(self, mock_backend_factory, mock_fetch, tmp_path):
        """When rasterize_field doesn't exist in data, manager creates sequential FID."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        gdf = gpd.GeoDataFrame(
            {"name": ["Aven", "Odet"]},  # No "FID" column
            geometry=[
                LineString([(350000, 6750000), (350500, 6750500)]),
                LineString([(351000, 6751000), (351500, 6751500)]),
            ],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "bdtopage"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        mgr.load()

        # Verify the saved shapefile now has FID column
        saved_shp = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.shp"
        saved_gdf = gpd.read_file(saved_shp)
        assert "FID" in saved_gdf.columns
        assert list(saved_gdf["FID"]) == [1, 2]

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    def test_all_sources_empty_raises(self, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        mock_fetch.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        with pytest.raises(ValueError, match="empty"):
            mgr.load()

    def test_get_bbox_wgs84(self, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        bbox = mgr._get_bbox_wgs84()
        assert len(bbox) == 4
        lon_min, lat_min, lon_max, lat_max = bbox
        # Roughly France area after reprojection from EPSG:2154
        assert -10 < lon_min < lon_max < 15
        assert 40 < lat_min < lat_max < 55

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_crs_reprojection(self, mock_backend_factory, mock_fetch, tmp_path):
        """Data in EPSG:4326 gets reprojected to project CRS before clip."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        # Data in WGS84 - inside the watershed after reprojection
        gdf_4326 = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_fetch.return_value = gdf_4326

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        geo = _fake_geographic(tmp_path, crs="EPSG:2154")
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()

        # The saved shapefile should be in project CRS, not WGS84
        saved_gdf = gpd.read_file(result.streams)
        assert saved_gdf.crs is not None
        assert "2154" in str(saved_gdf.crs)


# =====================================================================
# 11. Catalog / SQL registration
# =====================================================================


@pytest.mark.fast
class TestCatalogHydrography:
    """Test that hydrography data can be registered in the DataCatalog."""

    def test_register_hydrography_entry(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)  # in-memory
        entry_id = cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/streams.shp",
            bbox=(-2.5, 47.5, -2.0, 48.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )
        assert entry_id > 0

    def test_find_cached_hydrography(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/streams.shp",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )

        # find_cached should find entries for a smaller bbox
        result = cat.find_cached(
            variable="hydrography",
            source="bdtopage",
            bbox=(-2.5, 47.5, -2.0, 48.0),
        )
        assert result is not None

    def test_upsert_same_key(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        id1 = cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/streams_v1.shp",
            file_mtime=0.0,
        )
        id2 = cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/streams_v1.shp",
            file_mtime=1.0,
        )
        # Upsert: same entry updated, not duplicated
        assert id1 == id2

    def test_list_entries(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="custom",
            file_path="/tmp/a.shp",
            is_custom=True,
            file_mtime=0.0,
        )
        cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/b.shp",
            file_mtime=0.0,
        )
        df = cat.list_entries(variable="hydrography")
        assert len(df) == 2

    def test_invalidate_entry(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/osm.shp",
            file_mtime=0.0,
        )
        cat.invalidate(variable="hydrography", source="osm")
        df = cat.list_entries(variable="hydrography")
        assert len(df) == 0

    def test_duckdb_persistence(self, tmp_path):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        db = tmp_path / "catalog.duckdb"
        cat1 = DataCatalog(db_path=db)
        cat1.register(
            variable="hydrography",
            source="euhydro",
            file_path="/tmp/eu.shp",
            file_mtime=0.0,
        )

        # Reopen from disk
        cat2 = DataCatalog(db_path=db)
        df = cat2.list_entries(variable="hydrography")
        assert len(df) == 1
        assert df.iloc[0]["source"] == "euhydro"


# =====================================================================
# 12. TOML format acceptance
# =====================================================================


@pytest.mark.fast
class TestTomlFormatAcceptance:
    """Verify various TOML layouts produce valid configs."""

    def test_minimal_custom(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [{"source": "custom", "path": str(tmp_path / "s.shp")}],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert cfg.hydrography.sources[0].source == "custom"

    def test_minimal_osm(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "osm"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].waterway_types == ["river", "stream"]

    def test_minimal_bdtopage(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "bdtopage"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].typename == "sa:CoursEau_FXX_Topage2025"

    def test_minimal_euhydro(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "euhydro"}]},
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))
        assert cfg.hydrography.sources[0].group_name == "River_Net_lines"

    def test_multi_source_toml(self, tmp_path):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {
                "sources": [
                    {"source": "custom", "path": str(tmp_path / "local.shp")},
                    {"source": "osm", "waterway_types": ["canal"]},
                    {
                        "source": "bdtopage",
                        "typename": "sa:CoursEau_FXX_Topage2019",
                        "page_size": 100,
                    },
                    {
                        "source": "euhydro",
                        "group_name": "River_Net_lines",
                        "euhydro_page_size": 500,
                    },
                ],
            },
        }
        cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)
        assert len(cfg.hydrography.sources) == 4

    def test_invalid_source_in_toml(self):
        from hydromodpy.data.data_managers_config import DataManagersConfig

        section = {
            "types": ["hydrography"],
            "hydrography": {"sources": [{"source": "invalid_api"}]},
        }
        with pytest.raises((ValidationError, ValueError)):
            DataManagersConfig.from_toml_section(section, base_dir=Path("/tmp"))


# =====================================================================
# 13. Supported formats / internal data summary
# =====================================================================


@pytest.mark.fast
class TestDocumentedContracts:
    """Verify the documented public API surface."""

    def test_source_literals(self):
        """The four supported source types are exactly these."""
        info = HydrographySourceConfig.model_fields["source"]
        # Extract Literal args from Annotated
        for arg in get_args(info.annotation):
            if get_origin(arg) is Literal or hasattr(arg, "__args__"):
                literals = set(get_args(arg))
                if literals:
                    assert literals == {"custom", "osm", "bdtopage", "euhydro"}
                    return
        # Fallback: check via model_json_schema
        schema = HydrographySourceConfig.model_json_schema()
        source_enum = schema["properties"]["source"]["enum"]
        assert set(source_enum) == {"custom", "osm", "bdtopage", "euhydro"}

    def test_custom_vector_formats(self):
        """custom.py supports SHP, GPKG, GeoJSON."""
        from hydromodpy.data.variables.hydrography.custom import _VECTOR_EXTENSIONS

        assert "*.shp" in _VECTOR_EXTENSIONS
        assert "*.gpkg" in _VECTOR_EXTENSIONS
        assert "*.geojson" in _VECTOR_EXTENSIONS

    def test_result_is_dataclass(self):
        import dataclasses

        assert dataclasses.is_dataclass(HydrographyResult)
        assert not dataclasses.is_dataclass(HydrographyConfig)

    def test_all_apis_return_epsg4326(self):
        """Documented contract: all API fetch() functions return EPSG:4326."""
        # This is verified in the individual API tests above; here we just
        # verify the modules are importable and have a fetch function.
        from hydromodpy.data.variables.hydrography.apis import bdtopage, euhydro, osm

        assert callable(osm.fetch)
        assert callable(bdtopage.fetch)
        assert callable(euhydro.fetch)

    def test_manager_variable_name(self):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        assert HydrographyManager.VARIABLE_NAME == "hydrography"

    def test_package_exports(self):
        import hydromodpy.data.variables.hydrography as pkg

        assert hasattr(pkg, "HydrographyConfig")
        assert hasattr(pkg, "HydrographySourceConfig")
        assert hasattr(pkg, "HydrographyManager")
        assert hasattr(pkg, "HydrographyResult")


# =====================================================================
# 15. Custom loader - TIF support
# =====================================================================


@pytest.mark.fast
class TestCustomLoaderTif:
    """TIF files should be returned as Path, not GeoDataFrame."""

    def test_tif_file_returns_path(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        tif = tmp_path / "hydro.tif"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=tif)
        result = load_custom(cfg)
        assert isinstance(result, Path)
        assert result == tif

    def test_tiff_file_returns_path(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        tif = tmp_path / "hydro.tiff"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=tif)
        result = load_custom(cfg)
        assert isinstance(result, Path)

    def test_tif_in_directory(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "data"
        subdir.mkdir()
        tif = subdir / "streams.tif"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        result = load_custom(cfg)
        assert isinstance(result, Path)
        assert result.suffix == ".tif"

    def test_vector_file_still_returns_gdf(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        shp = tmp_path / "rivers.shp"
        _make_lines_gdf().to_file(shp)
        cfg = HydrographySourceConfig(source="custom", path=shp)
        result = load_custom(cfg)
        assert isinstance(result, gpd.GeoDataFrame)

    def test_directory_prefers_raster_over_vector(self, tmp_path):
        """When a directory has both TIF and SHP, TIF wins."""
        from hydromodpy.data.variables.hydrography.custom import load_custom

        _make_lines_gdf().to_file(tmp_path / "rivers.shp")
        _write_dummy_tif(tmp_path / "streams.tif")
        cfg = HydrographySourceConfig(source="custom", path=tmp_path)
        result = load_custom(cfg)
        assert isinstance(result, Path)

    def test_empty_dir_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "empty"
        subdir.mkdir()
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        with pytest.raises(FileNotFoundError):
            load_custom(cfg)

    def test_raster_extensions_constant(self):
        from hydromodpy.data.variables.hydrography.custom import _RASTER_EXTENSIONS

        assert "*.tif" in _RASTER_EXTENSIONS
        assert "*.tiff" in _RASTER_EXTENSIONS


# =====================================================================
# 16. Manager - TIF pipeline
# =====================================================================


@pytest.mark.fast
class TestManagerTifPipeline:
    """Manager should use _load_from_tif when custom returns a Path."""

    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_tif_custom_skips_vector_pipeline(self, mock_backend_factory, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write a TIF with data inside the watershed bbox
        tif = tmp_path / "input_streams.tif"
        _write_dummy_tif(tif, crs="EPSG:2154")

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "custom", "path": str(tif)}],
        )
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)
        result = mgr.load()

        assert isinstance(result, HydrographyResult)
        assert result.streams is None
        assert result.tif_streams.endswith("streams.tif")
        assert isinstance(result.streams_array, np.ndarray)
        # Vector rasterisation backend should NOT have been called
        backend.vector_lines_to_raster.assert_not_called()

    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_tif_array_negative_to_nan(self, mock_backend_factory, tmp_path):
        """Negative values in the TIF should become NaN in streams_array."""
        import rasterio
        from rasterio.transform import from_bounds

        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write TIF with some negative values
        tif = tmp_path / "neg_streams.tif"
        shape = (100, 100)
        transform = from_bounds(300000, 6700000, 400000, 6800000, shape[1], shape[0])
        data = np.ones(shape, dtype=np.float32)
        data[0, 0] = -32768
        data[10, 10] = -1
        with rasterio.open(
            str(tif),
            "w",
            driver="GTiff",
            height=shape[0],
            width=shape[1],
            count=1,
            dtype="float32",
            crs="EPSG:2154",
            transform=transform,
        ) as ds:
            ds.write(data, 1)

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "custom", "path": str(tif)}],
        )
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)
        result = mgr.load()

        assert np.any(np.isnan(result.streams_array))


# =====================================================================
# 17. Catalog cache in manager
# =====================================================================


@pytest.mark.fast
class TestCatalogCacheManager:
    """Test cache hit, miss+register, force_refresh, and subsomption."""

    def _make_cached_manager(self, tmp_path, *, force_refresh=False):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        catalog = DataCatalog(db_path=None)
        data_dir = tmp_path / "cache"
        data_dir.mkdir()

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "osm", "force_refresh": force_refresh}],
        )
        mgr = HydrographyManager(
            config=cfg,
            geographic=geo,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        return mgr, catalog, data_dir

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_cache_miss_then_hit(self, mock_backend_factory, mock_osm_fetch, tmp_path):
        """First call fetches API + registers; second call hits cache."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        mgr, catalog, data_dir = self._make_cached_manager(tmp_path)

        # Prepare lines inside watershed
        lines = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_osm_fetch.return_value = lines

        # Write fake TIF for read_tif_array
        tif_path = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Catalog should have an entry
        df = catalog.list_entries(variable="hydrography")
        assert len(df) == 1

        # GPKG file should exist in data_dir
        gpkg_files = list(data_dir.glob("*.gpkg"))
        assert len(gpkg_files) == 1

        # Second call - should use cache, not call API again
        mgr2 = HydrographyManager(
            config=mgr.config,
            geographic=mgr.geographic,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        mgr2.load()
        # API was NOT called again
        assert mock_osm_fetch.call_count == 1

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_force_refresh_bypasses_cache(self, mock_backend_factory, mock_osm_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        mgr, catalog, data_dir = self._make_cached_manager(tmp_path, force_refresh=True)

        lines = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_osm_fetch.return_value = lines

        tif_path = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Even with cache entry, force_refresh should re-fetch
        mgr2 = HydrographyManager(
            config=mgr.config,
            geographic=mgr.geographic,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        mgr2.load()
        assert mock_osm_fetch.call_count == 2

    def test_no_catalog_skips_cache(self, tmp_path):
        """Without catalog, _try_load_cached returns None."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(
            config=cfg,
            geographic=geo,
            out_path=tmp_path,
            catalog=None,
            data_dir=None,
        )
        result = mgr._try_load_cached("osm", (-2, 47, -1, 49))
        assert result is None

    def test_subsume_removes_smaller_bbox(self, tmp_path):
        """After registering a bigger bbox, smaller one is subsumed."""
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        catalog = DataCatalog(db_path=None)
        data_dir = tmp_path / "cache"
        data_dir.mkdir()

        # Register a small bbox
        small_gpkg = data_dir / "small.gpkg"
        _make_lines_gdf().to_file(small_gpkg, driver="GPKG")
        small_id = catalog.register(
            variable="hydrography",
            source="osm",
            file_path=str(small_gpkg),
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )

        # Register a bigger bbox and subsume
        big_gpkg = data_dir / "big.gpkg"
        _make_lines_gdf().to_file(big_gpkg, driver="GPKG")
        big_id = catalog.register(
            variable="hydrography",
            source="osm",
            file_path=str(big_gpkg),
            bbox=(-3.0, 47.0, -1.0, 49.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )
        removed = catalog.subsume_entries(
            variable="hydrography",
            source="osm",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            date_start=None,
            date_end=None,
            exclude_id=big_id,
        )
        assert removed == 1
        # Only the big entry remains
        df = catalog.list_entries(variable="hydrography")
        assert len(df) == 1
        assert df.iloc[0]["id"] == big_id

    def test_custom_never_subsumed(self, tmp_path):
        """Custom entries (is_custom=True) are never subsumed."""
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        catalog = DataCatalog(db_path=None)
        catalog.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/custom.gpkg",
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
            is_custom=True,
            file_mtime=0.0,
        )
        removed = catalog.subsume_entries(
            variable="hydrography",
            source="osm",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            date_start=None,
            date_end=None,
        )
        assert removed == 0


# =====================================================================
# 18. Result with optional streams
# =====================================================================


@pytest.mark.fast
class TestResultOptionalStreams:
    def test_streams_none_allowed(self):
        arr = np.zeros((10, 10))
        result = HydrographyResult(
            streams=None,
            tif_streams="/tmp/s.tif",
            streams_array=arr,
        )
        assert result.streams is None
        assert result.tif_streams == "/tmp/s.tif"

    def test_streams_str_still_works(self):
        arr = np.zeros((10, 10))
        result = HydrographyResult(
            streams="/tmp/s.shp",
            tif_streams="/tmp/s.tif",
            streams_array=arr,
        )
        assert result.streams == "/tmp/s.shp"


# =====================================================================
# 19. Config - force_refresh field
# =====================================================================


@pytest.mark.fast
class TestForceRefreshConfig:
    def test_force_refresh_default_false(self):
        cfg = HydrographySourceConfig(source="osm")
        assert cfg.force_refresh is False

    def test_force_refresh_set_true(self):
        cfg = HydrographySourceConfig(source="osm", force_refresh=True)
        assert cfg.force_refresh is True

    def test_force_refresh_param_level_dev(self):
        info = HydrographySourceConfig.model_fields["force_refresh"]
        for meta in info.metadata:
            if isinstance(meta, Profile):
                assert meta == Profile.DEV
                return
        pytest.fail("force_refresh should have Profile.DEV")

    def test_force_refresh_in_model_dump(self):
        cfg = HydrographySourceConfig(source="osm", force_refresh=True)
        dumped = cfg.model_dump()
        assert dumped["force_refresh"] is True


# =====================================================================
# 20. DataStore - load_hydrography method
# =====================================================================


@pytest.mark.fast
class TestDataStoreHydrography:
    def test_load_hydrography_method_exists(self):
        from hydromodpy.data.store import DataStore

        assert hasattr(DataStore, "load_hydrography")

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager.load")
    @patch("hydromodpy.data.variables.hydrography.manager.get_whitebox_backend")
    def test_load_hydrography_delegates(self, mock_backend, mock_load, tmp_path):
        from hydromodpy.data.store import DataStore

        mock_load.return_value = HydrographyResult(
            streams=None,
            tif_streams="/tmp/s.tif",
            streams_array=np.zeros((5, 5)),
        )

        # Create minimal workspace
        (tmp_path / "data").mkdir()
        store = DataStore(workspace_root=tmp_path)

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        result = store.load_hydrography(cfg, geographic=geo, out_path=tmp_path)
        assert isinstance(result, HydrographyResult)
        mock_load.assert_called_once()
