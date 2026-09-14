"""Shared helpers for SIM2-backed gridded variables."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord


@dataclass(frozen=True, slots=True)
class Sim2FieldSpec:
    """Describe one SIM2 field exposed as a HydroModPy variable."""

    parameter: str
    variable: str
    unit: str


@dataclass(frozen=True, slots=True)
class Sim2ComponentSpec:
    """Describe one component fetched from a SIM2 cube."""

    component: str
    parameter: str
    variable: str
    unit: str
    parameters: tuple[str, ...] | None = None
    scale: float = 1.0


def _date_range(project_period: tuple[datetime, datetime]) -> str:
    return f"{project_period[0].strftime('%Y-%m-%d')}/{project_period[1].strftime('%Y-%m-%d')}"


def _require_fetch_context(
    *,
    bbox: tuple[float, float, float, float] | None,
    project_period: tuple[datetime, datetime] | None,
) -> tuple[tuple[float, float, float, float], tuple[datetime, datetime]]:
    if bbox is None:
        raise ValueError("SIM2 source requires a bounding box (set extent or mask_path).")
    if project_period is None:
        raise ValueError("SIM2 source requires project_period (date_start/date_end).")
    return bbox, project_period


def _clean_field(data_array: object, variable: str) -> object:
    """Wrap one SIM2 data array as a clean (time, y, x) dataset named ``variable``."""
    da = data_array
    if getattr(da, "attrs", None) and "grid_mapping" in da.attrs:
        da = da.copy()
        da.attrs.pop("grid_mapping", None)
    out = da.to_dataset(name=variable)
    return out.drop_vars("spatial_ref", errors="ignore")


def _sim2_dataset_field(ds: object, parameter: str, variable: str) -> object:
    """Select one SIM2 parameter from a NetCDF dataset as a clean dataset."""
    return _clean_field(ds[parameter], variable)


def fetch_sim2_field(
    spec: Sim2FieldSpec,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch one SIM2 parameter as one FieldRecord."""
    bbox, project_period = _require_fetch_context(bbox=bbox, project_period=project_period)

    from hydromodpy.data.common.clients.sim2_edr import Sim2EDRClient

    # NetCDF4, not CoverageJSON: the EDR cube CoverageJSON lists axisNames
    # (y, x, t) that do not match its flat value ordering, which silently
    # scrambles time with space and destroys the seasonal cycle. The NetCDF
    # response carries the dimensions explicitly so xarray decodes it correctly.
    client = Sim2EDRClient(
        bbox=bbox,
        crs="EPSG:2154",
        date_range=_date_range(project_period),
        output_format="Netcdf4",
    )
    ds = client.fetch_cube(parameters=[spec.parameter])
    data = _sim2_dataset_field(ds, spec.parameter, spec.variable)

    return [
        FieldRecord(
            variable=spec.variable,
            source="sim2",
            unit=spec.unit,
            data=data,
            bbox=bbox,
            crs="EPSG:2154",
            date_start=project_period[0],
            date_end=project_period[1],
            frequency="D",
        )
    ]


def fetch_sim2_components(
    components: Iterable[str],
    *,
    specs: dict[str, Sim2ComponentSpec],
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
    transform: Callable[[str, object], object] | None = None,
) -> list[FieldRecord]:
    """Fetch selected SIM2 components as FieldRecords."""
    bbox, project_period = _require_fetch_context(bbox=bbox, project_period=project_period)
    selected = tuple(components)
    parameters = list(
        dict.fromkeys(
            parameter
            for component in selected
            for parameter in (specs[component].parameters or (specs[component].parameter,))
        )
    )

    from hydromodpy.data.common.clients.sim2_edr import Sim2EDRClient

    # NetCDF4, not CoverageJSON (see fetch_sim2_field for why).
    client = Sim2EDRClient(
        bbox=bbox,
        crs="EPSG:2154",
        date_range=_date_range(project_period),
        output_format="Netcdf4",
    )
    ds = client.fetch_cube(parameters=parameters)

    records: list[FieldRecord] = []
    for component in selected:
        spec = specs[component]
        data_array = ds[spec.parameter]
        if transform is not None:
            data_array = transform(component, ds)
        elif spec.scale != 1.0:
            data_array = data_array * spec.scale
        records.append(
            FieldRecord(
                variable=spec.variable,
                source="sim2",
                unit=spec.unit,
                data=_clean_field(data_array, spec.variable),
                bbox=bbox,
                crs="EPSG:2154",
                date_start=project_period[0],
                date_end=project_period[1],
                frequency="D",
            )
        )
    return records


__all__ = [
    "Sim2ComponentSpec",
    "Sim2FieldSpec",
    "fetch_sim2_components",
    "fetch_sim2_field",
]
