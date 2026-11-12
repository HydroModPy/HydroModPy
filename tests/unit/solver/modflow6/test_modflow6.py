"""Pre-processing checks of the ``Modflow6`` solver on a model without a time grid."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from tests._helpers.model_factory import make_model, small_geometry


def bound_model(regime):
    """A ``Modflow6`` holding a model with a mesh and a domain, and no time grid."""
    model = Modflow6(model_folder=".")
    model.inputs = make_model(
        geometry=replace(small_geometry(), domain=object()),
        time=ModelTime(grid=None, regime=regime, first_period_steady=True),
    )
    model._apply_preprocess_options(model.preprocess_options)
    return model


def test_transient_run_needs_a_time_grid():
    with pytest.raises(
        ValueError,
        match=r"preprocess_options\.time_grid derived from \[simulation\.time\] for transient flow runs",
    ):
        bound_model("transient")._validate_pre_processing_inputs()


def test_steady_run_needs_no_time_grid():
    assert bound_model("steady")._validate_pre_processing_inputs() is None
