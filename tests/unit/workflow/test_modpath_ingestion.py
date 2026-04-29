"""Unit tests for ``workflow.steps.extract``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.workflow.steps import extract


class _FakeStore:
    def __init__(self, sims: pd.DataFrame, array: np.ndarray) -> None:
        self._sims = sims
        self._array = array

    def list_simulations(self) -> pd.DataFrame:
        return self._sims

    def query_field(self, sim_id: str, name: str, timestep: int) -> np.ndarray:
        return self._array.ravel()

    def close(self) -> None:
        pass


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

    fake_store = _FakeStore(pd.DataFrame([{"sim_id": "abc"}]), array)
    monkeypatch.setattr(
        extract,
        "SimulationCatalog",
        lambda *_a, **_kw: fake_store,
    )
    monkeypatch.setattr(
        extract,
        "locate_workspace_root",
        lambda _root: tmp_path,
    )
    monkeypatch.setattr(
        extract.rasterio,
        "open",
        lambda *_a, **_kw: _FakeRasterSrc(),
    )

    captured: dict[str, object] = {}

    def _fake_export_tif(base_dem_path, data, dst_path, nodata):
        captured["base"] = base_dem_path
        captured["data"] = np.asarray(data, dtype=float)
        captured["dst"] = dst_path
        captured["nodata"] = nodata
        Path(dst_path).write_text("dummy")

    monkeypatch.setattr(extract, "export_tif", _fake_export_tif)

    ok = extract.restore_seepage_raster_from_store(tmp_path, base_raster, seepage_tif)

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


def test_restore_seepage_raster_returns_false_when_catalog_empty(
    tmp_path: Path, monkeypatch
) -> None:
    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    seepage_tif = tmp_path / "out.tif"

    fake_store = _FakeStore(pd.DataFrame(columns=["sim_id"]), np.array([]))
    monkeypatch.setattr(
        extract,
        "SimulationCatalog",
        lambda *_a, **_kw: fake_store,
    )
    monkeypatch.setattr(
        extract,
        "locate_workspace_root",
        lambda _root: tmp_path,
    )

    ok = extract.restore_seepage_raster_from_store(tmp_path, base_raster, seepage_tif)

    assert ok is False
