"""What the ``data-fetch`` declaration promises, held against the port.

The declaration composes six sources, and three of its members are **derived**
from them rather than written: the hosts it may reach, the payload paths it may
write, and the option documents a request may carry. A derivation nobody checks
is a copy that drifts on the first source added, so each one is compared here to
the thing it was derived from.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.fetch.artefacts import POINT_COLUMNS
from hydromodpy.data.fetch.capability import (
    DATA_FETCH,
    DOOR_TAG,
    PAYLOAD_PATHS,
    REACHED_HOSTS,
    REPORT_PATH,
    SERVED_SOURCES,
    BboxExtentInput,
    DataFetchRequest,
    EuHydroOptions,
    InstalledSourceOptions,
    OsmOptions,
    PeriodInput,
    SourceOptions,
)
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import ALL_PAYLOAD_KINDS
from hydromodpy.schema.capability import HOST_PATTERN

CALLER_EXTENT = {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}


def _option_models() -> tuple[type, ...]:
    """Every member of the tagged union, read off the annotation."""
    from typing import get_args

    union, _ = get_args(SourceOptions)
    return tuple(get_args(union))


def _tag_of(model: type) -> str:
    return model.model_fields["id"].annotation.__args__[0]


def _describing_models() -> tuple[type, ...]:
    """The members that name a source, which is every one but the door."""
    return tuple(model for model in _option_models() if _tag_of(model) != DOOR_TAG)


def test_the_served_sources_span_every_payload_kind() -> None:
    """Four lookalikes would make the artefact writers untested by construction."""
    assert {source.payload_kind for source in SERVED_SOURCES} == set(ALL_PAYLOAD_KINDS)
    assert len({source.extent_crs for source in SERVED_SOURCES}) >= 2


def test_every_served_source_has_one_options_model_and_the_reverse() -> None:
    models = _describing_models()

    assert {_tag_of(model) for model in models} == {source.source_id for source in SERVED_SOURCES}
    assert len(models) == len(SERVED_SOURCES)


def test_the_union_tags_the_shipped_sources_and_one_door() -> None:
    """Exactly one member tags no source, and every other one tags a shipped source.

    Read off the **frozen** ``SERVED_SOURCES``, not recomputed: the table is
    built once at import and a test that recomputes both sides of the filter
    agrees with itself whatever the filter does.
    """
    tags = {_tag_of(model) for model in _option_models()}
    shipped = set(registry.builtin_source_ids())

    assert DOOR_TAG == "installed"
    assert tags - shipped == {DOOR_TAG}, "a member tags neither a shipped source nor the door"
    assert {source.source_id for source in SERVED_SOURCES} == tags - {DOOR_TAG}
    assert len(SERVED_SOURCES) == len(_option_models()) - 1


def test_the_door_stays_out_of_the_table_when_a_builtin_is_unregistered(
    isolated_registry: object,
) -> None:
    """The filter reads the union, never the registry, and this is why.

    ``registry.unregister`` pops the built-in declaration, so a filter asking
    the registry what this build ships would let a **described** source fall
    out of ``SERVED_SOURCES`` and out of ``reaches_network`` -- silently, and
    for the rest of the process, since the table is built once at import.
    """
    registry.unregister("bdtopage")

    from hydromodpy.data.fetch.capability import _served_source_ids

    assert "bdtopage" in _served_source_ids()
    assert DOOR_TAG not in _served_source_ids()


def test_an_options_model_builds_the_source_it_is_tagged_for() -> None:
    for model in _describing_models():
        tag = _tag_of(model)
        built = model.model_validate({"id": tag}).build()
        assert built.source_id == tag


@pytest.mark.parametrize(
    ("model", "document", "expected"),
    [
        (
            EuHydroOptions,
            {"id": "euhydro", "group_name": "Canal_lines", "euhydro_page_size": 250},
            ("Canal_lines", 250),
        ),
        (
            OsmOptions,
            {"id": "osm", "waterway_types": ["canal", "ditch"]},
            ("canal", "ditch"),
        ),
    ],
    ids=["euhydro", "osm"],
)
def test_the_newly_described_sources_build_from_their_typed_options(
    model: type, document: dict[str, object], expected: tuple[object, ...]
) -> None:
    source = model.model_validate(document).build()

    if source.source_id == "euhydro":
        assert (source.group_name, source.euhydro_page_size) == expected
    else:
        assert source.waterway_types == expected


@pytest.mark.parametrize(
    "source",
    [
        {"id": "euhydro", "euhydro_page_size": 0},
        {"id": "euhydro", "group_name": " \t"},
        {"id": "osm", "waterway_types": []},
        {"id": "osm", "waterway_types": ["river", " \n"]},
        {"id": "osm", "waterway_types": ["river"], "group_name": "wrong-source"},
    ],
    ids=[
        "euhydro-page-size",
        "euhydro-blank-group",
        "osm-empty-types",
        "osm-blank-type",
        "osm-foreign-option",
    ],
)
def test_typed_source_options_refuse_a_value_their_adapter_cannot_serve(source: dict) -> None:
    with pytest.raises(ValueError):
        DataFetchRequest.model_validate({"source": source, "extent": dict(CALLER_EXTENT)})


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


# --------------------------------------------------------------------------- #
# The member that names a source this build does not describe
# --------------------------------------------------------------------------- #


class AcmeRadarSource:
    """A conforming source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-radar"
    payload_kind: ClassVar[str] = "fields"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "required"
    hosts: ClassVar[tuple[str, ...]] = ("radar.acme.example",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, sweep: str = "long") -> None:
        self.sweep = sweep
        self.variables: tuple[str, ...] = ("radar_rainfall",)

    def fetch(self, request: object) -> None:  # pragma: no cover - never fetched here
        raise AssertionError("this test double is resolved, never run")


