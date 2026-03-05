"""Unit tests for Modpath zone_partic runtime resolution."""

import sys
from pathlib import Path

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
        def __init__(self) -> None:
            self.verbose = True

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

    monkeypatch.setitem(
        sys.modules,
        "whitebox",
        type("_WB", (), {"WhiteboxTools": _FakeWhiteboxTools}),
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
