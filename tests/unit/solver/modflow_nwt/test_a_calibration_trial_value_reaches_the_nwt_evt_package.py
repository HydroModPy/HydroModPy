"""A calibration trial's extinction_depth reaches the built NWT EVT package.

Mirrors ``test_a_calibration_trial_value_reaches_the_soil_evt_package.py`` for
MODFLOW-NWT: ``FlowToModflowAdapter._build_etp_payload`` reads
``flow.sinks_sources['etp'].extinction_depth`` straight off the typed config a
trial just patched with ``set_by_path``, the same path
``TrialContext.fork`` rebuilds the runtime ``Flow`` from before every trial
solve.
"""

from __future__ import annotations

import types

import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter

from ._test_forcing_adapter_builders import _build_solver_mesh


def _adapter_for(etp_cfg: FlowEtpConfig) -> FlowToModflowAdapter:
    flow = types.SimpleNamespace(
        sinks_sources={"etp": etp_cfg},
        flow_regime="transient",
        active_sinks_sources=["etp"],
        config=None,
    )
    return FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(),
        nper=1,
        sink_fill=False,
    )


def _trial_etp(base: FlowEtpConfig, trial_value: float) -> FlowEtpConfig:
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "extinction_depth", trial_value)
    return trial_cfg


def test_a_trial_value_rebuilds_the_evt_depth() -> None:
    base = FlowEtpConfig(values=0.0, units="m/s", extinction_depth=1.0)

    trial_cfg = _trial_etp(base, 9.0)
    adapter = _adapter_for(trial_cfg)

    _evt_spd, _surface_offset, extinction_depth = adapter._build_etp_payload()

    assert extinction_depth == pytest.approx(9.0)


def test_two_trials_move_the_depth_each_time() -> None:
    base = FlowEtpConfig(values=0.0, units="m/s", extinction_depth=1.0)

    depths = [
        _adapter_for(_trial_etp(base, trial_value))._build_etp_payload()[2]
        for trial_value in (3.0, 15.0)
    ]

    assert depths == [pytest.approx(3.0), pytest.approx(15.0)]
