"""WP5 - water-table extraction never leaks a HDRY/HNOFLO sentinel.

``compute_watertable_elevation`` returns the uppermost SATURATED layer head and
maps every dry (-1e30), no-flow (+1e30) or non-finite cell to NODATA. These
tests call the REAL function (and the real flopy ``get_water_table``) with no
monkeypatch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.postprocess._models import NODATA
from hydromodpy.solver.modflow6.postprocess._watertable import (
    compute_watertable_depth,
    compute_watertable_elevation,
)
from hydromodpy.solver.modflow_nwt.nwt import ModflowPostprocessOptions

from ._test_modflow6_postprocessing_builders import _build_model, _DummyBudgetFile, _workspace_dir


def test_watertable_multilayer_dry_top_descends_to_saturated() -> None:
    head = np.array([[[1e30, -1e30, 5.0]], [[3.0, 4.0, 4.5]]])
    out = compute_watertable_elevation(head)
    assert out.tolist() == [3.0, 4.0, 5.0]


def test_watertable_fully_inactive_column_maps_to_nodata() -> None:
    head = np.array([[[1e30, 1e30, 8.0]], [[1e30, -1e30, 7.0]]])
    out = compute_watertable_elevation(head)
    # Cell 1 has no saturated layer (HNOFLO over HDRY) -> NODATA.
    assert out.tolist() == [float(NODATA), float(NODATA), 8.0]
    assert np.all(np.abs(out) < 1e20)


def test_watertable_no_sentinel_leak_invariant() -> None:
    head = np.array(
        [
            [[1e30, -1e30], [5.0, 1e30]],
            [[3.0, 1e30], [1e30, -1e30]],
            [[2.0, 1e30], [1.0, 8.0]],
        ]
    )
    out = compute_watertable_elevation(head)
    assert out.shape == (4,)
    assert np.all(np.abs(out) < 1e20)
    # cell0 -> 3.0, cell1 fully inactive -> NODATA, cell2 -> 5.0, cell3 -> 8.0.
    assert out.tolist() == [3.0, float(NODATA), 5.0, 8.0]


def test_watertable_single_layer_passthrough() -> None:
    head = np.array([[[9.0, 1e30, -1e30, 2.5]]])
    out = compute_watertable_elevation(head)
    assert out.tolist() == [9.0, float(NODATA), float(NODATA), 2.5]


def test_watertable_depth_handles_nodata_elevation() -> None:
    elev = np.array([10.0, float(NODATA), 8.0])
    dem = np.array([12.0, 12.0, 12.0])
    depth = compute_watertable_depth(
        watertable_elevation=elev, dem=dem, dem_mask=np.zeros(3, dtype=bool)
    )
    assert depth[0] == 2.0
    assert depth[2] == 4.0
    # A NODATA elevation must not become a ~10011 m depth.
    assert depth[1] == float(NODATA)
    assert depth[1] != 10011.0


class _SentinelHeadFile:
    def __init__(self, path: str):
        self.path = path

    def get_times(self):
        return [1.0]

    def get_kstpkper(self):
        return [(0, 0)]

    def get_data(self, *, totim):
        del totim
        # Single layer, 2x2 grid: two sentinel cells (HNOFLO and HDRY).
        return np.array([[[9.0, 1e30], [8.0, -1e30]]], dtype=float)


def test_postprocess_flow_mesh_uses_real_water_table(monkeypatch, tmp_path) -> None:
    model = _build_model(_workspace_dir(tmp_path, "watertable_real"))
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", _SentinelHeadFile
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile", _DummyBudgetFile
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
        lambda *args, **kwargs: None,
    )

    model.post_processing(ModflowPostprocessOptions(accumulation_flux=False))

    wt = model.dict_watertable_elevation[0]
    assert np.all(np.abs(wt) < 1e20)
    flat = np.asarray(wt, dtype=float).reshape(-1)
    # Finite cells keep their head; the two sentinel cells become NODATA.
    assert flat[0] == 9.0
    assert flat[2] == 8.0
    assert flat[1] == float(NODATA)
    assert flat[3] == float(NODATA)
