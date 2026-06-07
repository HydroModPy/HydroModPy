from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.modflow_nwt.mt3dms.mt3dms import Mt3dms


def _write_raster(path: Path, data: np.ndarray, *, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": int(data.shape[0]),
        "width": int(data.shape[1]),
        "count": 1,
        "dtype": data.dtype,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, float(data.shape[0]), 1.0, 1.0),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


class _FakeUcnFile:
    def __init__(self, _path: str) -> None:
        pass

    def get_alldata(self, mflay=None):
        _ = mflay
        return np.array(
            [
                [[[0.0, 0.0], [0.0, 0.0]]],
                [[[2.0, 3.0], [4.0, 5.0]]],
            ],
            dtype=np.float32,
        )


def test_mt3dms_processing_accepts_program_completed_normal_message(tmp_path: Path) -> None:
    model = Mt3dms.__new__(Mt3dms)
    model.full_path = str(tmp_path)
    model.model_name_mt = "demo_mt"
    Path(model.full_path).mkdir(parents=True, exist_ok=True)
    (Path(model.full_path) / "MT3D001.UCN").write_bytes(b"ucn")

    captured: dict[str, object] = {}

    class _FakeMt:
        def write_input(self) -> None:
            captured["write_input"] = True

        def run_model(self, **kwargs):
            captured["run_model_kwargs"] = kwargs
            return True, ["Program completed.   Total CPU time:  000 minutes  0.672 seconds"]

    model.mt = _FakeMt()

    success = model.processing(write_model=True, run_model=True, verbose=True)

    assert success is True
    assert captured["write_input"] is True
    assert captured["run_model_kwargs"] == {
        "silent": False,
        "pause": False,
        "normal_msg": ["normal termination", "program completed"],
    }
    assert (Path(model.full_path) / "demo_mt.UCN").exists()


def test_mt3dms_post_processing_exports_mass_accumulated(monkeypatch, tmp_path: Path) -> None:
    model = Mt3dms.__new__(Mt3dms)
    model.model_folder = str(tmp_path / "results")
    model.model_name = "demo"
    model.model_name_mt = "demo_mt"
    model.full_path = os.path.join(model.model_folder, model.model_name)
    Path(model.full_path).mkdir(parents=True, exist_ok=True)

    dem_path = tmp_path / "base_dem.tif"
    _write_raster(dem_path, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32))

    routing_ctx = SimpleNamespace(
        correc_path=str(tmp_path / "routing_fill.tif"),
        direc_path=str(tmp_path / "routing_direc.tif"),
    )
    _write_raster(
        Path(routing_ctx.correc_path), np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    )
    _write_raster(
        Path(routing_ctx.direc_path),
        np.array([[1, 1], [1, 1]], dtype=np.int16),
        nodata=-32768,
    )

    outflow_drain = {0: np.array([[1.0, 0.0], [2.0, 3.0]], dtype=np.float32)}
    model.model_modflow = SimpleNamespace(
        inactive_mask=np.array([[False, False], [False, False]], dtype=bool),
        dem_watershed_path=str(dem_path),
        nper=1,
        _ensure_solver_routing_context=lambda: routing_ctx,
        dict_outflow_drain=outflow_drain,
    )
    model.geographic = SimpleNamespace()

    save_file = Path(model.full_path) / "_postprocess"

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_nwt.mt3dms.mt3dms.bf.UcnFile",
        _FakeUcnFile,
    )

    captured: list[dict[str, object]] = []

    class _FakeMasstransfer:
        def __init__(
            self,
            geographic,
            raw_rast_name,
            trace_shp_name,
            mass_rast_name,
            extraction_folder=None,
            label="conc",
            routing_fill_path=None,
            routing_direc_path=None,
            backend=None,
        ) -> None:
            captured.append(
                {
                    "geographic": geographic,
                    "raw_rast_name": raw_rast_name,
                    "trace_shp_name": trace_shp_name,
                    "mass_rast_name": mass_rast_name,
                    "extraction_folder": extraction_folder,
                    "label": label,
                    "routing_fill_path": routing_fill_path,
                    "routing_direc_path": routing_direc_path,
                    "backend": backend,
                }
            )
            self._output = Path(extraction_folder) / "_rasters" / mass_rast_name

        def trace_cumulated(self) -> None:
            _write_raster(self._output, np.array([[9.0, 8.0], [7.0, 6.0]], dtype=np.float32))

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_nwt.mt3dms.mt3dms.masstransfer.Masstransfer",
        _FakeMasstransfer,
    )

    model.post_processing(
        model_mt3dms=model,
        concentration_seepage=True,
        mass_seepage=True,
        mass_accumulated=True,
        export_all_tif=True,
    )

    assert len(captured) == 1
    call = captured[0]
    assert call["geographic"] is model.geographic
    assert call["raw_rast_name"] == "mass_seepage_t(1).tif"
    assert call["trace_shp_name"] == "tracept_conc_t(1).shp"
    assert call["mass_rast_name"] == "mass_accumulated_t(1).tif"
    assert call["extraction_folder"] == str(save_file)
    assert call["routing_fill_path"] == routing_ctx.correc_path
    assert call["routing_direc_path"] == routing_ctx.direc_path

    mass_acc_path = save_file / "_rasters" / "mass_accumulated_t(1).tif"
    assert mass_acc_path.exists()
    with rasterio.open(mass_acc_path) as src:
        np.testing.assert_array_equal(
            src.read(1), np.array([[9.0, 8.0], [7.0, 6.0]], dtype=np.float32)
        )

    assert 0 in model.dict_mass_accumulated
    np.testing.assert_array_equal(
        model.dict_mass_accumulated[0], np.array([[9.0, 8.0], [7.0, 6.0]], dtype=np.float32)
    )
