"""Tests for the discriminated-union ``CalibrationMethodConfig``.

The legacy schema accepted ``method: str + optimizer_kwargs: dict[str, Any]``
and only failed at runtime when the kwargs were foreign to the chosen
method. The discriminated union promotes those failures to validation time
and dumps a clear Pydantic error.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.optim.method_config import (
    CmaEsMethodConfig,
    GridMethodConfig,
    OptunaMethodConfig,
    validate_method_kwargs,
)


def test_grid_method_with_default_kwargs_validates() -> None:
    cfg = validate_method_kwargs("grid", {})
    assert isinstance(cfg, GridMethodConfig)
    assert cfg.method == "grid"
    assert cfg.points_per_dim is None


def test_cma_es_method_with_supported_kwargs_validates() -> None:
    cfg = validate_method_kwargs("cma_es", {"sigma0": 0.5, "popsize": 10, "restarts": 2})
    assert isinstance(cfg, CmaEsMethodConfig)
    assert cfg.sigma0 == 0.5
    assert cfg.popsize == 10
    assert cfg.restarts == 2


def test_optuna_method_with_sampler_validates() -> None:
    cfg = validate_method_kwargs("optuna", {"sampler": "tpe", "direction": "minimize"})
    assert isinstance(cfg, OptunaMethodConfig)
    assert cfg.sampler == "tpe"
    assert cfg.direction == "minimize"


def test_cma_es_method_rejects_optuna_kwarg() -> None:
    """Mixing ``method='cma_es'`` with the Optuna ``sampler`` kwarg must fail eagerly."""
    with pytest.raises(ValidationError) as excinfo:
        validate_method_kwargs("cma_es", {"sampler": "tpe"})
    assert "sampler" in str(excinfo.value).lower()
