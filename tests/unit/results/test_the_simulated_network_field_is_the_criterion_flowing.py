"""The simulated_active_network field is the network the criterion counts as flowing.

The run is the monthly V-valley of :mod:`tests.unit.results._transient_network_run`:
in January (step 0) the whole axis flows, in June (step 5) the outlet alone at
two litres per second. The field is 1 on the flowing cells and 0 elsewhere,
cut with the run's sealed settings, the defaults when it sealed none.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    field_descriptor,
    simulated_active_network_stack,
)
from tests.unit.results._transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    OUTLET,
    transient_run,
)


def test_each_step_holds_the_cells_flowing_at_that_step() -> None:
    stack = simulated_active_network_stack(transient_run(), [0, 5])

    assert stack.shape[0] == 2
    assert set(np.unique(stack)) <= {0.0, 1.0}
    january, june = stack
    assert january[[OUTLET, MIDDLE, HEAD]].tolist() == [1.0, 1.0, 1.0]
    assert june[[OUTLET, MIDDLE, HEAD]].tolist() == [1.0, 0.0, 0.0]
    assert january[HILLSLOPE] == 0.0


def test_the_sealed_visible_flow_cuts_the_summer_outlet() -> None:
    """At 5 L/s the two-litre summer outlet no longer flows."""
    run = transient_run()
    run.config_snapshot = {
        "calibration": {
            "outputs": {
                "streams": {
                    "support": "network",
                    "observed_network": "data.hydrography",
                    "tau_specific_ratio": 1.0e-4,
                    "extent": {"visible_flow": "5 L/s"},
                }
            }
        }
    }
    (june,) = simulated_active_network_stack(run, [5])
    assert june[OUTLET] == 0.0


def test_a_run_without_a_release_flux_is_refused_by_name() -> None:
    run = transient_run()
    run.has_field = lambda variable, **_: variable == "topography"
    with pytest.raises(ValueError, match="no per-cell release_flux"):
        simulated_active_network_stack(run, [0])


def test_the_field_describes_itself_as_a_mask() -> None:
    descriptor = field_descriptor(SIMULATED_ACTIVE_NETWORK)
    assert descriptor.units == "1"
    assert descriptor.shape == "time_face"
    assert (descriptor.valid_min, descriptor.valid_max) == (0.0, 1.0)
