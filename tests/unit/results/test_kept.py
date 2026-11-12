"""The level of a run (research, result, publication), what it keeps, and the witness ``gc`` leaves.

A kept trial is research, a promoted run is a result and a published copy is
publication. The witness lists the entries ``gc`` removed from a trial, with sizes in bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.storage.kept import LEVELS, Purged, Retention, level_of, read_purged
from hydromodpy.schema.lineage import Lineage
from hydromodpy.solver.base.results_config import ResultsConfig

EVERYTHING = BudgetKeep.everything()
CONSUMERS = BudgetKeep.of_terms({"drain", "recharge"})

LEVELS_OF = [
    pytest.param(None, False, "result", id="no lineage"),
    pytest.param(Lineage(kind="trial"), False, "research", id="a kept trial"),
    pytest.param(Lineage(kind="promoted"), False, "result", id="a promoted run"),
    pytest.param(Lineage(kind="rerun"), False, "result", id="a rerun"),
    pytest.param(Lineage(kind="version"), False, "result", id="a version"),
    pytest.param(Lineage(kind="replay"), False, "result", id="a replay"),
    pytest.param(Lineage(kind="promoted"), True, "publication", id="a published copy"),
    pytest.param(Lineage(kind="trial"), True, "publication", id="a published trial"),
]


@pytest.mark.parametrize(("lineage", "published", "level"), LEVELS_OF)
def test_level_of_a_lineage(lineage, published, level) -> None:
    assert level_of(lineage, published=published) == level


def test_kept_trial_budget_terms() -> None:
    retention = Retention.of("research", ResultsConfig(), CONSUMERS)

    assert retention.budget.keeps("drain")
    assert not retention.budget.keeps("storage_ss")


LEVEL_REFUSALS = [
    pytest.param("publication", "a published copy is made by hmp publish", id="publication"),
    pytest.param("published", "A run level is one of", id="unknown"),
    pytest.param("", "A run level is one of", id="empty"),
]


@pytest.mark.parametrize(("level", "sentence"), LEVEL_REFUSALS)
def test_refused_levels(level: str, sentence: str) -> None:
    with pytest.raises(ValueError, match=sentence):
        Retention.of(level, ResultsConfig(), EVERYTHING)


MEMBER_REFUSALS = [
    pytest.param({"level": "result", "budget": {"drain"}}, "budget", id="budget not a BudgetKeep"),
    pytest.param(
        {"level": "result", "budget": EVERYTHING, "solver_files": "yes"},
        "solver_files",
        id="solver files not a bool",
    ),
    pytest.param(
        {"level": "result", "budget": EVERYTHING, "face_flows": "yes"},
        "face_flows",
        id="face flows not a bool",
    ),
    pytest.param({"level": 4, "budget": EVERYTHING}, "level", id="level not a str"),
    pytest.param(
        {"level": "publication", "budget": EVERYTHING}, "a published copy", id="publication level"
    ),
]


@pytest.mark.parametrize(("members", "named"), MEMBER_REFUSALS)
def test_refused_members(members: dict, named: str) -> None:
    with pytest.raises((TypeError, ValueError), match=named):
        Retention(**members)


AT = datetime(2026, 11, 11, 8, 30, tzinfo=UTC)


def test_purged_entries() -> None:
    entries = {"fields.zarr": 1}

    assert Purged(at=AT, entries=entries).entries == entries


PURGED_REFUSALS = [
    pytest.param({"mesh": 1}, "names 'mesh', which gc never removes", id="the mesh a replay reads"),
    pytest.param(
        {"tables.parquet": 1},
        "names 'tables.parquet', which gc never removes",
        id="an entry gc never removes",
    ),
]


@pytest.mark.parametrize(("entries", "named"), PURGED_REFUSALS)
def test_purged_refusals(entries: dict[str, int], named: str) -> None:
    with pytest.raises(ValueError, match=named):
        Purged(at=AT, entries=entries)


def test_purged_schema_refused(tmp_path) -> None:
    path = tmp_path / "purged.json"
    path.write_text(json.dumps({"schema": "hydromodpy.purged.v2", "at": AT.isoformat()}), "utf-8")

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.purged.v2"):
        read_purged(tmp_path)
