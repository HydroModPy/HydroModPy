"""Starting points and random draws of a search, in the transformed space of its parameters."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.sampling import search_space_center, search_space_samples


def test_log_uniform_center_is_the_geometric_mean():
    space = ParameterSpace(
        [CalibParameter(name="k", lower=1e-6, upper=1e-2, sampling="log_uniform")]
    )

    assert search_space_center(space).tolist() == pytest.approx([1e-4])


def test_normal_prior_samples_stay_within_bounds():
    space = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0, sampling="normal")])

    samples = search_space_samples(space, np.random.default_rng(7), 64)

    assert samples.shape == (64, 1)
    assert np.all(samples >= 0.0)
    assert np.all(samples <= 1.0)


def test_no_sample_asked_gives_an_empty_array():
    space = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0)])

    assert search_space_samples(space, np.random.default_rng(7), 0).shape == (0, 1)
