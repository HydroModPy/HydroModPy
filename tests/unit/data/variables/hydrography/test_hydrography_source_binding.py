"""What a ``[[data.hydrography.sources]]`` entry hands the source it names.

The binder replaced three copies of one name list with one rule -- a source is
handed the section field its constructor names -- and that rule is the only
place a value could now reach the wrong source silently. The table below is the
gate: it pins, per source this build ships, which section fields the binder
binds, so a constructor parameter renamed into a collision fails here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import FetchRequest, FetchResult, PayloadKind, extent_for
from hydromodpy.data.variables.hydrography.api_source import (
    NETWORK_PAYLOAD_KIND,
    source_from_section,
)
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

BOUND_FIELDS: dict[str, tuple[str, ...]] = {
    "bdtopage": ("page_size",),
    "euhydro": ("group_name", "euhydro_page_size"),
    "osm": ("waterway_types",),
}
"""Section fields each source takes, measured against its own signature."""

SECTION_ONLY_FIELDS = ("source", "path", "rasterize_field")
"""Fields of the section no source of THIS family may take.

``source`` is the selector, ``path`` belongs to the ``file`` loader, and
``rasterize_field`` is the manager's: what a vector is burned onto a grid by is
decided after a fetch, never inside one. A file-reading source of another
family (the Explore2 grids, and the ``file`` source of the full cache lot) does
take a path of its own; the table holds what a river network may name, and
says so in the test that walks it.
"""


def _bindable_parameters(source_id: str) -> tuple[str, ...]:
    """Every parameter of a source a keyword can reach, which is what binds."""
    import inspect

    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    parameters = inspect.signature(registry.data_sources.get("hydrography", source_id)).parameters
    return tuple(name for name, parameter in parameters.items() if parameter.kind in bindable)


def _network_source_ids() -> list[str]:
    """The shipped sources of the section that answer a river network.

    The generic ``file`` and ``url`` sources are registered under every section
    and answer files, which the manager reads itself; they bind ``path`` or
    ``url`` and belong to no network table.
    """
    return [
        source_id
        for source_id in registry.data_sources.names("hydrography", shipped_only=True)
        if registry.data_sources.get("hydrography", source_id).payload_kind == NETWORK_PAYLOAD_KIND
    ]


def test_the_two_paging_fields_do_not_cross() -> None:
    """The one collision the flat section could produce, pinned by value."""
    section = HydrographySourceConfig(
        source="euhydro",
        page_size=2000,
        euhydro_page_size=250,
    )
    source = source_from_section(section)

    assert source.euhydro_page_size == 250, "euhydro must not inherit BD Topage's page size"


def test_a_positional_only_constructor_is_refused_by_name() -> None:
    """A section fills a parameter by name, so it cannot fill this one."""

    class PositionalSource:
        source_id = "acme-positional"

        def __init__(self, waterway_types, /):
            self.waterway_types = waterway_types

    with pytest.raises(DataRequestError, match="waterway_types"):
        registry.build_from_section(
            PositionalSource,
            HydrographySourceConfig(source="osm", waterway_types=["canal"]),
        )


def test_a_section_naming_a_source_nobody_serves_is_refused_by_name() -> None:
    with pytest.raises(DataRequestError, match="acme-rivers"):
        source_from_section(SimpleNamespace(source="acme-rivers"))


def test_a_source_of_another_payload_kind_is_refused_before_it_is_built(
    isolated_registry: object,
) -> None:
    """The resolver branches on "not custom", so the kind has to be checked here.

    Found by the adversarial gate of this phase: reading the kind off the
    answer meant a DEM source named in a hydrography section downloaded
    France-wide archives before anything refused it.
    """
    registry.data_sources.register(AcmeGaugeSource)
    with pytest.raises(DataCapabilityError, match="acme-gauge"):
        source_from_section(SimpleNamespace(source="acme-gauge"))


def test_the_refusal_names_the_kind_the_variable_wants(isolated_registry: object) -> None:
    registry.data_sources.register(AcmeGaugeSource)
    with pytest.raises(DataCapabilityError, match=NETWORK_PAYLOAD_KIND):
        source_from_section(SimpleNamespace(source="acme-gauge"))


def _documented_names() -> tuple[str, ...]:
    """The source names the section documents, read off the field itself.

    The section used to carry a ``Literal`` and this list was read off it. It
    is read off ``value_docs`` now, for the reason the phase exists: the field
    accepts any id the registry resolves, so there is no closed annotation left
    to enumerate, and the only list the section still owns is the one it
    documents.
    """
    extra = HydrographySourceConfig.model_fields["source"].json_schema_extra
    return tuple(extra["value_docs"])


def test_every_source_the_section_documents_serves_a_network() -> None:
    """Anti-vacuity: a refusal that refused everything would pass both tests."""
    names = [name for name in _documented_names() if name not in ("file", "url")]
    assert len(names) == 3, "the documented list lost a source without anyone noticing"
    for name in names:
        assert source_from_section(SimpleNamespace(source=name)).source_id == name


# --------------------------------------------------------------------------- #
# What a document may name, which is the whole of F5e-3
# --------------------------------------------------------------------------- #


class AcmeLineworkSource:
    """A river-network source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-linework"
    section: ClassVar[str] = "hydrography"
    payload_kind: ClassVar[PayloadKind] = "features"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("linework.acme.example",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, waterway_types: list[str] | None = None) -> None:
        self.waterway_types = tuple(waterway_types or ())
        self.variables: tuple[str, ...] = ("stream_network",)

    def fetch(self, request: FetchRequest) -> FetchResult:  # pragma: no cover - not fetched here
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent_for(self, request),
        )


class AcmeGaugeSource(AcmeLineworkSource):
    """Installed, resolvable, and not a river network."""

    source_id: ClassVar[str] = "acme-gauge"
    payload_kind: ClassVar[PayloadKind] = "points"


SECTION_TOML = """
source = "acme-linework"
waterway_types = ["canal"]
"""


def test_an_installed_source_of_another_kind_is_refused_by_the_document(
    isolated_registry: object,
) -> None:
    """Resolvable is not acceptable, and the document is where that is said."""
    registry.data_sources.register(AcmeGaugeSource)

    with pytest.raises(ValidationError, match=NETWORK_PAYLOAD_KIND):
        HydrographySourceConfig(source="acme-gauge")
