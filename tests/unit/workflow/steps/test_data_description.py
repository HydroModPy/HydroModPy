"""The data description document that ``load_data`` writes, read back and compared.

A source that is a file carries the sha256 digest of that file, so the document says
which bytes the run consumed. Two documents of one run are compared to name the
variables whose source moved, which is how a resume reports what it did not reload.
"""

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


@dataclasses.dataclass
class Loaded:
    recharge: object = None
    geology: object = None
    loaded_plan_types: tuple[str, ...] | None = None


def test_empty_context_has_no_records() -> None:
    assert list(iter_loaded_records(Loaded())) == []
    assert list(iter_loaded_records(None)) == []


def test_document_round_trip(tmp_path: Path) -> None:
    payload = describe_loaded_data(
        Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),))),
        plan_types=("recharge",),
    )

    written = write_data_description(tmp_path, "run_a", payload)

    assert written == description_path(tmp_path)
    assert read_data_description(tmp_path) == payload
    assert read_data_description(tmp_path / "other_run") is None


def test_a_record_gained_or_lost_is_a_change() -> None:
    one = describe_loaded_data(
        Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )
    two = describe_loaded_data(
        Loaded(
            recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)),
            geology=FakeLoadResult(fields=(FakeRecord("geology", "brgm"),)),
        )
    )

    assert changed_sources(one, two) == ("geology:geology",)
    assert changed_sources(two, one) == ("geology:geology",)


COMPARED_WITH_NOTHING = [
    pytest.param(None, (), id="no earlier document"),
    pytest.param({}, ("recharge:recharge",), id="empty earlier document"),
    pytest.param({"records": []}, ("recharge:recharge",), id="earlier document without records"),
]


@pytest.mark.parametrize(("earlier", "changed"), COMPARED_WITH_NOTHING)
def test_comparing_against_nothing(earlier, changed) -> None:
    payload = describe_loaded_data(
        Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )

    assert changed_sources(earlier, payload) == changed


def test_shared_file_is_hashed_once(tmp_path: Path) -> None:
    shared = tmp_path / "shared.tif"
    shared.write_bytes(b"one raster, two variables")
    loaded = Loaded(
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


def test_digests_skip_sources_that_are_not_files() -> None:
    payload = describe_loaded_data(
        Loaded(recharge=FakeLoadResult(points=(FakeRecord("recharge", "synthetic"),)))
    )

    assert source_digests(payload) == {}
    assert source_digests(None) == {}
