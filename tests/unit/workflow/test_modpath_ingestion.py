"""Unit tests for ``workflow.steps.extract``: the seepage raster rebuilt from a run store."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.workflow.steps import extract
from tests._helpers.run_stores import open_run_store


class _FakeRasterSrc:
    height = 2
    width = 2

    def __enter__(self) -> _FakeRasterSrc:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def test_restore_seepage_raster_writes_tif(tmp_path: Path, monkeypatch) -> None:
    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    seepage_tif = tmp_path / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    array = np.array([[1.0, 0.0], [0.0, -9999.0]], dtype=float)

    with open_run_store(tmp_path / "project", n_cells=4) as store:
        store.write_field(store.sim_id, "seepage_mask", 0, array.ravel(), n_timesteps=1)
        run_dir = store.run_dir
    monkeypatch.setattr(extract.rasterio, "open", lambda *_a, **_kw: _FakeRasterSrc())

    captured: dict[str, object] = {}

    def _fake_export_tif(base_dem_path, data, dst_path, nodata):
        captured["base"] = base_dem_path
        captured["data"] = np.asarray(data, dtype=float)
        captured["dst"] = dst_path
        captured["nodata"] = nodata
        Path(dst_path).write_text("dummy")

    monkeypatch.setattr(extract, "export_tif", _fake_export_tif)

    ok = extract.restore_seepage_raster_from_store(run_dir, base_raster, seepage_tif)

    assert ok is True
    assert seepage_tif.is_file()
    assert captured["base"] == str(base_raster)
    np.testing.assert_array_equal(captured["data"], array)
    assert captured["dst"] == str(seepage_tif)
    assert captured["nodata"] == -9999.0


def test_restore_seepage_raster_returns_false_when_base_missing(tmp_path: Path) -> None:
    base_raster = tmp_path / "missing.tif"
    seepage_tif = tmp_path / "out.tif"
    assert extract.restore_seepage_raster_from_store(tmp_path, base_raster, seepage_tif) is False


def test_restore_seepage_raster_returns_false_when_the_run_has_no_field(tmp_path: Path) -> None:
    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    seepage_tif = tmp_path / "out.tif"
    with open_run_store(tmp_path / "project", n_cells=4) as store:
        run_dir = store.run_dir

    assert extract.restore_seepage_raster_from_store(run_dir, base_raster, seepage_tif) is False
