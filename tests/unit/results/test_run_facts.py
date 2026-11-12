"""The facts of a promoted run say what its session found.

A parameter the session calibrated has ``origin = "calibrated"`` on its row,
whether the row was written before the promotion was applied or after it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hydromodpy.results.record.manifest import ParameterRow
from hydromodpy.results.storage.run_facts import (
    CalibratedParameter,
    PromotionFacts,
    RunFacts,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 16, tzinfo=UTC)


def _facts() -> RunFacts:
    return RunFacts(
        sim_id="a" * 32,
        name="calage",
        case_id="calage",
        project="nancon",
        attempt=1,
        attempt_id="b" * 32,
        created_at=NOW,
        started_at=NOW,
    )


def _row(name: str, *, zone: str = "catchment", value: float = 1.0) -> ParameterRow:
    return ParameterRow(name=name, zone=zone, value=value, origin="declared", calibrated=False)


def _promotion(**updates) -> PromotionFacts:
    payload = {
        "converged": True,
        "bounds_hit": ["K"],
        "calibrated": [CalibratedParameter(name="K")],
    }
    payload.update(updates)
    return PromotionFacts(**payload)


def test_promotion_marks_rows_already_written() -> None:
    facts = _facts()
    facts.put_parameter(_row("K", value=1e-6))
    facts.put_parameter(_row("Ss", value=1e-5))

    facts.apply_promotion(_promotion())

    by_name = {row.name: row for row in facts.parameters}
    assert (by_name["K"].origin, by_name["K"].calibrated) == ("calibrated", True)
    assert (by_name["Ss"].origin, by_name["Ss"].calibrated) == ("declared", False)


def test_promotion_marks_its_zone_only() -> None:
    facts = _facts()
    facts.apply_promotion(_promotion(calibrated=[CalibratedParameter(name="K", zone="granite")]))

    facts.put_parameter(_row("K", zone="granite"))
    facts.put_parameter(_row("K", zone="schist"))

    marked = {row.zone: row.calibrated for row in facts.parameters}
    assert marked == {"granite": True, "schist": False}
