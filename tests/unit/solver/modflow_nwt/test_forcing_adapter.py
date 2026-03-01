from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.solver.modflow_nwt.forcing_to_modflow_adapter import (
    ForcingToModflowAdapter,
)


def test_forcing_adapter_builds_evt_and_clips_negative_recharge():
    recharge = pd.Series([0.1, -0.2, 0.3], dtype=float)
    adapter = ForcingToModflowAdapter(
        recharge=recharge,
        nper=3,
        flow_regime="transient",
        first_clim="mean",
    )

    out = adapter.build()

    assert out.evt_spd is not None
    assert out.evt_spd[0] == 0
    assert out.evt_spd[1] == pytest.approx(0.2)
    assert out.evt_spd[2] == pytest.approx(0.0)

    assert isinstance(out.rch_data, dict)
    assert out.rch_data[0] == pytest.approx(np.mean([0.1, 0.0, 0.3]))
    assert out.rch_data[1] == pytest.approx(0.0)
    assert out.rch_data[2] == pytest.approx(0.3)


def test_forcing_adapter_returns_steady_scalar_for_mapping_recharge():
    adapter = ForcingToModflowAdapter(
        recharge={0: 0.2, 1: 0.4},
        nper=2,
        flow_regime="steady",
        first_clim="mean",
    )
    out = adapter.build()

    assert out.evt_spd is None
    assert out.rch_data == pytest.approx(0.3)


def test_forcing_adapter_rejects_invalid_flow_regime():
    adapter = ForcingToModflowAdapter(
        recharge=0.001,
        nper=1,
        flow_regime="invalid",
        first_clim="mean",
    )
    with pytest.raises(ValueError, match="flow_regime must be 'steady' or 'transient'"):
        adapter.build()
