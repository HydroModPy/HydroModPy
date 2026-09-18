"""What a ``[[data.hydrography.sources]]`` entry hands the source it names.

The binder replaced three copies of one name list with one rule -- a source is
handed the section field its constructor names -- and that rule is the only
place a value could now reach the wrong source silently. The table below is the
gate: it pins, per source this build ships, which section fields the binder
binds, so a constructor parameter renamed into a collision fails here.
"""

from __future__ import annotations

import tomllib
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
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)

BOUND_FIELDS: dict[str, tuple[str, ...]] = {
    "bdtopage": ("typename", "page_size"),
    "euhydro": ("group_name", "euhydro_page_size"),
    "osm": ("waterway_types",),
    "hubeau-piezometry": (),
    "ign-bdalti": ("force_refresh",),
    "sim2-precipitation": (),
}
"""Section fields each source takes, measured against its own signature.

The two empty entries are half the point of the table: those sources are
registered and serve other variables, so a hydrography section carries nothing
they ask for, and adding a ``product`` or a ``components`` field here cannot
start feeding them by accident.

``ign-bdalti`` is the other half, and this gate is how it was found. It takes
``force_refresh``, which the section also carries with the same meaning -- skip
the cache, ask the provider again -- so binding it is right, and the manager
acting on the same field for its own catalogue is not a contradiction: one
bypasses the provider's cache, the other the catalogue's. A source named in a
hydrography section still has to answer with a feature table, which
``fetch_network`` is what refuses.
"""

SECTION_ONLY_FIELDS = ("source", "path", "rasterize_field")
"""Fields of the section no source may take.

``source`` is the selector, ``path`` belongs to the ``custom`` loader, and
``rasterize_field`` is the manager's: what a vector is burned onto a grid by is
decided after a fetch, never inside one.
"""


def _bindable_parameters(source_id: str) -> tuple[str, ...]:
    """Every parameter of a source a keyword can reach, which is what binds."""
    import inspect

    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    parameters = inspect.signature(registry.get(source_id)).parameters
    return tuple(name for name, parameter in parameters.items() if parameter.kind in bindable)


def test_the_table_covers_every_source_this_build_ships() -> None:
    assert set(BOUND_FIELDS) == set(registry.builtin_source_ids())


@pytest.mark.parametrize("source_id", sorted(BOUND_FIELDS))
def test_the_bound_fields_are_exactly_the_shared_names(source_id: str) -> None:
    section_fields = set(HydrographySourceConfig.model_fields)
    shared = tuple(name for name in _bindable_parameters(source_id) if name in section_fields)
    assert shared == BOUND_FIELDS[source_id]


def test_no_source_takes_a_field_the_manager_owns() -> None:
    for source_id in registry.builtin_source_ids():
        taken = set(_bindable_parameters(source_id)) & set(SECTION_ONLY_FIELDS)
        assert not taken, f"{source_id} would be handed {sorted(taken)}"


def test_a_section_hands_over_the_values_it_declares() -> None:
    section = HydrographySourceConfig(
        source="bdtopage",
        typename="sa:Other_Topage",
        page_size=17,
    )
    source = source_from_section(section)

    assert source.source_id == "bdtopage"
    assert source.typename == "sa:Other_Topage"
    assert source.page_size == 17


def test_the_two_paging_fields_do_not_cross() -> None:
    """The one collision the flat section could produce, pinned by value."""
    section = HydrographySourceConfig(
        source="euhydro",
        page_size=2000,
        euhydro_page_size=250,
    )
    source = source_from_section(section)

    assert source.euhydro_page_size == 250, "euhydro must not inherit BD Topage's page size"


def test_osm_takes_its_waterway_types_and_nothing_else() -> None:
    section = HydrographySourceConfig(source="osm", waterway_types=["canal"])
    source = source_from_section(section)

    assert source.waterway_types == ("canal",)
    assert not hasattr(source, "typename")


def test_a_source_the_section_says_nothing_about_gets_its_own_defaults() -> None:
    """How a third-party source is served: defaults, never a missing argument."""
    from hydromodpy.data.source.euhydro import DEFAULT_GROUP_NAME, DEFAULT_PAGE_SIZE

    source = registry.build_from_section(
        registry.get("euhydro"),
        SimpleNamespace(source="euhydro"),
    )

    assert source.group_name == DEFAULT_GROUP_NAME
    assert source.euhydro_page_size == DEFAULT_PAGE_SIZE