def _installed(name: str, **options: object) -> dict:
    return {"id": "installed", "name": name, "options": options}


def test_a_request_names_a_source_this_repository_does_not_name(
    isolated_registry: object,
) -> None:
    """The exit gate of F5e-3, on the request side.

    ``grep -r acme-radar hydromodpy/`` finds nothing, and this document reaches
    the class anyway, with the argument its own constructor names.
    """
    registry.register(AcmeRadarSource)

    request = DataFetchRequest.model_validate(
        {"source": _installed("acme-radar", sweep="short"), "extent": dict(CALLER_EXTENT)}
    )
    built = request.source.build()

    assert type(built) is AcmeRadarSource
    assert built.sweep == "short"


def test_installing_a_source_does_not_move_what_the_build_describes(
    isolated_registry: object,
) -> None:
    """D146 under the change: resolvable grew, described did not.

    The published description is package data compared byte for byte, so a
    plugin that widened ``SERVED_SOURCES`` or ``REACHED_HOSTS`` would make a
    frozen document depend on what is installed next to it.
    """
    before_sources = tuple(SERVED_SOURCES)
    before_hosts = tuple(REACHED_HOSTS)
    registry.register(AcmeRadarSource)

    assert registry.is_registered("acme-radar")
    assert tuple(SERVED_SOURCES) == before_sources
    assert tuple(REACHED_HOSTS) == before_hosts
    assert "radar.acme.example" not in DATA_FETCH.reaches_network


def test_a_name_this_installation_does_not_resolve_is_refused_before_the_job() -> None:
    with pytest.raises(ValueError, match="acme-radar"):
        DataFetchRequest.model_validate(
            {"source": _installed("acme-radar"), "extent": dict(CALLER_EXTENT)}
        )


def test_a_described_source_is_refused_through_the_door_it_does_not_need() -> None:
    """Two ways to ask for one source is how a request and its description diverge."""
    with pytest.raises(ValueError, match="describes"):
        DataFetchRequest.model_validate(
            {"source": _installed("bdtopage"), "extent": dict(CALLER_EXTENT)}
        )


@pytest.mark.parametrize("name", ["euhydro", "osm"])
def test_a_described_source_is_refused_through_the_door_it_no_longer_needs(name: str) -> None:
    with pytest.raises(ValueError, match="describes"):
        DataFetchRequest.model_validate({"source": _installed(name), "extent": dict(CALLER_EXTENT)})


def test_an_option_the_installed_source_cannot_take_is_refused_by_name(
    isolated_registry: object,
) -> None:
    """The bag is bound against the plugin's own signature, which is the only check there is."""
    registry.register(AcmeRadarSource)

    with pytest.raises(ValueError, match="resolution_m"):
        DataFetchRequest.model_validate(
            {
                "source": _installed("acme-radar", resolution_m=25),
                "extent": dict(CALLER_EXTENT),
            }
        )


def test_a_constructor_that_names_nothing_refuses_nothing(isolated_registry: object) -> None:
    """``**kwargs`` is a source saying it will take whatever it is handed.

    Pinned rather than tolerated. A signature is the only authority this build
    has over an installed source's options, and a bag declares no name, so
    everything binds. The refusal above is real for a source that declares its
    parameters and vacuous for one that does not, and a reader of the published
    description has to be able to know which.
    """

    class BagSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-bag"

        def __init__(self, **options: object) -> None:
            self.options = options
            self.variables: tuple[str, ...] = ("radar_rainfall",)

    registry.register(BagSource)
    request = DataFetchRequest.model_validate(
        {
            "source": _installed("acme-bag", anything={"nested": 1}),
            "extent": dict(CALLER_EXTENT),
        }
    )

    assert request.source.build().options == {"anything": {"nested": 1}}


def test_a_constructor_that_refuses_its_options_is_a_fault_of_the_request(
    isolated_registry: object,
) -> None:
    """A signature check catches a name and an arity, never a type.

    Without this, a wrong-typed option reached the constructor, raised a
    ``TypeError`` there and left as ``HMPY.E000`` and exit code 1 -- the code
    that tells an orchestrator HydroModPy is broken when the request is. The
    described sources keep the old behaviour on purpose: their
    constructors are this repository's, so one of them raising *is* a bug here.
    """

    class TypedSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-typed"

        def __init__(self, *, sweeps: int = 4) -> None:
            self.buffer = [0] * sweeps
            self.variables: tuple[str, ...] = ("radar_rainfall",)

    registry.register(TypedSource)
    request = DataFetchRequest.model_validate(
        {"source": _installed("acme-typed", sweeps="four"), "extent": dict(CALLER_EXTENT)}
    )

    with pytest.raises(DataRequestError, match="acme-typed"):
        request.source.build()


def test_an_argument_the_installed_source_demands_is_refused_when_missing(
    isolated_registry: object,
) -> None:
    """Otherwise it is a ``TypeError`` mid-job, which maps to "this is a HydroModPy bug"."""

    class DemandingSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-demanding"

        def __init__(self, *, licence_key: str) -> None:
            super().__init__()
            self.licence_key = licence_key

    registry.register(DemandingSource)

    with pytest.raises(ValueError, match="licence_key"):
        DataFetchRequest.model_validate(
            {"source": _installed("acme-demanding"), "extent": dict(CALLER_EXTENT)}
        )
