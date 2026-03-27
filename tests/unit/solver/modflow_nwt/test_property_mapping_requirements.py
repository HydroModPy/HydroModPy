from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
    resolve_required_flow_properties,
)


def test_resolve_required_flow_properties_steady_requires_only_k() -> None:
    assert resolve_required_flow_properties(flow_regime="steady") == frozenset({"K"})


def test_resolve_required_flow_properties_transient_requires_k_sy_ss() -> None:
    assert resolve_required_flow_properties(flow_regime="transient") == frozenset({"K", "Sy", "Ss"})


def test_resolve_required_flow_properties_unknown_regime_defaults_to_full_set() -> None:
    assert resolve_required_flow_properties(flow_regime="unknown") == frozenset({"K", "Sy", "Ss"})
