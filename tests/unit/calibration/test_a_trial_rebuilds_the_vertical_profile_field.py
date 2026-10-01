"""A trial rebuilds the runtime field with its own characteristic_depth.

A trial writes the typed config through ``set_by_path``, the same way
``TrialContext.fork`` does (``hydromodpy/calibration/runners/trial.py``: a
fresh ``model_copy(deep=True)`` of the base config, then one ``set_by_path``
per sampled parameter). The runtime ``FieldParam`` the solver actually reads
is then rebuilt from that typed config through ``FlowParam.resolved_payload``
and the registered ``FieldParamLike`` factory, exactly as
``ProcessSpatial.set_parameters_from_config`` does when a trial resets
``flow = None`` and the next pipeline step rebuilds it. Each trial forks a
deep copy, so concurrent trials (``TrialSandbox`` runs them in parallel) never
share the mutable ``FieldVerticalProfileSection`` instance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.physics.flow.flow_param_config import FlowParam
from hydromodpy.spatial.field.core.field_param import FieldParam


def _base_flow_param() -> FlowParam:
    return FlowParam.model_validate(
        {
            "field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-4},
            "field_vertical_profile": {"mode": "exponential", "characteristic_depth": 10.0},
        }
    )


def _rebuild_for_trial(base: FlowParam, trial_value: float) -> FieldParam:
    """Fork the way a trial does, then rebuild the runtime field from it."""
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "field_vertical_profile.characteristic_depth", trial_value)
    payload = trial_cfg.resolved_payload(param_id="K")
    return FieldParam.from_dict(payload)


def test_a_trial_value_rebuilds_the_field_without_touching_the_base() -> None:
    base = _base_flow_param()

    field = _rebuild_for_trial(base, 75.0)

    assert field.vertical_profile["characteristic_depth"] == pytest.approx(75.0)
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)


def test_two_trials_move_the_depth_each_time() -> None:
    base = _base_flow_param()

    depths = [
        _rebuild_for_trial(base, trial_value).vertical_profile["characteristic_depth"]
        for trial_value in (5.0, 40.0)
    ]

    assert depths == [pytest.approx(5.0), pytest.approx(40.0)]


def test_parallel_trials_do_not_cross_contaminate() -> None:
    base = _base_flow_param()
    trial_values = [5.0, 15.0, 30.0, 60.0, 120.0] * 4

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda value: _rebuild_for_trial(base, value).vertical_profile[
                    "characteristic_depth"
                ],
                trial_values,
            )
        )

    assert results == pytest.approx(trial_values)
    # The base trial context a concurrent fork started from is never mutated.
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)
