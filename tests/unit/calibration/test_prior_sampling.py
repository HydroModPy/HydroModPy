"""Tests for optimizer prior sampling helpers."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.adapters._prior_sampling import (
    physical_prior_sample,
    transformed_prior_center,
    transformed_prior_samples,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def test_log_uniform_center_uses_geometric_mean() -> None:
    space = ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-2, prior="log_uniform")])
    center = transformed_prior_center(space)
    assert center.tolist() == pytest.approx([1e-4])


def test_normal_prior_samples_stay_within_transformed_bounds() -> None:
    space = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0, prior="normal")])
    samples = transformed_prior_samples(space, np.random.default_rng(7), 64)
    assert samples.shape == (64, 1)
    assert np.all(samples >= 0.0)
    assert np.all(samples <= 1.0)


def test_physical_prior_sample_returns_physical_value() -> None:
    param = CalibParameter(name="k", lower=1e-6, upper=1e-2, transform="log")
    value = physical_prior_sample(param, np.random.default_rng(3))
    assert 1e-6 <= value <= 1e-2
