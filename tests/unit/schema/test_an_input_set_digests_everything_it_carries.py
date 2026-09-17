"""The input set is one object, and its digest covers all of it.

A digest over a chosen subset of fields — name, hash, role — lets the licence,
the CRS and the fetch query be rewritten without changing the id, which
destroys the only claim the digest was built to support. So the id here is
computed over the complete resource array, and these tests rewrite one field
at a time to prove it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.schema.job.inputset import (
    InputResource,
    Licence,
    build_inputset,
    file_resource,
    inline_resource,
    roll_up_licences,
)

ETALAB = Licence(
    spdx="etalab-2.0",
    url="https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
    attribution="Source: IGN, RGE ALTI, Licence Ouverte 2.0",
    confidence="assumed",
)
ODBL = Licence(
    spdx="ODbL-1.0",
    attribution="© OpenStreetMap contributors",
    share_alike=True,
    confidence="declared",
)


def _dem(**overrides: object) -> InputResource:
    fields: dict[str, object] = {
        "name": "dem",
        "role": "dem",
        "href": "/data/dem.tif",
        "media_type": "image/tiff; application=geotiff",
        "bytes": 4,
        "sha256": "a" * 64,
        "licence": ETALAB,
    }
    fields.update(overrides)
    return InputResource(**fields)  # type: ignore[arg-type]


def test_the_same_resources_digest_to_the_same_id() -> None:
    first = build_inputset([_dem()])
    second = build_inputset([_dem()])

    assert first.id == second.id
    assert first.id.startswith("sha256:")


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("licence", Licence(spdx="CC-BY-4.0", confidence="assumed")),
        ("role", "elevation"),
        ("media_type", "application/octet-stream"),
        ("spatial", {"crs": "EPSG:2154"}),
        ("source", {"slug": "ign_rgealti"}),
        ("copied_to", "inputs/dem.tif"),
    ],
)
def test_rewriting_any_member_changes_the_id(member: str, value: object) -> None:
    """The defect this answers: a digest of three fields left the rest free."""
    assert build_inputset([_dem()]).id != build_inputset([_dem(**{member: value})]).id


def test_a_licence_nobody_declared_is_said_to_be_undetermined() -> None:
    resource = InputResource(name="outlets", role="outlets", href="request.json#/inputs/outlets")

    assert resource.licence.spdx == UNDETERMINED_LICENSE
    assert resource.licence.confidence == "undetermined"


def test_one_licence_rolls_up_to_itself() -> None:
    rollup = roll_up_licences([ETALAB, ETALAB])

    assert rollup.expression == "etalab-2.0"
    assert rollup.redistributable is True
    assert rollup.share_alike is False
    assert rollup.confidence == "assumed"
    assert rollup.attribution == ("Source: IGN, RGE ALTI, Licence Ouverte 2.0",)


def test_two_licences_roll_up_to_both_of_them() -> None:
    """One job legitimately mixes a share-alike database with an open one."""
    rollup = roll_up_licences([ETALAB, ODBL])

    assert rollup.expression == "ODbL-1.0 AND etalab-2.0"
    assert rollup.share_alike is True
    assert rollup.confidence == "assumed"
    assert len(rollup.attribution) == 2


def test_the_rollup_carries_the_lowest_confidence_of_any_member() -> None:
    rollup = roll_up_licences([ODBL, Licence()])

    assert rollup.confidence == "undetermined"
    assert rollup.redistributable is False


def test_an_input_set_without_a_resource_still_rolls_up() -> None:
    """A rollup never refuses: refusing to seal on a licence loses results."""
    rollup = roll_up_licences([])

    assert rollup.expression == UNDETERMINED_LICENSE
    assert rollup.redistributable is False


def test_a_file_resource_hashes_the_bytes_it_read(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"II*\x00")

    resource = file_resource(
        "dem", role="dem", path=dem, media_type="image/tiff; application=geotiff"
    )

    assert resource.bytes == 4
    assert resource.sha256 == hashlib.sha256(b"II*\x00").hexdigest()
    assert resource.href == str(dem)


def test_an_inline_input_points_into_the_document_that_already_holds_it() -> None:
    resource = inline_resource(
        "outlets",
        role="outlets",
        value=[{"site_id": "cheze", "x": 1.0, "y": 2.0}],
        pointer="/inputs/outlets",
    )

    assert resource.href == "request.json#/inputs/outlets"
    assert resource.bytes is None
    assert len(resource.sha256 or "") == 64


def test_the_same_inline_value_spelled_two_ways_digests_once() -> None:
    first = inline_resource("o", role="outlets", value={"x": 1, "y": 2}, pointer="/inputs/o")
    second = inline_resource("o", role="outlets", value={"y": 2, "x": 1}, pointer="/inputs/o")

    assert first.sha256 == second.sha256


def test_two_resources_under_one_name_are_refused() -> None:
    with pytest.raises(ValueError, match="repeats the resource name"):
        build_inputset([_dem(), _dem(href="/data/other.tif")])


def test_the_document_carries_the_rollup_and_the_resources() -> None:
    document = build_inputset([_dem()]).to_document()

    assert document["schema"] == "hmp-inputset/v1"
    assert document["id"] == build_inputset([_dem()]).id
    assert document["resources"][0]["licence"]["spdx"] == "etalab-2.0"
    assert document["licence_rollup"]["expression"] == "etalab-2.0"
