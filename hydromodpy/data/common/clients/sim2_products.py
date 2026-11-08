"""SIM2 (SAFRAN-ISBA) products read by HydroModPy variables, and their download.

One table, :data:`SIM2_PRODUCTS`, says for each variable backed by SIM2 which
EDR parameters it reads, the unit it is stored in, and the name of each record
it yields. A variable with components (precipitation, radiation) yields one
record per component; the others yield a single record.

:func:`fetch_sim2` downloads a product from the GeoSAS EDR service. It takes
plain values -- the variable, the components, a box in EPSG:2154 and a period
-- and never a variable config, so the managers and the data-source port call
it the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

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
    shipped_hosts,
)

if TYPE_CHECKING:
    from hydromodpy.data.contracts.spatial_field import FieldRecord

SIM2_CRS = "EPSG:2154"
"""The CRS of the SIM2 grid and of the box :func:`fetch_sim2` expects."""

_J_CM2_TO_MJ_M2 = 0.01
"""1 J/cm2 = 1e4 J/m2 = 0.01 MJ/m2."""


@dataclass(frozen=True, slots=True)
class Sim2Component:
    """One record of a SIM2 product: its name and how its values are built.

    The values are the sum of the listed ``parameters``, times ``scale``.
    """

    variable: str
    parameters: tuple[str, ...]
    scale: float = 1.0


@dataclass(frozen=True, slots=True)
class Sim2Product:
    """What one HydroModPy variable reads from SIM2."""

    unit: str
    components: dict[str, Sim2Component] = field(default_factory=dict)
    """Keyed by the value a ``components`` list in the TOML may name."""
    single: Sim2Component | None = None
    """The one record of a variable without components."""


def _single(variable: str, parameter: str, unit: str) -> Sim2Product:
    return Sim2Product(unit=unit, single=Sim2Component(variable, (parameter,)))


SIM2_PRODUCTS: dict[str, Sim2Product] = {
    "etp": _single("etp", "ETP_Q", "mm/day"),
    "humidity": _single("humidity", "HU_Q", "%"),
    "precipitation": Sim2Product(
        unit="mm/day",
        components={
            "liquid": Sim2Component("precipitation_liquid", ("PRELIQ_Q",)),
            "solid": Sim2Component("precipitation_solid", ("PRENEI_Q",)),
            "total": Sim2Component("precipitation_total", ("PRELIQ_Q", "PRENEI_Q")),
        },
    ),
    "radiation": Sim2Product(
        unit="MJ/m2/j",
        components={
            "atmospheric": Sim2Component(
                "radiation_atmospheric", ("DLI_Q",), scale=_J_CM2_TO_MJ_M2
            ),
            "visible": Sim2Component("radiation_visible", ("SSI_Q",), scale=_J_CM2_TO_MJ_M2),
        },
    ),
    "recharge": _single("recharge", "DRAINC_Q", "mm/day"),
    "runoff": _single("runoff", "RUNC_Q", "mm/day"),
    "soil_moisture": _single("soil_moisture_index", "SWI_Q", "%"),
    "temperature": _single("temperature", "T_Q", "degC"),
    "wind": _single("wind", "FF_Q", "m/s"),
}
"""The nine variables backed by SIM2, keyed by their ``[data.<name>]`` section."""


def _date_range(project_period: tuple[datetime, datetime]) -> str:
    return f"{project_period[0].strftime('%Y-%m-%d')}/{project_period[1].strftime('%Y-%m-%d')}"


def _clean_field(data_array: object, variable: str) -> object:
    """Wrap one SIM2 data array as a clean (time, y, x) dataset named ``variable``."""
    da = data_array
    if getattr(da, "attrs", None) and "grid_mapping" in da.attrs:
        da = da.copy()
        da.attrs.pop("grid_mapping", None)
    out = da.to_dataset(name=variable)
    return out.drop_vars("spatial_ref", errors="ignore")


def _selected(product: Sim2Product, variable: str, components: Sequence[str] | None) -> list:
    if product.single is not None:
        return [product.single]
    if not components:
        raise ValueError(f"SIM2 {variable} needs at least one component.")
    unknown = sorted(set(components) - set(product.components))
    if unknown:
        raise ValueError(
            f"SIM2 {variable} has no component {unknown}; it has {sorted(product.components)}."
        )
    return [product.components[name] for name in components]


def fetch_sim2(
    variable: str,
    *,
    components: Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Download one SIM2 product over ``bbox`` (EPSG:2154) and ``project_period``.

    Returns one record per selected component, or the single record of a
    variable without components. ``components`` is ignored for the latter.
    """
    if bbox is None:
        raise ValueError("SIM2 source requires a bounding box (set extent or mask_path).")
    if project_period is None:
        raise ValueError("SIM2 source requires project_period (date_start/date_end).")
    product = SIM2_PRODUCTS[variable]
    selected = _selected(product, variable, components)
    parameters = list(dict.fromkeys(p for member in selected for p in member.parameters))

    from hydromodpy.data.common.clients.sim2_edr import Sim2EDRClient
    from hydromodpy.data.contracts.spatial_field import FieldRecord

    # NetCDF4, not CoverageJSON: the EDR cube CoverageJSON lists axisNames
    # (y, x, t) that do not match its flat value ordering, which silently
    # scrambles time with space and destroys the seasonal cycle. The NetCDF
    # response carries the dimensions explicitly so xarray decodes it correctly.
    client = Sim2EDRClient(
        bbox=bbox,
        crs=SIM2_CRS,
        date_range=_date_range(project_period),
        output_format="Netcdf4",
    )
    ds = client.fetch_cube(parameters=parameters)

    records: list[FieldRecord] = []
    for member in selected:
        data_array = ds[member.parameters[0]]
        for parameter in member.parameters[1:]:
            data_array = data_array + ds[parameter]
        if member.scale != 1.0:
            data_array = data_array * member.scale
        records.append(
            FieldRecord(
                variable=member.variable,
                source="sim2",
                unit=product.unit,
                data=_clean_field(data_array, member.variable),
                bbox=bbox,
                crs=SIM2_CRS,
                date_start=project_period[0],
                date_end=project_period[1],
                frequency="D",
            )
        )
    return records


