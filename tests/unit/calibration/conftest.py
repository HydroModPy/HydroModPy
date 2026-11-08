"""Fixtures shared by the calibration tests."""

import pytest

from tests._helpers.v_valley import build_bench
from tests.unit.calibration._factories_runners import fake_pipeline, quadratic_metric  # noqa: F401


@pytest.fixture(scope="module")
def bench():
    return build_bench()


@pytest.fixture(scope="module")
def ensure_bootstrap():
    """Fill the trial pipeline before any trial is run.

    Nothing installs the pipeline as a side effect of an import, so every module
    whose trials run the real pipeline asks for this fixture. The workflow and
    the configuration are imported by the pipeline methods themselves, when a
    trial first needs them.
    """
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()
