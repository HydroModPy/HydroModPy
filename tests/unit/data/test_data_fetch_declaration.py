"""What the ``data-fetch`` declaration promises, held against the port.

The declaration composes four sources, and three of its members are **derived**
from them rather than written: the hosts it may reach, the payload paths it may
write, and the option documents a request may carry. A derivation nobody checks
is a copy that drifts on the first source added, so each one is compared here to
the thing it was derived from.
"""

from __future__ import annotations

import pytest

from hydromodpy.data.fetch.artefacts import POINT_COLUMNS
from hydromodpy.data.fetch.capability import (
    DATA_FETCH,
    PAYLOAD_PATHS,
    REACHED_HOSTS,
    REPORT_PATH,
    SERVED_SOURCES,
    BboxExtentInput,
    DataFetchRequest,
    PeriodInput,
    SourceOptions,
)
from hydromodpy.data.source.port import ALL_PAYLOAD_KINDS
from hydromodpy.schema.capability import HOST_PATTERN

CALLER_EXTENT = {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}


def _option_models() -> tuple[type, ...]:
    """The four members of the tagged union, read off the annotation."""
    from typing import get_args

    union, _ = get_args(SourceOptions)
    return tuple(get_args(union))


def test_the_served_sources_span_every_payload_kind() -> None:
    """Four lookalikes would make the artefact writers untested by construction."""
    assert {source.payload_kind for source in SERVED_SOURCES} == set(ALL_PAYLOAD_KINDS)
    assert len({source.extent_crs for source in SERVED_SOURCES}) >= 2


def test_every_served_source_has_one_options_model_and_the_reverse() -> None:
    models = _option_models()
    tags = {model.model_fields["id"].annotation.__args__[0] for model in models}

    assert tags == {source.source_id for source in SERVED_SOURCES}
    assert len(models) == len(SERVED_SOURCES)


def test_an_options_model_builds_the_source_it_is_tagged_for() -> None:
    for model in _option_models():
        tag = model.model_fields["id"].annotation.__args__[0]
        built = model.model_validate({"id": tag}).build()
        assert built.source_id == tag


def test_the_declared_hosts_are_the_union_of_what_the_sources_declare() -> None:
    expected = sorted({host for source in SERVED_SOURCES for host in source.hosts})

    assert list(REACHED_HOSTS) == expected
    assert list(DATA_FETCH.reaches_network) == expected
    assert expected, "a capability that reaches no provider is not this one"
    for host in expected:
        assert HOST_PATTERN.match(host), host


def test_every_payload_kind_has_a_declared_artefact_to_land_in() -> None:
    assert set(PAYLOAD_PATHS) == set(ALL_PAYLOAD_KINDS)
    declared = {output.path for output in DATA_FETCH.outputs}
    assert set(PAYLOAD_PATHS.values()) <= declared


def test_the_report_is_the_only_artefact_a_run_always_writes() -> None:
    """Every payload output is optional, because only one of the four is written."""
    optional = {output.path for output in DATA_FETCH.outputs if not output.required}

    assert optional == set(PAYLOAD_PATHS.values())
    assert DATA_FETCH.output("report").required
    assert DATA_FETCH.output("report").path == REPORT_PATH


def test_the_point_table_names_the_station_and_the_observation() -> None:
    """The column order is a promise: a reader indexes it without a schema."""
    assert POINT_COLUMNS[0] == "station_id"
    assert POINT_COLUMNS[-2:] == ("datetime", "value")
    assert len(set(POINT_COLUMNS)) == len(POINT_COLUMNS)


# --------------------------------------------------------------------------- #
# What the request model refuses, before anything runs
# --------------------------------------------------------------------------- #


def test_a_request_that_selects_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="selects nothing"):
        DataFetchRequest.model_validate({"source": {"id": "bdtopage"}})


@pytest.mark.parametrize(
    "extra",
    [
        {"station_ids": ["BSS0000"]},
        {"mask": {"href": "watershed.gpkg"}},
    ],
    ids=["stations", "mask"],
)
def test_two_selectors_at_once_are_refused(extra: dict) -> None:
    with pytest.raises(ValueError, match="at once"):
        DataFetchRequest.model_validate(
            {"source": {"id": "bdtopage"}, "extent": dict(CALLER_EXTENT), **extra}
        )


def test_a_station_asked_for_twice_is_refused() -> None:
    """The port refuses it too, but only once the job directory has been touched."""
    with pytest.raises(ValueError, match="station_ids repeat"):
        DataFetchRequest.model_validate(
            {"source": {"id": "hubeau-piezometry"}, "station_ids": ["BSS0000", "BSS0000"]}
        )


def test_an_unknown_source_tag_is_refused_by_the_discriminator() -> None:
    with pytest.raises(ValueError):
        DataFetchRequest.model_validate(
            {"source": {"id": "nobody-serves-this"}, "extent": dict(CALLER_EXTENT)}
        )


def test_an_option_the_source_does_not_declare_is_refused() -> None:
    """``extra="forbid"`` on the option document, which is the point of tagging it."""
    with pytest.raises(ValueError):
        DataFetchRequest.model_validate(
            {
                "source": {"id": "bdtopage", "resolution_m": 25},
                "extent": dict(CALLER_EXTENT),
            }
        )


@pytest.mark.parametrize(
    "bbox",
    [[1.0, 2.0, 1.0, 3.0], [1.0, 2.0, 0.0, 3.0], [1.0, 2.0, 3.0, 2.0]],
    ids=["equal-x", "inverted-x", "equal-y"],
)
def test_an_empty_or_inverted_box_is_refused(bbox: list[float]) -> None:
    with pytest.raises(ValueError, match="empty or inverted"):
        BboxExtentInput.model_validate({"bbox": bbox, "crs": "EPSG:4326"})


def test_a_box_that_does_not_carry_four_bounds_is_refused() -> None:
    with pytest.raises(ValueError):
        BboxExtentInput.model_validate({"bbox": [1.0, 2.0, 3.0], "crs": "EPSG:4326"})


def test_a_crs_that_is_not_an_epsg_code_is_refused() -> None:
    with pytest.raises(ValueError):
        BboxExtentInput.model_validate({"bbox": [1.0, 2.0, 3.0, 4.0], "crs": "lambert93"})


def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="ends"):
        PeriodInput.model_validate({"start": "2020-12-31", "end": "2020-01-01"})


def test_a_date_without_a_time_is_read_as_a_window_bound() -> None:
    """An OGC client sends ``2020-01-01``; refusing it would be this boundary's fault."""
    period = PeriodInput.model_validate({"start": "2020-01-01", "end": "2020-01-31"})

    assert period.start.year == 2020
    assert period.end.day == 31
