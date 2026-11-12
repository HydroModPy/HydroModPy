"""MODFLOW-NWT stream and lake records share the MODFLOW 6 SFR and LAK terms."""

from __future__ import annotations

from hydromodpy.solver.modflow_common.budget_components import canonical_budget_component


def test_the_nwt_record_name_is_normalized_before_the_lookup() -> None:
    assert canonical_budget_component("  stream   leakage ") == "stream"
    assert canonical_budget_component("Lake Seepage") == "lake"
