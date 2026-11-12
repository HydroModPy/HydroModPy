"""The data description document."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from hydromodpy.workflow.steps.data_description import (
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


def test_the_walk_of_an_empty_context_yields_nothing() -> None:
    """A context that loaded nothing is not an error, it is an empty walk."""
    assert list(iter_loaded_records(_Loaded())) == []
    assert list(iter_loaded_records(None)) == []


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
