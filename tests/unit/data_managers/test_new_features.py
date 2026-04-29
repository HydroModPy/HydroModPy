"""Tests for the 5 reimplemented features:
1. Mask-based spatial selection
2. CSV export
3. from_toml() config loading
4. Advanced station discovery
5. Completeness report
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.common.export import export_records
from hydromodpy.data.common.geo_helpers import (
    expand_bbox,
    filter_locations_by_geometry,
    geometry_to_bbox,
    load_mask_geometry,
)
from hydromodpy.data.common.validation import compute_completeness
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord

# --- Helpers ---


def _make_record(station_id, x, y, n=10, variable="discharge"):
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
            "value": range(n),
        }
    )
    return PointRecord(
        station_id=station_id,
        variable=variable,
        source="custom",
        unit="m3/s",
        frequency="D",
        data=df,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, n),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:4326"),
        source_unit="L/s",
    )


# =========================================================================
# Feature 1: Mask-based spatial selection
# =========================================================================
class TestMaskSpatialSelection:
    def test_load_mask_vector_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_mask_geometry(Path("/nonexistent.shp"))

    def test_load_mask_unsupported_format(self, tmp_path):
        p = tmp_path / "mask.xyz"
        p.write_text("dummy")
        with pytest.raises(ValueError, match="Unsupported mask format"):
            load_mask_geometry(p)

    def test_filter_locations_by_geometry(self):
        """Test filtering with a shapely box geometry."""
        pytest.importorskip("shapely")
        from shapely.geometry import box

        geom = box(-2.0, 47.0, -1.0, 49.0)
        locs = [
            StationLocation(id="A", x=-1.5, y=48.0, crs="EPSG:4326"),  # inside
            StationLocation(id="B", x=3.0, y=45.0, crs="EPSG:4326"),  # outside
            StationLocation(id="C", x=-1.2, y=48.5, crs="EPSG:4326"),  # inside
        ]
        inside = filter_locations_by_geometry(locs, geom)
        assert {loc.id for loc in inside} == {"A", "C"}

    def test_geometry_to_bbox(self):
        pytest.importorskip("shapely")
        from shapely.geometry import box

        geom = box(-2.0, 47.0, -1.0, 49.0)
        bbox = geometry_to_bbox(geom)
        assert bbox == pytest.approx((-2.0, 47.0, -1.0, 49.0))

    def test_expand_bbox(self):
        bbox = (-1.0, 48.0, 0.0, 49.0)
        expanded = expand_bbox(bbox, radius_km=50.0)
        assert expanded[0] < -1.0
        assert expanded[1] < 48.0
        assert expanded[2] > 0.0
        assert expanded[3] > 49.0

    def test_load_mask_from_vector_geojson(self, tmp_path):
        """Test loading a GeoJSON mask file."""
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import box

        geom = box(-2.0, 47.0, -1.0, 49.0)
        gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
        mask_path = tmp_path / "mask.geojson"
        gdf.to_file(mask_path, driver="GeoJSON")

        loaded_geom = load_mask_geometry(mask_path)
        bbox = geometry_to_bbox(loaded_geom)
        assert bbox[0] == pytest.approx(-2.0)
        assert bbox[3] == pytest.approx(49.0)


# =========================================================================
# Feature 2: CSV export
# =========================================================================
class TestCSVExport:
    def test_export_records(self, tmp_path):
        records = [
            _make_record("S1", -1.5, 48.0, n=10),
            _make_record("S2", -1.6, 48.1, n=5),
        ]
        result = export_records(records, tmp_path / "out", prefix="hydro")

        assert "metadata" in result
        assert "table_of_contents" in result
        assert "chronicle_S1" in result
        assert "chronicle_S2" in result

        # Check metadata CSV
        meta = pd.read_csv(result["metadata"])
        assert len(meta) == 2
        assert "station_id" in meta.columns
        assert "source_unit" in meta.columns
        assert "x" in meta.columns
        assert "y" in meta.columns
        assert meta.loc[0, "source_unit"] == "L/s"

        # Check TOC CSV
        toc = pd.read_csv(result["table_of_contents"])
        assert len(toc) == 2
        assert "file" in toc.columns
        assert "n_records" in toc.columns
        assert "source_unit" in toc.columns

        # Check chronicle CSV
        chron = pd.read_csv(result["chronicle_S1"])
        assert len(chron) == 10
        assert list(chron.columns) == ["datetime", "value"]

    def test_export_empty_records(self, tmp_path):
        result = export_records([], tmp_path / "empty")
        assert result == {}

    def test_export_no_location(self, tmp_path):
        """Records without location should still export."""
        df = pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", periods=5, freq="D"),
                "value": range(5),
            }
        )
        rec = PointRecord(
            station_id="X",
            variable="discharge",
            source="custom",
            unit="m3/s",
            frequency="D",
            data=df,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 5),
        )
        result = export_records([rec], tmp_path / "noloc", prefix="test")
        meta = pd.read_csv(result["metadata"])
        assert len(meta) == 1
        assert "x" not in meta.columns


# =========================================================================
# Feature 3: from_toml() config loading
# =========================================================================
class TestFromToml:
    def test_hydrometry_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            '[hydrometry]\n[[hydrometry.sources]]\nsource = "hubeau"\nproduct = "QmnJ"\n'
        )
        from hydromodpy.data.variables.hydrometry.config import HydrometryConfig

        cfg = HydrometryConfig.from_toml(toml_path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].source == "hubeau"
        assert cfg.sources[0].product == "QmnJ"

    def test_piezometry_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            '[piezometry]\n[[piezometry.sources]]\nsource = "hubeau"\nproduct = "level"\n'
        )
        from hydromodpy.data.variables.piezometry.config import PiezometryConfig

        cfg = PiezometryConfig.from_toml(toml_path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].product == "level"

    def test_water_quality_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            '[water_quality]\n[[water_quality.sources]]\nsource = "custom"\npath = "/tmp/wq"\n'
        )
        from hydromodpy.data.variables.water_quality.config import WaterQualityConfig

        cfg = WaterQualityConfig.from_toml(toml_path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].source == "custom"

    def test_from_toml_custom_with_mask(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            "[hydrometry]\n"
            "[[hydrometry.sources]]\n"
            'source = "custom"\n'
            'path = "/tmp/data"\n'
            'mask_path = "/tmp/mask.shp"\n'
        )
        from hydromodpy.data.variables.hydrometry.config import HydrometryConfig

        cfg = HydrometryConfig.from_toml(toml_path)
        assert cfg.sources[0].mask_path == Path("/tmp/mask.shp")

    def test_from_toml_with_discovery_params(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            "[hydrometry]\n"
            "[[hydrometry.sources]]\n"
            'source = "hubeau"\n'
            'product = "QmnJ"\n'
            "require_observations = true\n"
            "fallback_search_radius_km = 25.0\n"
        )
        from hydromodpy.data.variables.hydrometry.config import HydrometryConfig

        cfg = HydrometryConfig.from_toml(toml_path)
        assert cfg.sources[0].require_observations is True
        assert cfg.sources[0].fallback_search_radius_km == 25.0


# =========================================================================
# Feature 4: Advanced station discovery
# =========================================================================
class TestAdvancedDiscovery:
    def test_station_period_overlaps_hydro(self):
        from hydromodpy.data.variables.hydrometry.apis.hubeau import _station_period_overlaps

        # Station active 2015 to 2021, request 2020-2020 -> overlap
        assert _station_period_overlaps(
            "2015-01-01",
            "2021-12-31",
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        # Station closed before request
        assert not _station_period_overlaps(
            "2015-01-01",
            "2018-12-31",
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        # Station opened after request
        assert not _station_period_overlaps(
            "2022-01-01",
            None,
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        # No dates -> assume valid
        assert _station_period_overlaps(
            None,
            None,
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )

    def test_station_period_overlaps_piezo(self):
        from hydromodpy.data.variables.piezometry.apis.hubeau import _station_period_overlaps

        # Same logic as hydrometry
        assert _station_period_overlaps(
            "2010-06-01",
            "2023-01-01",
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        assert not _station_period_overlaps(
            "2000-01-01",
            "2019-06-30",
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )

    def test_config_discovery_fields(self):
        from hydromodpy.data.variables.hydrometry.config import HydrometrySourceConfig

        cfg = HydrometrySourceConfig(
            source="hubeau",
            product="QmnJ",
            require_observations=False,
            fallback_search_radius_km=50.0,
        )
        assert cfg.require_observations is False
        assert cfg.fallback_search_radius_km == 50.0

    def test_config_discovery_defaults(self):
        from hydromodpy.data.variables.hydrometry.config import HydrometrySourceConfig

        cfg = HydrometrySourceConfig(source="hubeau", product="QmnJ")
        assert cfg.require_observations is True
        assert cfg.fallback_search_radius_km is None


# =========================================================================
# Feature 5: Completeness report
# =========================================================================
class TestCompletenessReport:
    def test_completeness_report_via_manager(self, sample_hydro_dir, project_period):
        from hydromodpy.data.variables.hydrometry.config import (
            HydrometryConfig,
            HydrometrySourceConfig,
        )
        from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

        cfg = HydrometryConfig(
            sources=[HydrometrySourceConfig(source="custom", path=sample_hydro_dir)]
        )
        mgr = HydrometryManager(
            config=cfg,
            catalog=None,
            project_period=project_period,
        )
        records = mgr.load()
        report = mgr.get_completeness_report(records)

        assert isinstance(report, pd.DataFrame)
        assert len(report) == 2
        assert "station_id" in report.columns
        assert "completeness_pct" in report.columns
        assert "variable" in report.columns
        assert "source" in report.columns
        # Both stations have full data (91 days)
        for _, row in report.iterrows():
            assert row["completeness_pct"] == pytest.approx(100.0)
            assert row["expected_days"] == 91
            assert row["missing_days"] == 0

    def test_completeness_with_gaps(self):
        # 30-day period, only 20 records
        dates = pd.date_range("2020-01-01", periods=20, freq="D")
        df = pd.DataFrame({"datetime": dates, "value": range(20)})
        stats = compute_completeness(
            df,
            station_id="S1",
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 30),
        )
        assert stats["expected_days"] == 30
        assert stats["actual_days"] == 20
        assert stats["missing_days"] == 10
        assert stats["completeness_pct"] == pytest.approx(66.67, rel=0.01)

    def test_completeness_constant_record(self, project_period):
        df = pd.DataFrame(
            {
                "datetime": pd.date_range(project_period[0], project_period[1], freq="D"),
                "value": 1.0,
            }
        )
        rec = PointRecord(
            station_id="C1",
            variable="discharge",
            source="custom",
            unit="m3/s",
            frequency="D",
            data=df,
            date_start=project_period[0],
            date_end=project_period[1],
            is_constant=True,
        )
        from hydromodpy.data.base_manager_variable import BaseVariableManager

        class DummyManager(BaseVariableManager):
            VARIABLE_NAME = "test"

            def _fetch_from_source(self, source_cfg):
                return []

        mgr = DummyManager(
            config=type("C", (), {"sources": []})(), catalog=None, project_period=project_period
        )
        report = mgr.get_completeness_report([rec])
        assert bool(report.iloc[0]["is_constant"]) is True
        assert report.iloc[0]["completeness_pct"] == pytest.approx(100.0)


# =========================================================================
# Feature integration: export via manager
# =========================================================================
class TestManagerExport:
    def test_export_via_manager(self, sample_hydro_dir, project_period, tmp_path):
        from hydromodpy.data.variables.hydrometry.config import (
            HydrometryConfig,
            HydrometrySourceConfig,
        )
        from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

        cfg = HydrometryConfig(
            sources=[HydrometrySourceConfig(source="custom", path=sample_hydro_dir)]
        )
        mgr = HydrometryManager(
            config=cfg,
            catalog=None,
            project_period=project_period,
        )
        records = mgr.load()
        out = tmp_path / "export"
        result = mgr.export(records, out)

        assert "metadata" in result
        assert "table_of_contents" in result
        assert (out / "hydrometry_metadata.csv").exists()
        assert (out / "hydrometry_table_of_contents.csv").exists()
