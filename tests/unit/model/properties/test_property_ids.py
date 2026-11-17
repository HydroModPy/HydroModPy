"""The flow property ids: their default unit and the refusal of a retired spelling."""

from __future__ import annotations

import re

import pytest

from hydromodpy.model.properties.property_ids import (
    FLOW_PROPERTY_IDS,
    default_unit_of,
    refusal_of_a_retired_id,
)


@pytest.mark.parametrize("prop", FLOW_PROPERTY_IDS, ids=lambda prop: prop.id)
def test_a_known_id_takes_its_declared_unit(prop):
    assert default_unit_of(prop.id) == prop.unit


def test_a_free_id_takes_no_unit():
    assert default_unit_of("my_own_number") == "-"


@pytest.mark.parametrize(
    ("param_id", "match"),
    [
        ("K33", r"flow\.param\.K33 is now flow\.param\.Kv\."),
        ("sy", r"flow\.param\.sy is now flow\.param\.Sy\."),
        ("Kz", r"never been read by a solver.*Write flow\.param\.Kv"),
        ("Ky", r"Write flow\.param\.K22 to set it"),
    ],
)
def test_a_retired_id_is_refused_with_the_name_to_write(param_id, match):
    assert re.search(match, refusal_of_a_retired_id(param_id) or "")


@pytest.mark.parametrize("param_id", ["K", "Sy", "anything_else"])
def test_a_current_id_is_not_refused(param_id):
    assert refusal_of_a_retired_id(param_id) is None
