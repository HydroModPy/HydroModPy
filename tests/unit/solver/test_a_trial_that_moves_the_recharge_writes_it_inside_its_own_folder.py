"""A trial that samples the recharge writes it into its own folder, not the shared one.

The calibration-wide ``_shared_recharge`` dir assumes the recharge is invariant
across trials. A phase that samples a recharge parameter breaks that
assumption, so its trials mark themselves with
``PRIVATE_TRIAL_RECHARGE_KEY`` and each gets its own ``<trial>/_recharge``
folder instead, wherever the model that asks for it sits (leaf, nested, or the
``_ssic`` steady-state auxiliary model).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from hydromodpy.solver.modflow6.build import _shared_recharge_dir
from hydromodpy.solver.modflow6.builders.recharge import (
    PRIVATE_TRIAL_RECHARGE_KEY,
    TRIAL_RECHARGE_DIRNAME,
)

_SCRATCH = os.path.join(os.sep, "p", ".hmp", "scratch")
_TRIAL = os.path.join(_SCRATCH, "run_trial000016")
_OVERRIDES = {PRIVATE_TRIAL_RECHARGE_KEY: True}


def test_a_leaf_model_writes_into_its_own_trial_recharge_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_a_nested_model_still_finds_its_trial_folder() -> None:
    nested = os.path.join(_TRIAL, "cheze_cal_377f4b")
    model = SimpleNamespace(full_path=nested, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_the_ssic_auxiliary_model_shares_its_parent_trials_folder() -> None:
    ssic = os.path.join(_TRIAL, "cheze_cal_377f4b", "_ssic", "ssic")
    model = SimpleNamespace(full_path=ssic, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_without_the_key_a_trial_keeps_using_the_shared_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL, _flow_runtime_overrides={})
    assert _shared_recharge_dir(model) == os.path.join(_SCRATCH, "_shared_recharge")


def test_a_trial_with_no_overrides_at_all_keeps_using_the_shared_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL)
    assert _shared_recharge_dir(model) == os.path.join(_SCRATCH, "_shared_recharge")


def test_outside_a_trial_there_is_no_recharge_folder_at_all() -> None:
    model = SimpleNamespace(
        full_path=os.path.join(_SCRATCH, "plain_run"), _flow_runtime_overrides=_OVERRIDES
    )
    assert _shared_recharge_dir(model) is None
