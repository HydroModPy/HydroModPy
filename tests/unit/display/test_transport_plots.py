from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from hydromodpy.analysis.display.transport_plots import (
    _load_concentration_cube,
    _load_outflow_drain_array,
    _resolve_ucn_path,
)


def test_resolve_ucn_path_falls_back_to_solver_output_name() -> None:
    target = Path("run_dir") / "demo_mt.ucn"
    model_transport = SimpleNamespace(
        full_path=Path("run_dir"),
        model_name_mt="demo_mt",
    )

    with patch("pathlib.Path.exists", lambda self: self == target):
        assert _resolve_ucn_path(model_transport) == target


def test_resolve_ucn_path_falls_back_to_mt3d_default_output() -> None:
    target = Path("run_dir") / "MT3D001.UCN"
    model_transport = SimpleNamespace(
        full_path=Path("run_dir"),
        model_name_mt="demo_mt",
    )

    with patch("pathlib.Path.exists", lambda self: self == target):
        assert _resolve_ucn_path(model_transport) == target


def test_load_concentration_cube_falls_back_to_headfile_reader() -> None:
    captured: dict[str, object] = {}

    class _FailingUcnFile:
        def __init__(self, path) -> None:
            captured["ucn_path"] = path
            raise OSError("UcnFile cannot read this concentration output")

    class _FakeHeadFile:
        def __init__(self, path, text=None, precision=None) -> None:
            captured["head_path"] = path
            captured["head_text"] = text
            captured["head_precision"] = precision

        def get_alldata(self, mflay=None):
            captured["head_mflay"] = mflay
            return np.array([[[[1e30, 2.0]]]], dtype=float)

    model_transport = SimpleNamespace(path_file="demo_mt.ucn")

    with patch("flopy.utils.binaryfile.UcnFile", _FailingUcnFile):
        with patch("flopy.utils.binaryfile.HeadFile", _FakeHeadFile):
            concentration = _load_concentration_cube(model_transport)

    assert captured["ucn_path"] == Path("demo_mt.ucn")
    assert captured["head_path"] == Path("demo_mt.ucn")
    assert captured["head_text"] == "CONCENTRATION"
    assert captured["head_precision"] == "double"
    assert captured["head_mflay"] is None
    assert np.isnan(concentration[0, 0, 0, 0])
    assert concentration[0, 0, 0, 1] == 2.0


def test_load_outflow_drain_array_falls_back_to_npy_series() -> None:
    model_modflow = SimpleNamespace(full_path=Path("run_dir"), nrow=2, ncol=2)
    series_path = Path("run_dir") / "_postprocess" / "outflow_drain.npy"

    class _FakeNpy:
        def item(self):
            return {1: np.array([[1.0, 0.0], [2.0, 3.0]], dtype=float)}

    with patch("pathlib.Path.exists", lambda self: self == series_path):
        with patch("numpy.load", lambda path, allow_pickle=True: _FakeNpy()):
            seep = _load_outflow_drain_array(
                model_modflow,
                1,
                fallback_shape=(2, 2),
            )

    np.testing.assert_array_equal(seep, np.array([[1.0, 0.0], [2.0, 3.0]], dtype=float))
