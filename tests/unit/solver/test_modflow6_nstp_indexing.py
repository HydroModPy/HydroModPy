"""WP4 - MF6 post-processing indexes budget/transport by the real timestep.

With nstp_per_period > 1 the output has nper*nstp entries. A budget term must be
read by its true (kstp, kper) + totim, like the head; a concentration slice must
be read by its own index and paired with the seepage at the same output index.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.postprocess._models import NODATA
from hydromodpy.solver.modflow_nwt.nwt import ModflowPostprocessOptions

from ._test_modflow6_postprocessing_builders import (
    _build_model,
    _build_unstructured_model,
    _build_unstructured_transport_model,
    _workspace_dir,
)


class _MultiStepHeadFile:
    """A single stress period split into ``n`` timesteps (nstp = n)."""

    n_steps = 4

    def __init__(self, path: str):
        self.path = path

    def get_times(self):
        return [float(k + 1) for k in range(self.n_steps)]

    def get_kstpkper(self):
        return [(k, 0) for k in range(self.n_steps)]

    def get_data(self, *, totim):
        del totim
        return np.array([[[9.0, 8.5], [8.0, 7.5]]], dtype=float)


def _patch_flow_readers(monkeypatch, head_cls, budget_cls) -> None:
    # Do NOT patch get_water_table: the real function runs on clean heads.
    monkeypatch.setattr("hydromodpy.solver.modflow6.postprocess.pipeline.bf.HeadFile", head_cls)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.CellBudgetFile", budget_cls
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
        lambda *args, **kwargs: None,
    )


def test_mf6_flow_postprocess_indexes_drn_by_real_timestep_nstp_gt_1(monkeypatch, tmp_path) -> None:
    class _DrnByStep:
        def __init__(self, path: str):
            self.path = path

        def get_data(self, *, kstpkper, text, totim=None):
            del totim
            if text != "DRN":
                raise ValueError("The specified text string is not in the budget file")
            kstp = int(kstpkper[0])
            # Cell 0 (node 1) drains -(kstp+1); a real per-timestep value.
            return [np.array([[1.0, -float(kstp + 1)]], dtype=float)]

        def close(self) -> None:
            pass

    model = _build_model(_workspace_dir(tmp_path, "nstp_drn"))
    _patch_flow_readers(monkeypatch, _MultiStepHeadFile, _DrnByStep)

    model.post_processing(ModflowPostprocessOptions(accumulation_flux=False))

    for item in range(_MultiStepHeadFile.n_steps):
        assert model.dict_outflow_drain[item].reshape(-1)[0] == float(item + 1)
        assert model.dict_seepage_areas[item].reshape(-1)[0] == 1.0


def test_mf6_flow_postprocess_chd_outlet_indexed_by_timestep(monkeypatch, tmp_path) -> None:
    class _ChdByStep:
        def __init__(self, path: str):
            self.path = path

        def get_data(self, *, kstpkper, text, totim=None):
            del totim
            if text != "CHD":
                raise ValueError("The specified text string is not in the budget file")
            kstp = int(kstpkper[0])
            dtype = np.dtype([("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
            # East cell 1 (node 2) discharges 5 at step 0, 7 at step 1.
            return [np.array([(2, 0, -(5.0 + 2.0 * kstp))], dtype=dtype)]

        def close(self) -> None:
            pass

    class _TwoStepHead(_MultiStepHeadFile):
        n_steps = 2

    model = _build_model(_workspace_dir(tmp_path, "nstp_chd"))
    _patch_flow_readers(monkeypatch, _TwoStepHead, _ChdByStep)

    model.post_processing(
        ModflowPostprocessOptions(accumulation_flux=False, outlet_discharge_east_side_m3_s=True)
    )

    assert model.dict_outlet_discharge_east_side_m3_s[0].tolist() == [5.0]
    assert model.dict_outlet_discharge_east_side_m3_s[1].tolist() == [7.0]


def test_mf6_flow_postprocess_warns_on_budget_count_mismatch(monkeypatch, tmp_path) -> None:
    class _HeadThreeTimesTwoSteps:
        def __init__(self, path: str):
            self.path = path

        def get_times(self):
            return [1.0, 2.0, 3.0]

        def get_kstpkper(self):
            return [(0, 0), (1, 0)]

        def get_data(self, *, totim):
            del totim
            return np.array([[[9.0, 8.5], [8.0, 7.5]]], dtype=float)

    class _NoDrn:
        def __init__(self, path: str):
            self.path = path

        def get_data(self, *, kstpkper, text, totim=None):
            del kstpkper, text, totim
            raise ValueError("The specified text string is not in the budget file")

        def close(self) -> None:
            pass

    model = _build_model(_workspace_dir(tmp_path, "nstp_warn"))
    _patch_flow_readers(monkeypatch, _HeadThreeTimesTwoSteps, _NoDrn)

    warnings_logged: list[str] = []
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.logger.warning",
        lambda msg, *args: warnings_logged.append(str(msg) % args if args else str(msg)),
    )

    model.post_processing(ModflowPostprocessOptions(accumulation_flux=False))

    assert any("(kstp,kper) entries" in message for message in warnings_logged)
    # Pairs by the shorter length (2): no crash, two output indices processed.
    assert set(model.dict_outflow_drain) == {0, 1}


class _TwoSliceUcn:
    def __init__(self, path: str, data: np.ndarray):
        self.path = path
        self._data = data

    def get_alldata(self, *, mflay=None):
        del mflay
        return self._data

    def get_times(self):
        return [1.0, 2.0]


def _run_transport(monkeypatch, tmp_path, name, ucn_data, outflow_drain, **kwargs):
    flow_model = _build_unstructured_model(_workspace_dir(tmp_path, name))
    flow_model.last_postprocess_options = ModflowPostprocessOptions(
        accumulation_flux=False,
        native_mesh_npz=False,
        native_mesh_csv=False,
        native_mesh_vtu=False,
        native_mesh_png=False,
    )
    flow_model.dict_outflow_drain = outflow_drain
    transport_model = _build_unstructured_transport_model(flow_model)
    (Path(flow_model.full_path) / "_postprocess").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.bf.UcnFile",
        lambda path: _TwoSliceUcn(path, ucn_data),
    )
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.postprocess.pipeline.raster_io.export_tif",
        lambda *args, **kwargs: None,
    )
    transport_model.post_processing(transport_model, **kwargs)
    return transport_model


def test_mf6_transport_postprocess_reads_each_concentration_slice(monkeypatch, tmp_path) -> None:
    ucn = np.array([[[0.2, 0.4]], [[0.6, 0.8]]], dtype=float)
    transport_model = _run_transport(
        monkeypatch,
        tmp_path,
        "transport_slices",
        ucn,
        {0: np.array([1.0, 1.0]), 1: np.array([1.0, 1.0])},
        concentration_seepage=True,
        mass_seepage=False,
        mass_accumulated=False,
    )
    saved = np.load(
        Path(transport_model.save_file) / "concentration_seepage.npy", allow_pickle=True
    ).item()
    np.testing.assert_allclose(saved[0], [0.2, 0.4])
    np.testing.assert_allclose(saved[1], [0.6, 0.8])  # not a repeat of slice 0


def test_mf6_transport_pairs_concentration_with_same_index_seepage(monkeypatch, tmp_path) -> None:
    ucn = np.array([[[0.5, 0.5]], [[0.5, 0.5]]], dtype=float)
    transport_model = _run_transport(
        monkeypatch,
        tmp_path,
        "transport_pairing",
        ucn,
        {0: np.array([2.0, 0.0]), 1: np.array([0.0, 3.0])},
        concentration_seepage=False,
        mass_seepage=True,
        mass_accumulated=False,
    )
    saved = np.load(Path(transport_model.save_file) / "mass_seepage.npy", allow_pickle=True).item()
    np.testing.assert_allclose(saved[0], [1.0, float(NODATA)])
    np.testing.assert_allclose(saved[1], [float(NODATA), 1.5])
