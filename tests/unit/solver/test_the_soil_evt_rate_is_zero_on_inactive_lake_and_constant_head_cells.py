"""The soil EVTA rate is zeroed exactly where LAK or a CHD already own the flux.

An inactive (fixed-area) lake cell gets its open-water evaporation from LAK;
an ocean or stream CHD cell never receives MF6 ET at all (``ibound < 0``). Both
must read 0 in the EVTA rate array, and every other cell keeps the soil's
discretized deficit.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders.recharge import build_soil_evta_payload
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NROW, _NCOL = 2, 3
_NCPL = _NROW * _NCOL


def _mesh() -> SolverMesh:
    top = np.full((_NROW, _NCOL), 10.0)
    botm = np.full((_NROW, _NCOL), 0.0)
    return SolverMesh.from_structured_arrays(nrow=_NROW, ncol=_NCOL, top=top, botm=np.stack([botm]))


def _model() -> SimpleNamespace:
    return SimpleNamespace(
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
        _soil_etp_rate={0: np.full(_NCPL, 2.0e-8)},
        _soil_evt_surface_offset_m=0.0,
        _soil_evt_extinction_depth_m=1.0,
    )


def test_lake_ocean_and_stream_cells_draw_no_evta() -> None:
    ocean_mask = np.zeros(_NCPL, dtype=bool)
    ocean_mask[0] = True
    stream_mask = np.zeros(_NCPL, dtype=bool)
    stream_mask[3] = True
    lake_cell_ids = [5]

    payload = build_soil_evta_payload(
        _model(),
        _mesh(),
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=lake_cell_ids,
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    rate, _, _ = payload
    rate0 = rate[0]
    assert rate0[0] == 0.0
    assert rate0[3] == 0.0
    assert rate0[5] == 0.0
    np.testing.assert_allclose(rate0[[1, 2, 4]], 2.0e-8)


def test_without_any_excluded_cell_every_cell_keeps_the_soil_rate() -> None:
    payload = build_soil_evta_payload(
        _model(),
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    rate, _, _ = payload
    np.testing.assert_allclose(rate[0], np.full(_NCPL, 2.0e-8))


def test_without_a_soil_etp_rate_the_payload_is_none() -> None:
    model = _model()
    model._soil_etp_rate = None

    payload = build_soil_evta_payload(
        model,
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is None
