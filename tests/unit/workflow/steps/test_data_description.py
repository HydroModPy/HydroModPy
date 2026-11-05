"""The data description document."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from hydromodpy.workflow.steps.data_description import (
    SCHEMA_VERSION,
    changed_sources,
    describe_loaded_data,
    description_path,
    iter_loaded_records,
    read_data_description,
    source_digests,
    write_data_description,
)
from tests.unit.workflow.steps._helpers import FakeLoadResult, FakeRecord

# --- test_data_description ---
# The document ``load_data`` writes, read back and compared.
#
# Two properties matter beyond the round-trip. A source that is a file carries the
# digest of that file, so the document says which bytes the run consumed; and two
# documents of the same run can be compared to name the variables whose source
# moved, which is how a resume reports that it did not reload what it loaded.


@dataclasses.dataclass
class _Loaded:
    recharge: object = None
    geology: object = None
    loaded_plan_types: tuple[str, ...] | None = None


def test_the_walk_yields_points_and_fields_with_their_scope() -> None:
    """Every record is named by the scope that holds it and by its kind."""
    loaded = _Loaded(
        recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)),
        geology=FakeLoadResult(fields=(FakeRecord("geology", "brgm"),)),
    )

    walked = {(item.scope, item.kind, item.variable) for item in iter_loaded_records(loaded)}

    assert walked == {
        ("recharge", "point", "recharge"),
        ("geology", "field", "geology"),
    }


def test_the_walk_of_an_empty_context_yields_nothing() -> None:
    """A context that loaded nothing is not an error, it is an empty walk."""
    assert list(iter_loaded_records(_Loaded())) == []
    assert list(iter_loaded_records(None)) == []


def test_a_file_backed_source_carries_the_digest_of_its_bytes(tmp_path: Path) -> None:
    """The document says which bytes the run consumed, not only which name."""
    source = tmp_path / "geology.gpkg"
    source.write_bytes(b"one geology layer")
    loaded = _Loaded(
        geology=FakeLoadResult(
            fields=(FakeRecord("geology", "custom", metadata={"vector_path": str(source)}),)
        )
    )

    payload = describe_loaded_data(loaded, plan_types=("geology",))

    assert payload["schema"] == SCHEMA_VERSION
    assert payload["plan_types"] == ["geology"]
    (record,) = payload["records"]
    assert record["source_path"] == str(source)
    assert record["source_sha256"] == hashlib.sha256(b"one geology layer").hexdigest()


def test_a_source_without_a_file_carries_no_digest() -> None:
    """A synthetic series is described as one instead of being given a digest."""
    loaded = _Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))

    (record,) = describe_loaded_data(loaded)["records"]

    assert record["source"] == "synthetic"
    assert record["source_path"] is None
    assert record["source_sha256"] is None


def test_the_document_round_trips_through_disk(tmp_path: Path) -> None:
    """What is written is what is read, under the run it belongs to."""
    payload = describe_loaded_data(
        _Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),))),
        plan_types=("recharge",),
    )

    written = write_data_description(tmp_path, "run_a", payload)

    assert written == description_path(tmp_path)
    assert read_data_description(tmp_path) == payload
    assert read_data_description(tmp_path / "other_run") is None


def test_a_document_of_another_schema_is_refused_by_name(tmp_path: Path) -> None:
    """A future schema is refused with the version read, never half understood."""
    from hydromodpy.core.exceptions import SchemaVersionMismatchError

    path = description_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydromodpy.loaded_data.v99", "records": []}', encoding="utf-8")

    with pytest.raises(
        SchemaVersionMismatchError, match="loaded_data.v99.*delete it and run again"
    ):
        read_data_description(tmp_path)


def test_a_rewritten_source_is_named_as_changed(tmp_path: Path) -> None:
    """The digest moves when the bytes move, and the variable is named."""
    source = tmp_path / "geology.gpkg"
    source.write_bytes(b"before")
    loaded = _Loaded(
        geology=FakeLoadResult(
            fields=(FakeRecord("geology", "custom", metadata={"vector_path": str(source)}),)
        )
    )
    before = describe_loaded_data(loaded)

    source.write_bytes(b"after")
    after = describe_loaded_data(loaded)

    assert changed_sources(before, after) == ("geology:geology",)
    assert changed_sources(before, before) == ()


def test_a_record_that_appears_or_disappears_is_a_change() -> None:
    """The plan itself moving counts: a variable gained is a variable changed."""
    one = describe_loaded_data(
        _Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )
    two = describe_loaded_data(
        _Loaded(
            recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)),
            geology=FakeLoadResult(fields=(FakeRecord("geology", "brgm"),)),
        )
    )

    assert changed_sources(one, two) == ("geology:geology",)
    assert changed_sources(two, one) == ("geology:geology",)


@pytest.mark.parametrize("missing", [None, {}, {"records": []}])
def test_comparing_against_nothing_names_nothing(missing) -> None:
    """A run with no earlier document has nothing to disagree with."""
    payload = describe_loaded_data(
        _Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )

    if missing is None:
        assert changed_sources(None, payload) == ()
    else:
        assert changed_sources(missing, payload) == ("recharge:recharge",)


def test_two_stations_of_one_variable_stay_two_records(tmp_path: Path) -> None:
    """The Hub'Eau managers label every station of a scope with one variable.

    A document that indexed one record per ``scope:variable`` would describe
    both piezometers as one, and a change on the first would vanish behind the
    second. This is the case a multi-station run is made of.
    """
    first = tmp_path / "A.csv"
    second = tmp_path / "B.csv"
    first.write_bytes(b"station A")
    second.write_bytes(b"station B")
    loaded = _Loaded(
        recharge=FakeLoadResult(
            points=(
                FakeRecord("piezo", "BSS-A", metadata={"source_path": str(first)}, station_id="A"),
                FakeRecord("piezo", "BSS-B", metadata={"source_path": str(second)}, station_id="B"),
            )
        )
    )
    before = describe_loaded_data(loaded)
    assert len(before["records"]) == 2
    assert {r["station_id"] for r in before["records"]} == {"A", "B"}

    first.write_bytes(b"station A, revised")
    after = describe_loaded_data(loaded)

    assert changed_sources(before, after) == ("recharge:piezo",)


def test_a_file_read_by_two_records_is_hashed_once(tmp_path: Path) -> None:
    """The digest of a file is a function of the file, not of its readers."""
    shared = tmp_path / "shared.tif"
    shared.write_bytes(b"one raster, two variables")
    loaded = _Loaded(
        geology=FakeLoadResult(
            fields=(
                FakeRecord("code", "custom", metadata={"raster_path": str(shared)}),
                FakeRecord("thickness", "custom", metadata={"raster_path": str(shared)}),
            )
        )
    )

    payload = describe_loaded_data(loaded)

    digests = {r["source_sha256"] for r in payload["records"]}
    assert digests == {hashlib.sha256(b"one raster, two variables").hexdigest()}
    assert source_digests(payload) == {str(shared): digests.pop()}


def test_the_digest_index_ignores_sources_that_are_not_files() -> None:
    """A synthetic series contributes no entry rather than a null one."""
    payload = describe_loaded_data(
        _Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )

    assert source_digests(payload) == {}
    assert source_digests(None) == {}


def test_the_record_order_does_not_follow_the_walk(tmp_path: Path) -> None:
    """A document whose order moved would move its digest, and replan a resume."""
    one = FakeRecord("piezo", "BSS-A", station_id="A")
    two = FakeRecord("piezo", "BSS-B", station_id="B")

    forward = describe_loaded_data(_Loaded(recharge=FakeLoadResult(points=(one, two))))
    backward = describe_loaded_data(_Loaded(recharge=FakeLoadResult(points=(two, one))))

    assert forward == backward