def test_a_positional_or_keyword_parameter_is_bound_too() -> None:
    """The style a third-party source is most likely to write, and it must work.

    Binding keyword-only parameters alone passed every gate of this file,
    because all six in-tree sources declare theirs behind a ``*``. It silently
    dropped the value for anyone who did not.
    """

    class PlainSource:
        source_id = "acme-plain"

        def __init__(self, waterway_types=("river",)):
            self.waterway_types = waterway_types

    built = registry.build_from_section(
        PlainSource,
        HydrographySourceConfig(source="osm", waterway_types=["canal"]),
    )
    assert built.waterway_types == ["canal"]


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


def test_a_constructor_taking_only_a_bag_receives_nothing() -> None:
    """``**kwargs`` is not a declaration, so the binder passes it no field."""

    class BagSource:
        source_id = "acme-bag"

        def __init__(self, **options: object) -> None:
            self.options = options

    built = registry.build_from_section(
        BagSource,
        HydrographySourceConfig(source="osm", waterway_types=["canal"]),
    )
    assert built.options == {}


def test_a_section_naming_a_source_nobody_serves_is_refused_by_name() -> None:
    with pytest.raises(DataRequestError, match="acme-rivers"):
        source_from_section(SimpleNamespace(source="acme-rivers"))


def test_the_declared_defaults_match_the_config() -> None:
    """The adapters repeat the section's defaults so they stay pydantic-free."""
    from hydromodpy.data.source.euhydro import DEFAULT_GROUP_NAME, DEFAULT_PAGE_SIZE
    from hydromodpy.data.source.osm import DEFAULT_WATERWAY_TYPES

    fields = HydrographySourceConfig.model_fields
    assert fields["group_name"].default == DEFAULT_GROUP_NAME
    assert fields["euhydro_page_size"].default == DEFAULT_PAGE_SIZE
    assert tuple(fields["waterway_types"].default_factory()) == DEFAULT_WATERWAY_TYPES


def test_a_source_of_another_payload_kind_is_refused_before_it_is_built() -> None:
    """The resolver branches on "not custom", so the kind has to be checked here.

    Found by the adversarial gate of this phase: reading the kind off the
    answer meant a DEM source named in a hydrography section downloaded
    France-wide archives before anything refused it.
    """
    with pytest.raises(DataCapabilityError, match="ign-bdalti"):
        source_from_section(SimpleNamespace(source="ign-bdalti"))


def test_the_refusal_names_the_kind_the_variable_wants() -> None:
    with pytest.raises(DataCapabilityError, match=NETWORK_PAYLOAD_KIND):
        source_from_section(SimpleNamespace(source="sim2-precipitation"))


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
    names = [name for name in _documented_names() if name != "custom"]
    assert len(names) == 3, "the documented list lost a source without anyone noticing"
    for name in names:
        assert source_from_section(SimpleNamespace(source=name)).source_id == name


# --------------------------------------------------------------------------- #
# What a document may name, which is the whole of F5e-3
# --------------------------------------------------------------------------- #


class AcmeLineworkSource:
    """A river-network source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-linework"
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


def test_a_toml_section_names_a_source_this_repository_does_not_name(
    isolated_registry: object,
) -> None:
    """The exit gate of F5e-3, on the configuration side.

    The name reaches the source through a real TOML document and through the
    binder, and ``grep -r acme-linework hydromodpy/`` finds nothing: the list
    of names lives in the registry and the section no longer copies it.
    """
    registry.register(AcmeLineworkSource)

    section = HydrographySourceConfig.model_validate(tomllib.loads(SECTION_TOML))

    assert section.source == "acme-linework"
    built = source_from_section(section)
    assert type(built) is AcmeLineworkSource
    assert built.waterway_types == ("canal",), "the binder fed the plugin its own parameter"


def test_an_installed_source_of_another_kind_is_refused_by_the_document(
    isolated_registry: object,
) -> None:
    """Resolvable is not acceptable, and the document is where that is said."""
    registry.register(AcmeGaugeSource)

    with pytest.raises(ValidationError, match=NETWORK_PAYLOAD_KIND):
        HydrographySourceConfig(source="acme-gauge")


def test_a_name_nothing_resolves_is_refused_by_the_document() -> None:
    """The refusal a closed ``Literal`` used to give, given by the registry now."""
    with pytest.raises(ValidationError, match="acme-linework"):
        HydrographySourceConfig(source="acme-linework")


def test_the_refusal_names_the_field_and_not_only_the_entry() -> None:
    """A section carries nine fields, so the fault has to say which one is wrong.

    The check is a ``field_validator`` for this reason alone. On the model it
    would locate at ``sources[0]``, and a reader would be told that something
    in a nine-field table is wrong without being told what.
    """
    with pytest.raises(ValidationError) as raised:
        HydrographyConfig(sources=[{"source": "sim2-precipitation"}])

    assert raised.value.errors()[0]["loc"] == ("sources", 0, "source")
