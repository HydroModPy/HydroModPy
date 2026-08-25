"""Standalone SFR on a tiny DISV model: real MF6 run, budget + routing identity.

Two variants of the shared two-reach trace model run real MF6 (6.6.3):

* pure routing (``connected_to_aquifer = false``): the terminal EXT-OUTFLOW must
  equal inflow + runoff exactly (no streambed exchange to hide a routing bug);
* connected reaches: the same identity holds once the reach-aquifer exchange is
  added back, and the global GWF budget closes.

This is the proof that SFR routes standalone (no lake anywhere). Tolerances:
rows 44-45 of ``tests/TOLERANCES.md`` (single source of truth).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy
from tests._helpers.tolerances import tol
from tests.integration.solver._sfr_models import (
    INFLOW_M3S,
    RUNOFF_M3S,
    run_standalone_sfr_model,
)

# tests/TOLERANCES.md row 44 (fraction; the MF6 listing reports percent).
_BUDGET_CLOSURE_FRACTION = tol("sfr_standalone_budget_closure")
# tests/TOLERANCES.md row 45: per-SFR routing identity bands.
_ROUTING_IDENTITY_RTOL = 1e-6
_EXCHANGE_IDENTITY_REL = 1e-2


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_sfr_standalone_pure_routing_identity(tmp_path: Path) -> None:
    network, obs = run_standalone_sfr_model(tmp_path, connected=False)
    terminal = max(reach.ifno for reach in network.reaches)
    outflow = -obs[f"R{terminal}_EXT_OUTFLOW"]  # MF6 reports outflow negative
    expected = INFLOW_M3S + RUNOFF_M3S
    # Pure routing: no streambed exchange can hide a mis-route.
    assert outflow == pytest.approx(expected, rel=_ROUTING_IDENTITY_RTOL)
    # Headwater inflow arrived where it was injected.
    assert obs["R0_EXT_INFLOW"] == pytest.approx(INFLOW_M3S, rel=_ROUTING_IDENTITY_RTOL)

    discrepancy = _last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) / 100.0 <= _BUDGET_CLOSURE_FRACTION


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_sfr_standalone_connected_closes_mass_with_exchange(tmp_path: Path) -> None:
    network, obs = run_standalone_sfr_model(tmp_path, connected=True)
    terminal = max(reach.ifno for reach in network.reaches)
    outflow = -obs[f"R{terminal}_EXT_OUTFLOW"]
    # 'sfr' obs is positive when the stream loses water to the aquifer.
    gw_loss = sum(
        obs[f"R{reach.ifno}_GW_EXCHANGE"] for reach in network.reaches if reach.cellid is not None
    )
    expected = INFLOW_M3S + RUNOFF_M3S - gw_loss
    total_in = INFLOW_M3S + RUNOFF_M3S
    assert abs(outflow - expected) / total_in <= _EXCHANGE_IDENTITY_REL
    # The streambed exchange is a real, non-zero term in this variant.
    assert gw_loss != pytest.approx(0.0, abs=1e-12)

    discrepancy = _last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) / 100.0 <= _BUDGET_CLOSURE_FRACTION
