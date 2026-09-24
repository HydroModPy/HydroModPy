"""``DataRequest``: data asked for from outside a project, as one JSON document.

A program with no project and no TOML -- a Docker container, a web service, a
GIS tool -- asks for ``[data]`` sections over an extent and a period. The
sections are the models of the TOML itself, so what works in a project works
in a request. The extent is exactly one of three things: a box with its CRS, a
vector mask (a basin ``terrain-delineate`` sealed, for instance), or a list of
stations. ``installed`` asks a plugin source by its name.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.data.loading.config_schema import DataManagersConfig

CRS_PATTERN = r"^EPSG:[0-9]{4,6}$"
"""How an extent names its CRS: an EPSG code, refused early rather than guessed."""

MAX_STATIONS = 1_000
"""Declared because a published schema needs a number."""


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
    mask: Annotated[str | None, Profile.USER] = Field(
        default=None,
        min_length=1,
        description=(
            "vector file whose shape bounds the request, typically a watershed "
            "sealed by terrain-delineate"
        ),
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
        description="keyword arguments handed to that source's constructor",
    )


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
        from hydromodpy.data.loading._dispatch import VARIABLE_SPECS, get_manager_class

        if variable not in VARIABLE_SPECS:
            raise ValueError(f"Unknown variable {variable!r}; known: {sorted(VARIABLE_SPECS)}")
        if source is None:
            served = sorted(get_manager_class(variable).SOURCES)
            if len(served) != 1:
                raise ValueError(f"{variable!r} is served by {served}; name one with source")
            source = served[0]
        extent: dict[str, Any] = {}
        if bbox is not None:
            extent = {"bbox": list(bbox), "crs": crs}
        elif mask is not None:
            extent = {"mask": str(mask)}
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
    "MAX_STATIONS",
    "DataRequest",
    "InstalledSource",
    "RequestExtent",
    "RequestPeriod",
]
