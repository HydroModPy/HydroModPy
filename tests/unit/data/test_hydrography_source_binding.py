"""What a ``[[data.hydrography.sources]]`` entry hands the source it names.

The binder replaced three copies of one name list with one rule -- a source is
handed the section field its constructor names -- and that rule is the only
place a value could now reach the wrong source silently. The table below is the
gate: it pins, per source this build ships, which section fields the binder
binds, so a constructor parameter renamed into a collision fails here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source import registry
from hydromodpy.data.variables.hydrography.api_source import source_from_section
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

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
