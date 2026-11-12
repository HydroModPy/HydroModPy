"""A ``[[data.hydrography.sources]]`` entry is turned into the source it names.

A source is handed the section field its constructor names. The section holds
three shipped network sources (BD TOPAGE, EU-Hydro, OSM) and takes any other id
the registry resolves, provided the source answers a river network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import FetchRequest, FetchResult, PayloadKind, extent_for
from hydromodpy.data.variables.hydrography.api_source import (
    NETWORK_PAYLOAD_KIND,
    source_from_section,
)
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig


class AcmeGaugeSource:
    """Installed and resolvable, and not a river network."""

    source_id: ClassVar[str] = "acme-gauge"
    section: ClassVar[str] = "hydrography"
    payload_kind: ClassVar[PayloadKind] = "points"
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


def test_the_two_paging_fields_do_not_cross() -> None:
    # EU-Hydro must not inherit the page size of BD TOPAGE.
    section = HydrographySourceConfig(source="euhydro", page_size=2000, euhydro_page_size=250)

    assert source_from_section(section).euhydro_page_size == 250


def test_every_documented_source_serves_a_network() -> None:
    extra = HydrographySourceConfig.model_fields["source"].json_schema_extra
    names = [name for name in extra["value_docs"] if name not in ("file", "url")]

    assert len(names) == 3, "the documented list lost a source without anyone noticing"
    for name in names:
        assert source_from_section(SimpleNamespace(source=name)).source_id == name


# The two messages that a source of another payload kind is refused with.
GAUGE_REFUSALS = [
    pytest.param("acme-gauge", id="names the source"),
    pytest.param(NETWORK_PAYLOAD_KIND, id="names the kind wanted"),
]


@pytest.mark.parametrize("match", GAUGE_REFUSALS)
def test_a_source_of_another_kind_is_refused_before_it_is_built(
    isolated_registry: object, match: str
) -> None:
    registry.data_sources.register(AcmeGaugeSource)

    with pytest.raises(DataCapabilityError, match=match):
        source_from_section(SimpleNamespace(source="acme-gauge"))


def test_refusals() -> None:
    class PositionalSource:
        source_id = "acme-positional"

        def __init__(self, waterway_types, /):
            self.waterway_types = waterway_types

    # A section fills a parameter by name, so it cannot fill a positional-only one.
    with pytest.raises(DataRequestError, match="waterway_types"):
        registry.build_from_section(
            PositionalSource,
            HydrographySourceConfig(source="osm", waterway_types=["canal"]),
        )
    with pytest.raises(DataRequestError, match="acme-rivers"):
        source_from_section(SimpleNamespace(source="acme-rivers"))
