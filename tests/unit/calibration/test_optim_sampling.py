"""Tests of `optim.sampling`."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.sampling import (
    physical_sample,
    search_space_center,
    search_space_samples,
)

# From test_sampling.py
# Tests for the sampling helpers of the optimizers.


def test_log_uniform_center_uses_geometric_mean() -> None:
    space = ParameterSpace(
        [CalibParameter(name="k", lower=1e-6, upper=1e-2, sampling="log_uniform")]
    )
    center = search_space_center(space)
    assert center.tolist() == pytest.approx([1e-4])


def test_normal_prior_samples_stay_within_transformed_bounds() -> None:
    space = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0, sampling="normal")])
    samples = search_space_samples(space, np.random.default_rng(7), 64)
    assert samples.shape == (64, 1)
    assert np.all(samples >= 0.0)
    assert np.all(samples <= 1.0)


def test_no_sample_asked_gives_an_empty_array() -> None:
    space = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0)])

    assert search_space_samples(space, np.random.default_rng(7), 0).shape == (0, 1)


def test_physical_sample_returns_physical_value() -> None:
    param = CalibParameter(name="k", lower=1e-6, upper=1e-2, search_space="log")
    value = physical_sample(param, np.random.default_rng(3))
    assert 1e-6 <= value <= 1e-2
