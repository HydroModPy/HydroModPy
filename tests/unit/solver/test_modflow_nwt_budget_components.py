"""MODFLOW-NWT stream and lake records share the MODFLOW 6 SFR and LAK terms."""

from __future__ import annotations

import pytest

from hydromodpy.core.field_routing import RELEASE_BUDGET_KEYS
from hydromodpy.solver.modflow_common.budget_components import (
    CANONICAL_BUDGET_TERMS,
    canonical_budget_component,
)


@pytest.mark.parametrize(
    ("nwt_record", "mf6_record", "term"),
    [("STREAM LEAKAGE", "SFR", "stream"), ("LAKE SEEPAGE", "LAK", "lake")],
)
def test_a_nwt_exchange_record_maps_to_the_term_of_its_modflow6_twin(
    nwt_record: str, mf6_record: str, term: str
) -> None:
    assert canonical_budget_component(nwt_record) == term
    assert canonical_budget_component(mf6_record) == term
    assert term in CANONICAL_BUDGET_TERMS
    assert term in RELEASE_BUDGET_KEYS


def test_the_nwt_record_name_is_normalized_before_the_lookup() -> None:
    assert canonical_budget_component("  stream   leakage ") == "stream"
    assert canonical_budget_component("Lake Seepage") == "lake"
