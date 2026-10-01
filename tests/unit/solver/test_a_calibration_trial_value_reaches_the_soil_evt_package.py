"""A calibration trial's extinction_depth reaches the built soil EVT package.

``extinction_depth`` is now declared ``Calibrable`` on ``FlowEtpConfig``
(``hydromodpy/physics/flow/sinks_sources/etp.py``). A trial writes it the same
way any other replace-mode parameter is written, through
``hydromodpy.calibration.optim.parameters.set_by_path``, on the typed config a
``TrialContext.fork`` rebuilds the runtime ``Flow`` from before every trial
solve. ``bind_soil_etp_from_flow`` then reads it straight off that config, so
no solve is needed to prove the wiring: only the MODFLOW 6 soil-mode builder
that turns it into the EVTA payload.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.solver.modflow6.builders.recharge import (
    bind_soil_etp_from_flow,
    build_soil_evta_payload,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NCPL = 4


def _mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    botm = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(nrow=2, ncol=2, top=top, botm=np.stack([botm]))


def _soil_mode_model(etp_cfg: FlowEtpConfig) -> SimpleNamespace:
    """Bind ``etp_cfg`` the way MODFLOW 6 soil mode does, with the real binder."""
    model = SimpleNamespace(
        flow=SimpleNamespace(active_sinks_sources=["etp"], sinks_sources={"etp": etp_cfg}),
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
    )
    bind_soil_etp_from_flow(model)
    # ``resolve_deferred_soil_etp`` discretizes the heterogeneous source onto
    # the grid; out of scope here (exercised by the soil EVT rate tests), so
    # the rate is set directly, the way those tests also do.
    model._soil_etp_rate = {0: np.full(_NCPL, 1.0e-8)}
    return model


def _trial_etp(base: FlowEtpConfig, trial_value: float) -> FlowEtpConfig:
    """Copy ``base`` and write ``extinction_depth`` the way a trial does."""
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "extinction_depth", trial_value)
    return trial_cfg


def _base_etp() -> FlowEtpConfig:
    cfg = FlowEtpConfig(extinction_depth=1.0, heterogeneous_source=object())
    cfg._from_soil_reservoir = True
    return cfg


def test_a_trial_value_rebuilds_the_evt_depth() -> None:
    trial_cfg = _trial_etp(_base_etp(), 7.5)

    model = _soil_mode_model(trial_cfg)
    payload = build_soil_evta_payload(
        model,
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    _rate_payload, _surface, depth = payload
    assert depth == pytest.approx(7.5)


def test_two_trials_move_the_depth_each_time() -> None:
    """The builder is not caching the first trial's depth."""
    base = _base_etp()
    depths = []
    for trial_value in (2.0, 12.0):
        model = _soil_mode_model(_trial_etp(base, trial_value))
        _rate, _surface, depth = build_soil_evta_payload(
            model,
            _mesh(),
            ocean_support_mask=np.zeros(_NCPL, dtype=bool),
            stream_support_mask=np.zeros(_NCPL, dtype=bool),
            lake_cell_ids=[],
            drain_active=False,
            shared_dir=None,
        )
        depths.append(depth)

    assert depths == [pytest.approx(2.0), pytest.approx(12.0)]
