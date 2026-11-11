"""The level of a run, what it keeps, and the witness ``gc`` leaves on a trial."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.storage.kept import (
    LEVELS,
    PURGED_SCHEMA,
    Purged,
    Retention,
    at_least,
    level_of,
    read_purged,
    renders,
    write_purged,
)
from hydromodpy.schema.lineage import Lineage
from hydromodpy.solver.base.results_config import ResultsConfig

EVERYTHING = BudgetKeep.everything()
CONSUMERS = BudgetKeep.of_terms({"drain", "recharge"})

LEVEL_CASES = (
    ("no lineage", None, False, "result"),
    ("a kept trial", Lineage(kind="trial"), False, "research"),
    ("a promoted run", Lineage(kind="promoted"), False, "result"),
    ("a rerun", Lineage(kind="rerun"), False, "result"),
    ("a version", Lineage(kind="version"), False, "result"),
    ("a replay", Lineage(kind="replay"), False, "result"),
    ("a published copy", Lineage(kind="promoted"), True, "publication"),
    ("a published trial", Lineage(kind="trial"), True, "publication"),
)


@pytest.mark.parametrize(
    ("case", "lineage", "published", "level"), LEVEL_CASES, ids=[case for case, *_ in LEVEL_CASES]
)
def test_a_level_is_read_from_the_lineage(
    case: str, lineage: Lineage | None, published: bool, level: str
) -> None:
    del case

    assert level_of(lineage, published=published) == level


AT_LEAST = tuple(
    (level, wanted, LEVELS.index(level) >= LEVELS.index(wanted))
    for level in LEVELS
    for wanted in LEVELS
)


@pytest.mark.parametrize(
    ("level", "wanted", "holds"),
    AT_LEAST,
    ids=[f"{level} at least {wanted}" for level, wanted, _ in AT_LEAST],
)
def test_a_level_holds_from_wanted_upward(level: str, wanted: str, holds: bool) -> None:
    assert at_least(level, wanted) is holds


RENDERS = (("research", False), ("result", True), ("publication", True))


@pytest.mark.parametrize(("level", "holds"), RENDERS, ids=[level for level, _ in RENDERS])
def test_only_a_result_and_above_render(level: str, holds: bool) -> None:
    assert renders(level) is holds


RETENTION_KEYS = tuple(
    (
        f"{level}, solver files {solver_files}, face flows {face_flows}",
        level,
        solver_files,
        face_flows,
    )
    for level in ("research", "result")
    for solver_files in (False, True)
    for face_flows in (False, True)
)


@pytest.mark.parametrize(
    ("case", "level", "solver_files", "face_flows"),
    RETENTION_KEYS,
    ids=[case for case, *_ in RETENTION_KEYS],
)
def test_a_retention_reads_the_level_and_the_results_table(
    case: str, level: str, solver_files: bool, face_flows: bool
) -> None:
    del case
    results = ResultsConfig(keep_solver_files=solver_files, keep_face_flows=face_flows)

    retention = Retention.of(level, results, EVERYTHING)

    assert retention.level == level
    assert retention.budget is EVERYTHING
    assert retention.solver_files is (solver_files if level == "result" else False)
    assert retention.face_flows is (face_flows if level == "result" else False)


def test_the_defaults_keep_every_term_and_drop_both_raw_groups() -> None:
    retention = Retention.of("result", ResultsConfig(), EVERYTHING)

    assert retention == Retention(level="result", budget=EVERYTHING)


def test_the_per_cell_budget_of_a_kept_trial_holds_its_consumer_terms() -> None:
    retention = Retention.of("research", ResultsConfig(), CONSUMERS)

    assert retention.budget.keeps("drain")
    assert not retention.budget.keeps("storage_ss")


@pytest.mark.parametrize(
    ("level", "sentence"),
    [
        ("publication", "a published copy is made by hmp publish"),
        ("published", "A run level is one of"),
        ("", "A run level is one of"),
    ],
    ids=["publication", "unknown", "empty"],
)
def test_a_retention_refuses_a_level_a_run_is_not_written_at(level: str, sentence: str) -> None:
    with pytest.raises(ValueError, match=sentence):
        Retention.of(level, ResultsConfig(), EVERYTHING)


@pytest.mark.parametrize(
    ("members", "named"),
    [
        ({"level": "result", "budget": {"drain"}}, "budget"),
        ({"level": "result", "budget": EVERYTHING, "solver_files": "yes"}, "solver_files"),
        ({"level": "result", "budget": EVERYTHING, "face_flows": "yes"}, "face_flows"),
        ({"level": 4, "budget": EVERYTHING}, "level"),
        ({"level": "publication", "budget": EVERYTHING}, "a published copy"),
    ],
    ids=[
        "a budget that is not a BudgetKeep",
        "solver files that are not a bool",
        "face flows that are not a bool",
        "a level that is not a str",
        "the publication level",
    ],
)
def test_a_retention_refuses_a_member_of_the_wrong_type(members: dict, named: str) -> None:
    with pytest.raises((TypeError, ValueError), match=named):
        Retention(**members)


def test_a_retention_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Retention(level="result", budget=EVERYTHING).solver_files = True  # type: ignore[misc]


AT = datetime(2026, 11, 11, 8, 30, tzinfo=UTC)


def test_a_purge_witness_round_trips(tmp_path) -> None:
    purged = Purged(at=AT, entries={"fields.zarr": 4096})

    path = write_purged(tmp_path, purged)

    assert read_purged(tmp_path) == purged
    assert path.name == "purged.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == PURGED_SCHEMA
    assert payload["entries"] == {"fields.zarr": 4096}


def test_a_run_without_a_witness_reads_none(tmp_path) -> None:
    assert read_purged(tmp_path) is None


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        ({"fields.zarr": 1}, None),
        ({"mesh": 1}, "names 'mesh', which gc never removes"),
        ({"tables.parquet": 1}, "names 'tables.parquet', which gc never removes"),
    ],
    ids=["the fields", "the mesh a replay reads", "an entry gc never removes"],
)
def test_a_witness_names_only_what_gc_removes(entries: dict[str, int], named: str | None) -> None:
    if named is None:
        assert Purged(at=AT, entries=entries).entries == entries
    else:
        with pytest.raises(ValueError, match=named):
            Purged(at=AT, entries=entries)


def test_a_witness_of_another_schema_is_refused(tmp_path) -> None:
    path = tmp_path / "purged.json"
    path.write_text(json.dumps({"schema": "hydromodpy.purged.v2", "at": AT.isoformat()}), "utf-8")

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.purged.v2"):
        read_purged(tmp_path)