class Sim2Source:
    """Base DataSource for gridded products from SIM2 (SAFRAN-ISBA)."""

    source_id: ClassVar[str] = "sim2"
    payload_kind: ClassVar[PayloadKind] = "fields"
    extent_crs: ClassVar[str] = SIM2_CRS
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "required"
    writes_out_dir: ClassVar[bool] = False
    section: ClassVar[str] = ""

    variables: tuple[str, ...]
    hosts: tuple[str, ...]

    def __init__(
        self,
        *,
        components: Sequence[str] | None = None,
        section: str | None = None,
    ) -> None:
        if section is not None:
            self.section = section
        self.components = tuple(components) if components is not None else None
        self.product = SIM2_PRODUCTS[self.section]
        if self.components is not None:
            self.variables = tuple(
                member.variable for member in _selected(self.product, self.section, self.components)
            )
        elif self.product.single is not None:
            self.variables = (self.product.single.variable,)
        else:
            self.variables = tuple(member.variable for member in self.product.components.values())
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request)
        records = fetch_sim2(
            self.section,
            components=self.components,
            bbox=extent.bbox,
            project_period=period.as_tuple if period is not None else None,
        )
        require_declared_variables(self, [r.variable for r in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            fields=tuple(records),
        )


class Sim2Precipitation(Sim2Source):
    section: ClassVar[str] = "precipitation"


class Sim2Etp(Sim2Source):
    section: ClassVar[str] = "etp"


class Sim2Temperature(Sim2Source):
    section: ClassVar[str] = "temperature"


class Sim2Wind(Sim2Source):
    section: ClassVar[str] = "wind"


class Sim2Humidity(Sim2Source):
    section: ClassVar[str] = "humidity"


class Sim2Radiation(Sim2Source):
    section: ClassVar[str] = "radiation"


class Sim2SoilMoisture(Sim2Source):
    section: ClassVar[str] = "soil_moisture"


class Sim2Runoff(Sim2Source):
    section: ClassVar[str] = "runoff"


class Sim2Recharge(Sim2Source):
    section: ClassVar[str] = "recharge"


__all__ = [
    "SIM2_CRS",
    "SIM2_PRODUCTS",
    "Sim2Component",
    "Sim2Etp",
    "Sim2Humidity",
    "Sim2Precipitation",
    "Sim2Product",
    "Sim2Radiation",
    "Sim2Recharge",
    "Sim2Runoff",
    "Sim2SoilMoisture",
    "Sim2Source",
    "Sim2Temperature",
    "Sim2Wind",
    "fetch_sim2",
]
