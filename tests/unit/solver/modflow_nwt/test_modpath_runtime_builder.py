"""Unit tests for Modpath zone_partic runtime resolution."""

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow_nwt.modpath.modpath import Modpath


def _make_modpath_stub(tmp_path: Path) -> Modpath:
    model = Modpath.__new__(Modpath)
    model.full_path = str(tmp_path)
    return model


def test_modpath_resolve_zone_partic_returns_domain_raster(
    tmp_path: Path,
) -> None:
    model = _make_modpath_stub(tmp_path)
    model._resolve_domain_raster = lambda: "domain_raster.tif"
    assert model._resolve_zone_partic("domain") == "domain_raster.tif"


def test_modpath_resolve_zone_partic_clips_seepage_raster(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _make_modpath_stub(tmp_path)
    rasters_dir = tmp_path / "_postprocess" / "_rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    seepage_tif = rasters_dir / "seepage_areas_t(0).tif"
    seepage_tif.write_text("dummy")

    watershed_shp = tmp_path / "watershed.shp"
    watershed_shp.write_text("dummy")
    model._get_watershed_shp = lambda: str(watershed_shp)

    calls: dict[str, object] = {}

    class _FakeWhiteboxTools:
        def clip_raster_to_polygon(
            self,
            in_raster: str,
            in_polygon: str,
            out_raster: str,
            maintain_dimensions: bool = True,
        ) -> None:
            calls["in_raster"] = in_raster
            calls["in_polygon"] = in_polygon
            calls["out_raster"] = out_raster
            calls["maintain_dimensions"] = maintain_dimensions
            Path(out_raster).write_text("dummy")

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_nwt.modpath.modpath.get_whitebox_backend",
        lambda: _FakeWhiteboxTools(),
    )

    resolved = model._resolve_zone_partic("seepage_clip")

    expected_clip = tmp_path / "_postprocess" / "_rasters" / "seepage_areas_t(0)_clip.tif"
    assert resolved == str(expected_clip)
    assert expected_clip.exists()
    assert calls["in_raster"] == str(seepage_tif)
    assert calls["in_polygon"] == str(watershed_shp)
    assert calls["out_raster"] == str(expected_clip)
    assert calls["maintain_dimensions"] is True


def test_modpath_resolve_zone_partic_fails_when_seepage_raster_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="missing seepage raster"):
        model = _make_modpath_stub(tmp_path)
        model._get_watershed_shp = lambda: str(tmp_path / "watershed.shp")
        model._resolve_zone_partic("seepage_clip")


def test_modpath_resolve_zone_partic_rebuilds_seepage_raster_from_npy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _make_modpath_stub(tmp_path)
    postprocess_dir = tmp_path / "_postprocess"
    rasters_dir = postprocess_dir / "_rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)

    seepage_payload = {0: np.array([[1.0, 0.0], [0.0, -9999.0]], dtype=float)}
    np.save(postprocess_dir / "seepage_areas.npy", seepage_payload)

    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    model._get_base_raster_path = lambda: str(base_raster)

    watershed_shp = tmp_path / "watershed.shp"
    watershed_shp.write_text("dummy")
    model._get_watershed_shp = lambda: str(watershed_shp)

    export_calls: dict[str, object] = {}
    clip_calls: dict[str, object] = {}

    def _fake_export_tif(base_dem_path, data_to_tif, data_tif_path, data_nodata_val=None, data_crs=None):
        export_calls["base_dem_path"] = base_dem_path
        export_calls["data_to_tif"] = np.asarray(data_to_tif, dtype=float)
        export_calls["data_tif_path"] = data_tif_path
        export_calls["data_nodata_val"] = data_nodata_val
        Path(data_tif_path).write_text("dummy")

    class _FakeWhiteboxTools:
        def clip_raster_to_polygon(
            self,
            in_raster: str,
            in_polygon: str,
            out_raster: str,
            maintain_dimensions: bool = True,
        ) -> None:
            clip_calls["in_raster"] = in_raster
            clip_calls["in_polygon"] = in_polygon
            clip_calls["out_raster"] = out_raster
            clip_calls["maintain_dimensions"] = maintain_dimensions
            Path(out_raster).write_text("dummy")

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_nwt.modpath.modpath.toolbox.export_tif",
        _fake_export_tif,
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow_nwt.modpath.modpath.get_whitebox_backend",
        lambda: _FakeWhiteboxTools(),
    )

    resolved = model._resolve_zone_partic("seepage_clip")

    seepage_tif = rasters_dir / "seepage_areas_t(0).tif"
    expected_clip = rasters_dir / "seepage_areas_t(0)_clip.tif"
    assert resolved == str(expected_clip)
    assert seepage_tif.exists()
    assert expected_clip.exists()
    assert export_calls["base_dem_path"] == str(base_raster)
    np.testing.assert_array_equal(export_calls["data_to_tif"], seepage_payload[0])
    assert export_calls["data_tif_path"] == str(seepage_tif)
    assert export_calls["data_nodata_val"] == -9999.0
    assert clip_calls["in_raster"] == str(seepage_tif)
    assert clip_calls["in_polygon"] == str(watershed_shp)
    assert clip_calls["out_raster"] == str(expected_clip)
    assert clip_calls["maintain_dimensions"] is True
