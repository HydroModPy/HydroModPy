from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6 import Modflow6


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def test_modflow6_requires_canonical_time_grid_for_launcher_flow_preprocessing():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=".")
    model.flow = SimpleNamespace(config=SimpleNamespace(flow_regime="transient"))
    model.domain = object()
    model._apply_preprocess_options(model.preprocess_options)

    with pytest.raises(
        ValueError,
        match=r"preprocess_options\.time_grid derived from \[simulation\.time\].*fallback is no longer supported",
    ):
        model._validate_pre_processing_inputs()
