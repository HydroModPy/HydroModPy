"""The facts of a promoted run say what its session found.

The convergence of the trial solve, the parameters that ended on a bound, and
the parameters the session set: their rows say ``origin = "calibrated"``, whether they were
written before the promotion was applied or after it, and a sealed run reads
them back from its manifest.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hydromodpy.results.manifest import ParameterRow
from hydromodpy.results.storage.run_facts import (
    CalibratedParameter,
    PromotionFacts,
    RunFacts,
)
from tests._helpers.run_records import make_record

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


def test_the_promotion_writes_the_convergence_and_the_bounds() -> None:
    facts = _facts()

    facts.apply_promotion(_promotion())

    assert not {"cost_name", "cost", "objective_window"} & set(RunFacts.model_fields)
    assert facts.converged is True
    assert facts.bounds_hit == ["K"]


def test_a_row_written_before_the_promotion_is_marked_calibrated() -> None:
    facts = _facts()
    facts.put_parameter(_row("K", value=1e-6))
    facts.put_parameter(_row("Ss", value=1e-5))

    facts.apply_promotion(_promotion())

    by_name = {row.name: row for row in facts.parameters}
    assert (by_name["K"].origin, by_name["K"].calibrated) == ("calibrated", True)
    assert (by_name["Ss"].origin, by_name["Ss"].calibrated) == ("declared", False)


def test_a_row_written_after_the_promotion_is_marked_calibrated() -> None:
    facts = _facts()
    facts.apply_promotion(_promotion())

    facts.put_parameter(_row("K", value=1e-6))

    assert facts.parameters[0].origin == "calibrated"
    assert facts.parameters[0].calibrated is True


def test_a_zone_names_its_rows_only() -> None:
    facts = _facts()
    facts.apply_promotion(_promotion(calibrated=[CalibratedParameter(name="K", zone="granite")]))

    facts.put_parameter(_row("K", zone="granite"))
    facts.put_parameter(_row("K", zone="schist"))

    marked = {row.zone: row.calibrated for row in facts.parameters}
    assert marked == {"granite": True, "schist": False}


def test_the_calibrated_parameters_survive_the_facts_document() -> None:
    facts = _facts()
    facts.apply_promotion(_promotion())

    again = RunFacts.model_validate(facts.model_dump(mode="json", by_alias=True))
    again.put_parameter(_row("K"))

    assert again.calibrated == [CalibratedParameter(name="K")]
    assert again.parameters[0].calibrated is True


def test_a_sealed_run_reads_its_calibrated_parameters_back() -> None:
    record = make_record(
        parameters=[
            ParameterRow(name="K", value=1e-6, origin="calibrated", calibrated=True),
            _row("Ss", value=1e-5),
        ]
    )
    manifest = record.to_manifest(sealed_at=NOW, artifacts=[])

    facts = RunFacts.from_manifest(manifest)

    assert facts.calibrated == [CalibratedParameter(name="K", zone="catchment")]
