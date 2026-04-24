"""Tests for parameter mode support and config application helpers.

Covers Phase 2 of the calibration integration:

- CalibParameter gains ``target`` / ``mode``.
- ParameterSpace.from_toml_mapping hydrates both.
- apply_parameter_to_config resolves the dotted path and applies the
  chosen mode ('replace' writes the value as-is, 'scale' multiplies the
  base value by the candidate).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from hydromodpy.calibration.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)

# ---------------------------------------------------------------------------
# Minimal Pydantic fixture that mirrors a nested config tree
# ---------------------------------------------------------------------------


class _InnerCfg(BaseModel):
    value: float = 1.0


class _MiddleCfg(BaseModel):
    homogeneous: _InnerCfg = Field(default_factory=_InnerCfg)


class _OuterCfg(BaseModel):
    K: _MiddleCfg = Field(default_factory=_MiddleCfg)
    Sy: Annotated[float, Field()] = 0.1


class TestSpaceFromTomlMappingHydratesModeAndTarget:
    def test_mode_defaults_to_replace(self):
        space = ParameterSpace.from_toml_mapping(
            {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "path": "K.homogeneous.value",
                }
            }
        )
        param = space["K"]
        assert param.mode == "replace"
        assert param.target is None
        assert param.path == "K.homogeneous.value"
        assert param.effective_path == "K.homogeneous.value"

    def test_target_wins_over_path(self):
        space = ParameterSpace.from_toml_mapping(
            {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "path": "legacy.path",
                    "target": "K.homogeneous.value",
                    "mode": "scale",
                }
            }
        )
        param = space["K"]
        assert param.target == "K.homogeneous.value"
        assert param.mode == "scale"
        assert param.effective_path == "K.homogeneous.value"

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="mode must be 'replace' or 'scale'"):
            ParameterSpace.from_toml_mapping(
                {
                    "K": {
                        "bounds": [1e-6, 1e-3],
                        "path": "K.homogeneous.value",
                        "mode": "multiply",
                    }
                }
            )


class TestApplyParameterToConfig:
    def test_replace_writes_candidate_value(self):
        cfg = _OuterCfg()
        param = CalibParameter(
            name="K",
            lower=1e-6,
            upper=1e-3,
            path="K.homogeneous.value",
            mode="replace",
        )
        apply_parameter_to_config(cfg, param, 2.5e-4)
        assert cfg.K.homogeneous.value == pytest.approx(2.5e-4)

    def test_scale_multiplies_base_value(self):
        cfg = _OuterCfg()
        cfg.K.homogeneous.value = 4.0
        param = CalibParameter(
            name="K",
            lower=0.1,
            upper=10.0,
            target="K.homogeneous.value",
            mode="scale",
        )
        apply_parameter_to_config(cfg, param, 3.0)
        assert cfg.K.homogeneous.value == pytest.approx(12.0)

    def test_replace_flat_field(self):
        cfg = _OuterCfg()
        param = CalibParameter(
            name="Sy",
            lower=0.02,
            upper=0.30,
            path="Sy",
            mode="replace",
        )
        apply_parameter_to_config(cfg, param, 0.15)
        assert cfg.Sy == pytest.approx(0.15)

    def test_rejects_invalid_path(self):
        cfg = _OuterCfg()
        param = CalibParameter(
            name="K",
            lower=0.0,
            upper=1.0,
            path="K.homogeneous.does_not_exist",
            mode="replace",
        )
        with pytest.raises(ValueError, match="not found"):
            apply_parameter_to_config(cfg, param, 0.5)

    def test_rejects_missing_path(self):
        param = CalibParameter(
            name="K",
            lower=0.0,
            upper=1.0,
            path=None,
            target=None,
            mode="replace",
        )
        with pytest.raises(ValueError, match="has no target or path"):
            apply_parameter_to_config(_OuterCfg(), param, 0.5)

    def test_scale_requires_numeric_base(self):
        class _StrCfg(BaseModel):
            label: str = "alpha"

        cfg = _StrCfg()
        param = CalibParameter(
            name="label",
            lower=0.1,
            upper=10.0,
            path="label",
            mode="scale",
        )
        with pytest.raises(ValueError, match="numeric base"):
            apply_parameter_to_config(cfg, param, 2.0)
