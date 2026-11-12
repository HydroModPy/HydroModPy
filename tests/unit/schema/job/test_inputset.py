"""The input set of a job: licensed resources whose id digests every field.

A digest over a chosen subset (name, hash, role) would let the licence, the CRS
or the fetch query change without changing the id. So the id covers the whole
resource array. A licence nobody declared is undetermined, and a roll-up never
refuses, because refusing to seal on a licence would lose results.
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


def dem_resource(**overrides: object) -> InputResource:
    fields: dict[str, object] = {
        "name": "dem",
        "role": "dem",
        "href": "/data/dem.tif",
        "media_type": "image/tiff; application=geotiff",
        "bytes": 4,
        "sha256": "a" * 64,
        "licence": ETALAB,
    }
    return InputResource(**(fields | overrides))  # type: ignore[arg-type]


def test_same_resources_same_id() -> None:
    first = build_inputset([dem_resource()])
    second = build_inputset([dem_resource()])

    assert first.id == second.id
    assert first.id.startswith("sha256:")


def test_undeclared_licence_is_undetermined() -> None:
    resource = InputResource(name="outlets", role="outlets", href="request.json#/inputs/outlets")

    assert resource.licence.spdx == UNDETERMINED_LICENSE
    assert resource.licence.confidence == "undetermined"


def test_empty_set_still_rolls_up() -> None:
    rollup = roll_up_licences([])

    assert rollup.expression == UNDETERMINED_LICENSE
    assert rollup.redistributable is False


def test_inline_input_points_into_the_request() -> None:
    resource = inline_resource(
        "outlets",
        role="outlets",
        value=[{"site_id": "cheze", "x": 1.0, "y": 2.0}],
        pointer="/inputs/outlets",
    )

    assert resource.href == "request.json#/inputs/outlets"
    assert resource.bytes is None
    assert len(resource.sha256 or "") == 64


def test_inline_value_digest_ignores_key_order() -> None:
    first = inline_resource("o", role="outlets", value={"x": 1, "y": 2}, pointer="/inputs/o")
    second = inline_resource("o", role="outlets", value={"y": 2, "x": 1}, pointer="/inputs/o")

    assert first.sha256 == second.sha256


def test_two_resources_under_one_name_are_refused() -> None:
    with pytest.raises(ValueError, match="repeats the resource name"):
        build_inputset([dem_resource(), dem_resource(href="/data/other.tif")])
