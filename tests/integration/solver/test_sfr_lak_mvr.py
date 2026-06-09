"""Coupled SFR -> MVR -> LAK on a tiny DISV model: the lake receives the stream.

The production SFR builder emits the SFR -> LAK MoverRecord for the terminal
reach (``outflow_to_lake = 1``); the MVR block is assembled exactly as
``build.py`` does. Real MF6 runs and the transfer is verified on BOTH sides:
the terminal reach ``to-mvr`` equals the lake ``from-mvr`` (TOLERANCES row 46),
the routed identity holds and the global budget closes (rows 44-45).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy
from tests.integration.solver._sfr_models import (
    INFLOW_M3S,
    RUNOFF_M3S,
    run_coupled_sfr_lak_model,
)

# tests/TOLERANCES.md row 44: global budget closure.
_BUDGET_PERCENT_DISCREPANCY = 1.0
# tests/TOLERANCES.md row 46: MVR transfer reciprocity (to-mvr vs from-mvr).
_MVR_RECIPROCITY_RTOL = 1e-9
# tests/TOLERANCES.md row 45: routed identity with streambed exchange.
_EXCHANGE_IDENTITY_REL = 1e-2


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_terminal_reach_feeds_the_lake_through_mvr(tmp_path: Path) -> None:
    network, sfr_obs, lak_obs = run_coupled_sfr_lak_model(tmp_path)
    terminal = max(reach.ifno for reach in network.reaches)

    to_mvr = -sfr_obs[f"R{terminal}_TO_MVR"]  # outflow side, reported negative
    from_mvr = lak_obs["LAC0_FROM_MVR"]

    # The transfer actually happened and is the full network outflow.
    assert to_mvr > 0.0
    assert from_mvr == pytest.approx(to_mvr, rel=_MVR_RECIPROCITY_RTOL)

    # Nothing leaks out of the network side-channel: ext-outflow is zero on the
    # terminal reach (MVR takes all of it) and the routed identity holds.
    assert sfr_obs[f"R{terminal}_EXT_OUTFLOW"] == pytest.approx(0.0, abs=1e-12)
    gw_loss = sum(
        sfr_obs[f"R{reach.ifno}_GW_EXCHANGE"]
        for reach in network.reaches
        if reach.cellid is not None
    )
    expected = INFLOW_M3S + RUNOFF_M3S - gw_loss
    assert abs(to_mvr - expected) / (INFLOW_M3S + RUNOFF_M3S) <= _EXCHANGE_IDENTITY_REL

    # The lake actually received the water: its steady stage sits above the bed.
    assert lak_obs["LAC0_STAGE"] > 90.0

    discrepancy = _last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) <= _BUDGET_PERCENT_DISCREPANCY
