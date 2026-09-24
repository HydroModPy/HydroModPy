"""SIM2 EDR API adapter for precipitation data.

:class:`Sim2PrecipitationSource` puts ``fetch`` behind the data-source port. It
is the fourth payload
kind, ``fields``, and it is the biggest family of the census: nine of the
twenty-five fetch functions of this tree return ``list[FieldRecord]`` behind one
shared signature, ``fetch(config, *, bbox, project_period)``. Precipitation is
the one picked because it is the only one that folds two SIM2 parameters into a
third component -- ``total`` is ``PRELIQ_Q + PRENEI_Q`` -- so an adapter that
worked here works for the eight that do less.

Like the IGN source it is queried in **EPSG:2154**, and like the Hub'Eau one it
cannot be called without a window: ``variables/sim2.py`` raises
``SIM2 source requires project_period`` whatever the signature's default says.

Why it declares ``writes_out_dir = False`` while writing a file
---------------------------------------------------------------
``Sim2EDRClient._load_netcdf_from_bytes`` writes a temporary NetCDF on the fetch path, under
``$TMPDIR`` and not under the directory the request names. The declaration is
about ``request.out_dir`` and that answer is ``no``: this source leaves the
caller's directory exactly as it found it. What the temporary file belongs to is
the capability's own declaration of the places it writes outside its job
directory, D92, which is F5c's business and not the port's.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataCapabilityError
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_declared_variables,
    require_period,
    require_selectors,
)
from hydromodpy.data.variables.sim2 import Sim2ComponentSpec, fetch_sim2_components

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.data.variables.precipitation.config import PrecipitationSourceConfig

VARIABLE_NAME = "precipitation"
INTERNAL_UNIT = "mm/day"
_SPECS = {
    "liquid": Sim2ComponentSpec(
        component="liquid",
        parameter="PRELIQ_Q",
        variable="precipitation_liquid",
        unit=INTERNAL_UNIT,
    ),
    "solid": Sim2ComponentSpec(
        component="solid",
        parameter="PRENEI_Q",
        variable="precipitation_solid",
        unit=INTERNAL_UNIT,
    ),
    "total": Sim2ComponentSpec(
        component="total",
        parameter="PRELIQ_Q",
        parameters=("PRELIQ_Q", "PRENEI_Q"),
        variable="precipitation_total",
        unit=INTERNAL_UNIT,
    ),
}


def _transform_component(component: str, ds: object) -> object:
    if component == "total":
        return ds["PRELIQ_Q"] + ds["PRENEI_Q"]
    return ds[_SPECS[component].parameter]


def fetch(
    config: PrecipitationSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch precipitation from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as FieldRecord(s), one per component.
    """
    return fetch_sim2_components(
        config.components,
        specs=_SPECS,
        bbox=bbox,
        project_period=project_period,
        transform=_transform_component,
    )


COMPONENT_VARIABLE: dict[str, str] = {
    "liquid": "precipitation_liquid",
    "solid": "precipitation_solid",
    "total": "precipitation_total",
}
"""The three components the SIM2 precipitation adapter exposes, and their names.

Read off ``precipitation/apis/sim2.py:13-32``, where each ``Sim2ComponentSpec``
carries the variable its record is named after.
"""


class Sim2PrecipitationSource:
    """Daily SIM2 precipitation grids from the GeoSAS EDR service."""

    source_id: ClassVar[str] = "sim2-precipitation"
    payload_kind: ClassVar[PayloadKind] = "fields"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "required"
    hosts: ClassVar[tuple[str, ...]] = ("api.geosas.fr",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, components: tuple[str, ...] = ("total",)) -> None:
        if isinstance(components, str):
            raise DataCapabilityError(
                f"components={components!r} is a single string, which would be read one "
                "character per component. Pass a sequence."
            )
        chosen = tuple(components)
        unknown = sorted({name for name in chosen if name not in COMPONENT_VARIABLE})
        if unknown:
            raise DataCapabilityError(
                f"Source {self.source_id!r} does not serve components {unknown}; "
                f"it serves {sorted(COMPONENT_VARIABLE)}."
            )
        if not chosen:
            raise DataCapabilityError(
                f"Source {self.source_id!r} was built with no component, so it would "
                "fetch a cube and return nothing."
            )
        if len(set(chosen)) != len(chosen):
            raise DataCapabilityError(f"Components repeat: {chosen}.")
        self.components = chosen
        self.variables: tuple[str, ...] = tuple(COMPONENT_VARIABLE[name] for name in chosen)
        """The variables this instance emits, one per configured component."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch one field per configured component over the request's extent."""
        require_selectors(self, request)
        period = require_period(self, request)
        assert period is not None  # period_need == "required", checked just above
        extent = extent_for(self, request)
        from hydromodpy.data.variables.precipitation.config import PrecipitationSourceConfig

        config = PrecipitationSourceConfig(source="sim2", components=list(self.components))
        records = fetch(config, bbox=extent.bbox, project_period=period.as_tuple)
        require_declared_variables(self, [record.variable for record in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            fields=tuple(records),
            metadata={"components": self.components},
        )


__all__ = [
    "COMPONENT_VARIABLE",
    "INTERNAL_UNIT",
    "Sim2PrecipitationSource",
    "VARIABLE_NAME",
    "fetch",
]
