"""A built structure's geometry and a coupling rule are not search targets.

``FlowBarrierConfig.crest_elevation`` / ``base_elevation`` and
``FlowReachNetworkConfig.outflow_value`` were deliberately left without a
``Calibrable`` annotation: the wall's elevations trade off against ``hydchr``
(a deeper foot and a lower ``hydchr`` reduce under-dam flow the same way), and
the MVR ``outflow_value`` is a coupling rule, not a hydraulic property. Letting
a search move any of them buys fit through equifinality or through masking a
structural error, rather than resolving a real physical unknown. This states
the boundary the catalogue draws rather than reciting the three names, so a
sibling field that IS a property is asserted calibratable too.
"""

from __future__ import annotations

from hydromodpy.calibration.targets import declared_calibrable
from hydromodpy.physics.flow.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachNetworkConfig


def test_the_barrier_elevations_are_not_calibratable() -> None:
    for name in ("crest_elevation", "base_elevation"):
        assert declared_calibrable(FlowBarrierConfig.model_fields[name]) is None


def test_the_mvr_coupling_value_is_not_calibratable() -> None:
    assert declared_calibrable(FlowReachNetworkConfig.model_fields["outflow_value"]) is None


def test_the_barrier_resistance_properties_stay_calibratable() -> None:
    for name in ("hydchr", "k"):
        assert declared_calibrable(FlowBarrierConfig.model_fields[name]) is not None


def test_the_reach_hydraulic_properties_stay_calibratable() -> None:
    for name in ("streambed_k", "manning"):
        assert declared_calibrable(FlowReachNetworkConfig.model_fields[name]) is not None
