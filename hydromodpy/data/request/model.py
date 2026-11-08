"""``DataRequest``: data asked for from outside a project, as one JSON document.

A program with no project and no TOML -- a Docker container, a web service, a
GIS tool -- asks for ``[data]`` sections over an extent and a period. The
sections are the models of the TOML itself, so what works in a project works
in a request. The extent is exactly one of three things: a box with its CRS, a
vector mask (a basin polygon, for instance), or a list of
stations. ``installed`` asks a plugin source by its name.

The mask is a file link, the shape every job input takes: ``href``, an optional
media type and an optional ``sha256`` that pins its bytes. A chain fills it
from the watershed of an earlier step by linking the member ``extent.mask``.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.schema.job.request import FileLink

CRS_PATTERN = r"^EPSG:[0-9]{4,6}$"
"""How an extent names its CRS: an EPSG code, refused early rather than guessed."""

MAX_STATIONS = 1_000
"""Declared because a published schema needs a number."""

MAX_INSTALLED = 16
"""How many plugin sources one request asks, declared for the same reason."""


class RequestExtent(HydroModelBase):
    """Where the data is asked for: a box with its CRS, a mask, or stations."""

    bbox: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="xmin, ymin, xmax, ymax, in the units of crs",
        examples=[[320000.0, 6780000.0, 360000.0, 6810000.0]],
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        pattern=CRS_PATTERN,
        description="CRS the four bounds of bbox are expressed in",
        examples=["EPSG:2154"],
    )
    mask: Annotated[FileLink | None, Profile.USER] = Field(
        default=None,
        description="vector file whose shape bounds the request, typically a watershed",
    )
    station_ids: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        max_length=MAX_STATIONS,
        description="station codes to fetch, for the variables that select by station",
    )

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> RequestExtent:
        if (self.bbox is None) != (self.crs is None):
            raise ValueError("bbox and crs go together: give both or neither")
        chosen = [
            name
            for name, given in (
                ("bbox", self.bbox is not None),
                ("mask", self.mask is not None),
                ("station_ids", bool(self.station_ids)),
            )
            if given
        ]
        if len(chosen) != 1:
            raise ValueError(
                "the extent is exactly one of bbox (with crs), mask or station_ids; "
                f"this one gives {chosen or 'none'}"
            )
        if self.bbox is not None:
            xmin, ymin, xmax, ymax = self.bbox
            if xmin >= xmax or ymin >= ymax:
                raise ValueError(
                    f"bbox ({xmin}, {ymin}, {xmax}, {ymax}) is empty or inverted; "
                    "expected xmin < xmax and ymin < ymax"
                )
        repeated = sorted({code for code in self.station_ids if self.station_ids.count(code) > 1})
        if repeated:
            raise ValueError(f"station_ids repeat {repeated}")
        return self


class RequestPeriod(HydroModelBase):
    """The closed time window asked for, both ends included."""

    start: Annotated[datetime, Profile.USER] = Field(
        description="first instant of the window, inclusive",
        examples=["2010-01-01"],
    )
    end: Annotated[datetime, Profile.USER] = Field(
        description=(
            "last instant of the window, inclusive; a date without a time keeps its whole day"
        ),
        examples=["2020-12-31"],
    )

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> RequestPeriod:
        if self.end < self.start:
            raise ValueError(f"period ends ({self.end}) before it starts ({self.start})")
        return self


def _data_sections() -> tuple[str, ...]:
    """Every ``[data.<name>]`` section, the variables the loader dispatches on."""
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS

    return tuple(VARIABLE_SPECS)


def _shipped_source_ids(data_sources: object, sections: tuple[str, ...]) -> set[str]:
    """The source ids this build ships, read off the joined keys it declares.

    A key is ``<section>_<source_id>`` and is compared against the known
    sections, never split on ``_``: a section is not the prefix of another
    followed by ``_``, which is what the registry's own gate holds, so the id
    cut behind the matching section is the one and only id the key declares.
    """
    ids: set[str] = set()
    joined = tuple(data_sources.names(shipped_only=True))  # type: ignore[attr-defined]
    for key in joined:
        for section in sections:
            if key.startswith(f"{section}_"):
                ids.add(key[len(section) + 1 :])
    return ids


class InstalledSource(HydroModelBase):
    """A source a plugin installed beside this build, asked by its name."""

    name: Annotated[str, Profile.USER] = Field(
        min_length=1,
        description=(
            "source id this installation resolves, registered on the "
            "'hydromodpy.data.source' entry-point group"
        ),
        examples=["acme-radar"],
    )
    options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "keyword arguments handed to that source's constructor, bound against "
            "its signature before anything runs"
        ),
    )

    @model_validator(mode="after")
    def _refuse_what_this_installation_cannot_answer(self) -> InstalledSource:
        """Refuse a shipped id, an unresolvable one, and options it cannot take.

        A source is registered under its section and its source id, and this
        member asks by the id alone, so two plugin sections that both serve one
        id are an ambiguity the resolution refuses by naming the keys. A shipped
        source is asked for through its ``[data]`` section, which describes its
        shape. The options are bound against the constructor's signature: a
        misspelled or missing one is refused by name, a wrong type is the
        source's to refuse.
        """
        from hydromodpy.data.source import registry

        if self.name in _shipped_source_ids(registry.data_sources, _data_sections()):
            raise ValueError(
                f"{self.name!r} is a source this build ships; ask for it through its "
                "[data] section, which describes its options"
            )
        try:
            source_cls = registry.installed_source_cls(self.name)
        except DataRequestError as exc:
            raise ValueError(str(exc)) from exc
        try:
            inspect.signature(source_cls).bind(**self.options)
        except TypeError as exc:
            raise ValueError(
                f"source {self.name!r} cannot be built from these options: {exc}"
            ) from exc
        return self


class DataRequest(HydroModelBase):
    """``[data]`` sections, an extent and a period, asked for from outside."""

    data: Annotated[DataManagersConfig, Profile.USER] = Field(
        default_factory=DataManagersConfig,
        description="the [data] sections to fetch, with the models of the TOML",
    )
    extent: Annotated[RequestExtent, Profile.USER] = Field(
        description="exactly one of a box with its CRS, a mask, or stations",
    )
    period: Annotated[RequestPeriod | None, Profile.USER] = Field(
        default=None,
        description="time window, for the variables that have a time axis",
    )
    installed: Annotated[list[InstalledSource], Profile.USER] = Field(
        default_factory=list,
        max_length=MAX_INSTALLED,
        description="plugin sources asked by name, beside the [data] sections",
    )

    @model_validator(mode="after")
    def _asks_for_something(self) -> DataRequest:
        if not self.sections() and not self.installed:
            raise ValueError("the request names no [data] section and no installed source")
        return self

    @classmethod
    def for_variable(
        cls,
        variable: str,
        *,
        source: str | None = None,
        bbox: Sequence[float] | None = None,
        crs: str | None = None,
        mask: str | Path | None = None,
        station_ids: Sequence[str] | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> DataRequest:
        """The request for one variable and one source, as ``hmp data get <variable>`` builds it.

        Without ``source``, the variable's one downloading source is used; a
        variable with several must name one.
        """
        from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
        from hydromodpy.data.source import registry
        from hydromodpy.schema.sources import SOURCES as SOURCE_REGISTRY

        if variable not in VARIABLE_SPECS:
            raise ValueError(f"Unknown variable {variable!r}; known: {sorted(VARIABLE_SPECS)}")
        if source is None:
            sources = list(registry.data_sources.names(variable, shipped_only=True))
            # A source read or built locally (explore2, synthetic, constant) needs
            # more than a variable name, so only the downloading ones are candidates.
            served = [name for name in sources if SOURCE_REGISTRY[name].hosts] or sources
            if len(served) != 1:
                raise ValueError(f"{variable!r} is served by {served}; name one with source")
            source = served[0]
        extent: dict[str, Any] = {}
        if bbox is not None:
            extent = {"bbox": list(bbox), "crs": crs}
        elif mask is not None:
            extent = {"mask": {"href": str(mask)}}
        elif station_ids:
            extent = {"station_ids": list(station_ids)}
        payload: dict[str, Any] = {
            "data": {variable: {"sources": [{"source": source}]}},
            "extent": extent,
        }
        if start is not None or end is not None:
            payload["period"] = {"start": start, "end": end}
        return cls.model_validate(payload)

    def sections(self) -> dict[str, Any]:
        """The ``[data]`` sections this request carries, keyed by variable."""
        from hydromodpy.data.loading._dispatch import VARIABLE_SPECS

        return {
            name: section
            for name in VARIABLE_SPECS
            if (section := getattr(self.data, name, None)) is not None
        }


__all__ = [
    "CRS_PATTERN",
    "MAX_INSTALLED",
    "MAX_STATIONS",
    "DataRequest",
    "InstalledSource",
    "RequestExtent",
    "RequestPeriod",
]
