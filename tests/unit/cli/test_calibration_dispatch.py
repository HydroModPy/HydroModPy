"""Tests for the [model_calibration] -> [calibration] auto-conversion."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from hydromodpy._cli.legacy_calibration import normalize_legacy_calibration_section
from hydromodpy.calibration.cli import _load_toml_calibration


def test_normalize_renames_model_calibration_to_calibration() -> None:
    raw = {"model_calibration": {"method": "optuna"}}
    with pytest.warns(DeprecationWarning, match=r"\[model_calibration\] is deprecated"):
        result = normalize_legacy_calibration_section(raw)
    assert result == {"calibration": {"method": "optuna"}}
    assert "model_calibration" not in result


def test_normalize_noop_without_legacy_section() -> None:
    raw = {"calibration": {"method": "optuna"}, "simulation": {"name": "toy"}}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = normalize_legacy_calibration_section(raw)
    assert result == {"calibration": {"method": "optuna"}, "simulation": {"name": "toy"}}


def test_normalize_keeps_explicit_calibration_when_both_present() -> None:
    raw = {
        "calibration": {"method": "optuna"},
        "model_calibration": {"method": "scipy_de"},
    }
    with pytest.warns(DeprecationWarning, match=r"both present"):
        result = normalize_legacy_calibration_section(raw)
    assert result == {"calibration": {"method": "optuna"}}
    assert "model_calibration" not in result


def test_load_toml_calibration_accepts_legacy_section(tmp_path: Path) -> None:
    toml_path = tmp_path / "legacy.toml"
    toml_path.write_text(
        "[model_calibration]\n"
        'method = "optuna"\n'
        "max_iter = 5\n"
        "\n"
        "[model_calibration.parameters.K]\n"
        "bounds = [1e-6, 1e-3]\n"
        'transform = "log"\n'
        'path = "flow.param.K.field_homogeneous.value"\n',
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match=r"\[model_calibration\] is deprecated"):
        cfg, raw = _load_toml_calibration(toml_path)

    assert cfg.method == "optuna"
    assert cfg.max_iter == 5
    assert "K" in cfg.parameters
    assert "calibration" in raw
    assert "model_calibration" not in raw
