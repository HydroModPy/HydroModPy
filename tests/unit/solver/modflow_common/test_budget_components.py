"""MODFLOW-NWT stream and lake records share the MODFLOW 6 SFR and LAK terms."""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_common.budget_components import canonical_budget_component

NWT_NAMES = [
    pytest.param("  stream   leakage ", "stream", id="stream leakage"),
    pytest.param("Lake Seepage", "lake", id="lake seepage"),
]


@pytest.mark.parametrize(("record", "component"), NWT_NAMES)
def test_nwt_record_name(record, component) -> None:
    assert canonical_budget_component(record) == component
