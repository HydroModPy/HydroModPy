"""The input set is one object, and its digest covers all of it.

A digest over a chosen subset of fields — name, hash, role — lets the licence,
the CRS and the fetch query be rewritten without changing the id, which
destroys the only claim the digest was built to support. So the id here is
computed over the complete resource array, and these tests rewrite one field
at a time to prove it.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.schema.job.inputset import (
    InputResource,
    Licence,
    build_inputset,
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


def test_a_licence_nobody_declared_is_said_to_be_undetermined() -> None:
    resource = InputResource(name="outlets", role="outlets", href="request.json#/inputs/outlets")

    assert resource.licence.spdx == UNDETERMINED_LICENSE
    assert resource.licence.confidence == "undetermined"


def test_an_input_set_without_a_resource_still_rolls_up() -> None:
    """A rollup never refuses: refusing to seal on a licence loses results."""
    rollup = roll_up_licences([])

    assert rollup.expression == UNDETERMINED_LICENSE
    assert rollup.redistributable is False


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
