"""Every declared ``[flow]`` key must survive the TOML loader.

The loader used to rebuild the validation payload from a hand-written key
list, so a field added to :class:`FlowConfig` was accepted by the unknown-key
guard and then silently dropped (``restart_from`` was the regression). These
tests pin the model itself as the source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.physics.flow import flow_toml_loader
from hydromodpy.physics.flow.flow_config import FlowConfig

# One non-default value per scalar field, used to prove the value reaches the
# model instead of being replaced by the field default.
_SCALAR_PROBES: dict[str, Any] = {
    "flow_regime": "steady",
    "first_period_steady": False,
    "restart_from": "prior_run/fields.zarr",
    "runtime_backend": "petsc",
    "surface_interaction_model": "complementarity",
    "runtime_max_iterations": 77,
    "runtime_tol_residual_inf": 1e-7,
    "runtime_tol_state_update_inf": 1e-9,
    "vi_substeps_per_period": 3,
    "vi_substep_on_failure": True,
    "vi_max_adaptive_substeps": 5,
    "ts_vi_steps_per_period": 6,
    "ts_vi_adapt": True,
    "ts_vi_dt_min_fraction": 1.0 / 32.0,
    "ts_vi_dt_max_fraction": 1.0 / 2.0,
    "ts_vi_type": "cn",
    "ts_vi_snes_type": "vinewtonssls",
}


def _build(section: dict[str, Any]) -> FlowConfig:
    return FlowConfig.from_toml_section(section, base_dir=Path("."))


def test_restart_from_declared_in_toml_reaches_the_config() -> None:
    cfg = _build({"restart_from": "runs/spinup/fields.zarr"})
    assert cfg.restart_from == "runs/spinup/fields.zarr"


def test_every_scalar_field_has_a_probe() -> None:
    """The probe table must cover all non-preparsed model fields."""
    expected = set(FlowConfig.model_fields) - set(flow_toml_loader._PREPARSED_KEYS)
    assert set(_SCALAR_PROBES) == expected


@pytest.mark.parametrize(("key", "value"), sorted(_SCALAR_PROBES.items()))
def test_scalar_field_is_forwarded(key: str, value: Any) -> None:
    cfg = _build({key: value})
    assert getattr(cfg, key) == value


def test_preparsed_keys_are_known_to_the_model() -> None:
    unknown = set(flow_toml_loader._PREPARSED_KEYS) - set(FlowConfig.model_fields)
    assert unknown == {"param_values"}


def test_absent_keys_keep_the_model_defaults() -> None:
    cfg = _build({})
    for key in _SCALAR_PROBES:
        assert getattr(cfg, key) == FlowConfig.model_fields[key].default
