"""Fixtures shared by the calibration tests."""

import pytest

import hydromodpy
from tests._helpers.v_valley import build_bench
from tests.unit.calibration._factories_runners import fake_pipeline, quadratic_metric  # noqa: F401


@pytest.fixture(scope="module")
def bench():
    return build_bench()


@pytest.fixture(scope="module")
def ensure_bootstrap():
    """Wire the deferred providers before any trial is run."""
    hydromodpy.bootstrap()
