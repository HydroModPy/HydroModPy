"""Observable extraction: time/spatial selection, normalization, CSV export."""

from __future__ import annotations

import csv
import numbers
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.analysis.comparison.config import (
    MethodComparisonObservable,
    MethodComparisonVariant,
)
from hydromodpy.analysis.comparison.runtime_mesh import (
    CellCentroidTable,
    resolve_bundle_cells,
)
from hydromodpy.analysis.comparison.runtime_physics import (
    _NODATA_SENTINELS,
    _convert_accumulation_rate_to_m3_s,
    _convert_flux_m3_s_to_depth_m_per_day,
    _convert_rate_m_s_to_m_per_day,
    _is_canonical_outlet_flux,
    _native_unit_for_variable,
    is_nodata_value,
)
from hydromodpy.analysis.comparison.runtime_series import (
    TimeSlice,
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog


def _area_for_series_value(
    *,
    series: VariableSeries,
    cells: CellCentroidTable | None,
    value_index: int,
) -> float | None:
    """Return the cell area associated with one extracted scalar value."""
    if cells is None:
        return None
    if series.cell_ids is not None and value_index < int(series.cell_ids.size):
        return cells.area_for_cell_id(int(series.cell_ids[int(value_index)]))
    if cells.area_m2 is None or value_index >= int(cells.cell_ids.size):
        return None
    area = float(cells.area_m2[int(value_index)])
    if not np.isfinite(area) or area <= 0.0:
        return None
    return area


def _cell_id_for_series_value(
    *,
    series: VariableSeries,
    cells: CellCentroidTable | None,
    value_index: int,
    details: Mapping[str, Any],
) -> int | None:
    selected_cell_raw = details.get("selected_cell_index")
    if selected_cell_raw not in ("", None):
        try:
            return int(selected_cell_raw)
        except Exception:
            return None
    if series.cell_ids is not None and value_index < int(series.cell_ids.size):
        return int(series.cell_ids[int(value_index)])
    if cells is not None and value_index < int(cells.cell_ids.size):
        return int(cells.cell_ids[int(value_index)])
    return None


def _vertical_bounds_for_series_value(
    *,
    series: VariableSeries,
    cells: CellCentroidTable | None,
    value_index: int,
    details: Mapping[str, Any],
) -> tuple[float | str, float | str]:
    if cells is None:
        return "", ""
    cell_id = _cell_id_for_series_value(
        series=series,
        cells=cells,
        value_index=value_index,
        details=details,
    )
    if cell_id is None:
        return "", ""
    bounds = cells.vertical_bounds_for_cell_id(cell_id)
    if bounds is None:
        return "", ""
    top, bottom = bounds
    return top, bottom


def normalize_observable_value(
    *,
    observable: MethodComparisonObservable,
    series: VariableSeries,
    value: float,
    value_index: int,
    details: Mapping[str, Any],
    cells: CellCentroidTable | None,
) -> dict[str, Any]:
    """Normalize one selected observable value and its output metadata."""
    native_unit = _native_unit_for_variable(series.variable_name)
    output_value = float(value)
    derived_from_variable = series.variable_name
    conversion_applied = ""
    cell_area_m2: float | str = ""

    if _is_canonical_outlet_flux(observable.variable):
        native_unit = "m3/s"
        if series.variable_name == "accumulation_flux":
            selected_cell_raw = details.get("selected_cell_index")
            if selected_cell_raw in ("", None):
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    "canonical outlet_flux from accumulation_flux "
                    "without an explicit outlet cell selection."
                )
            if cells is None:
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    "canonical outlet_flux without mesh bundle areas."
                )
            area_m2 = cells.area_for_cell_id(int(selected_cell_raw))
            if area_m2 is None:
                raise ValueError(
                    f"Observable '{observable.name}' cannot derive "
                    f"canonical outlet_flux because area_m2 is missing "
                    f"for cell {selected_cell_raw}."
                )
            output_value = _convert_accumulation_rate_to_m3_s(
                value_m_per_day=output_value,
                cell_area_m2=area_m2,
            )
            conversion_applied = "accumulation_flux_m_per_day_to_m3_s"
            cell_area_m2 = area_m2
        elif native_unit == "":
            native_unit = "m3/s"
    elif observable.variable.strip().lower() == "outflow_drain" and series.variable_name in {
        "drainage_flux_history_m3_s",
        "drainage_flux_m3_s",
    }:
        area_m2 = _area_for_series_value(
            series=series,
            cells=cells,
            value_index=value_index,
        )
        if area_m2 is None:
            raise ValueError(
                f"Observable '{observable.name}' cannot derive outflow_drain "
                "from drainage_flux without cell areas."
            )
        output_value = _convert_flux_m3_s_to_depth_m_per_day(
            value_m3_s=output_value,
            cell_area_m2=area_m2,
        )
        native_unit = "m3/s"
        conversion_applied = "drainage_flux_m3_s_to_m_per_day"
        cell_area_m2 = area_m2
    elif (
        observable.variable.strip().lower()
        in {
            "surface_excess_rate",
            "surface_excess_map",
        }
        and series.variable_name == "saturation_excess_history_m_s"
    ):
        output_value = _convert_rate_m_s_to_m_per_day(value_m_s=output_value)
        native_unit = "m/s"
        conversion_applied = "surface_excess_m_s_to_m_per_day"

    return {
        "value": output_value,
        "unit": observable.unit or native_unit,
        "native_unit": native_unit,
        "derived_from_variable": derived_from_variable,
        "conversion_applied": conversion_applied,
        "cell_area_m2": cell_area_m2,
    }


def _select_time_slices(
    series: VariableSeries,
    observable: MethodComparisonObservable,
) -> tuple[TimeSlice, ...]:
    """Select time slices requested by one observable."""
    if observable.time_window is not None:
        start, end = observable.time_window
        if isinstance(start, numbers.Real) and isinstance(end, numbers.Real):
            selected = [
                item
                for item in series.slices
                if item.elapsed_seconds is not None
                and float(start) <= float(item.elapsed_seconds) <= float(end)
            ]
        else:
            selected = [
                item for item in series.slices if str(start) <= str(item.time_key) <= str(end)
            ]
        return tuple(selected or series.slices)

    time_selector = observable.time
    if time_selector is None or str(time_selector).strip().lower() == "all":
        return series.slices
    selector_text = str(time_selector).strip().lower()
    if selector_text == "last":
        return (series.slices[-1],)
    if selector_text == "first":
        return (series.slices[0],)

    for item in series.slices:
        if str(item.time_key) == str(time_selector):
            return (item,)
    if isinstance(time_selector, numbers.Integral):
        index = int(time_selector)
        if -len(series.slices) <= index < len(series.slices):
            return (series.slices[index],)
    raise KeyError(
        f"Time selector {time_selector!r} not found for variable '{series.variable_name}'"
    )


def select_time_slices(
    series: VariableSeries,
    observable: MethodComparisonObservable,
) -> tuple[TimeSlice, ...]:
    """Public wrapper exposing observable time selection for reuse."""
    return _select_time_slices(series, observable)


def _reduce(values: Any, *, reducer: str | None, label: str) -> tuple[float, ...]:
    """Reduce one numeric sequence."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size > 0:
        for sentinel in _NODATA_SENTINELS:
            arr[np.isclose(arr, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    reducer_key = "identity" if reducer is None else str(reducer).strip().lower()
    if reducer_key in {"identity", "all", "none"}:
        return tuple(float(value) for value in arr)
    if reducer_key == "sum":
        return (float(np.nansum(arr)),)
    if reducer_key == "mean":
        return (float(np.nanmean(arr)),)
    if reducer_key == "min":
        return (float(np.nanmin(arr)),)
    if reducer_key == "max":
        return (float(np.nanmax(arr)),)
    if reducer_key == "absmax":
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return (float("nan"),)
        return (float(finite[int(np.argmax(np.abs(finite)))]),)
    if reducer_key == "first":
        return (float(arr[0]),)
    if reducer_key == "last":
        return (float(arr[-1]),)
    if reducer_key == "nearest_cell":
        if arr.size != 1:
            raise ValueError("nearest_cell reducer expects one selected cell value")
        return (float(arr[0]),)
    raise ValueError(f"Unsupported reducer '{reducer}' for {label}")


def _cell_position_for_cell_id(
    series: VariableSeries,
    *,
    cell_id: int,
) -> int:
    if series.cell_ids is not None:
        matches = np.flatnonzero(series.cell_ids == int(cell_id))
        if matches.size == 0:
            raise IndexError(f"cell_id {cell_id} is absent from {series.source_path}")
        return int(matches[0])
    return int(cell_id)


def _select_cell_values(
    *,
    series: VariableSeries,
    values: np.ndarray,
    cell_ids: list[int],
) -> np.ndarray:
    positions = [_cell_position_for_cell_id(series, cell_id=cell_id) for cell_id in cell_ids]
    if any(position >= values.size for position in positions):
        raise IndexError(
            f"cell index outside variable '{series.variable_name}' values (size={values.size})"
        )
    return values[np.asarray(positions, dtype=int)]


def _select_spatial_values(
    *,
    series: VariableSeries,
    time_slice: TimeSlice,
    observable: MethodComparisonObservable,
    cells: CellCentroidTable | None,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    """Apply spatial selection for one observable/time slice."""
    values = np.asarray(time_slice.values, dtype=float).ravel()
    details: dict[str, Any] = {}

    if observable.support == "point":
        if observable.cell_index is not None:
            selected_cell_id = int(observable.cell_index)
        elif cells is not None and observable.x is not None and observable.y is not None:
            selected_cell_id = cells.nearest_cell_id(x=observable.x, y=observable.y)
        elif values.size == 1:
            return (float(values[0]),), {"selection": "scalar"}
        else:
            raise ValueError(
                f"Point observable '{observable.name}' needs a mesh bundle cells.csv "
                "for x/y lookup, or a cell_index."
            )
        selected = _select_cell_values(
            series=series,
            values=values,
            cell_ids=[selected_cell_id],
        )
        details["selected_cell_index"] = selected_cell_id
        details["selection"] = "nearest_cell"
        return _reduce(selected, reducer="nearest_cell", label=observable.name), details

    if observable.support == "outlet":
        if observable.cell_index is not None:
            selected_cell_ids = [int(observable.cell_index)]
            details["selection"] = "declared_cell"
        elif observable.x is not None and observable.y is not None and cells is not None:
            selected_cell_ids = [cells.nearest_cell_id(x=observable.x, y=observable.y)]
            details["selection"] = "nearest_declared_outlet_point"
        else:
            if not observable.allow_domain_proxy and values.size > 1:
                raise ValueError(
                    f"Outlet observable '{observable.name}' needs cell_index or x/y "
                    "coordinates for a strict outlet extraction."
                )
            selected_cell_ids = []
            details["selection"] = (
                "domain_reducer_proxy" if values.size > 1 else "scalar_outlet_series"
            )
        if values.size == 1 and series.cell_ids is None:
            if selected_cell_ids:
                details["selected_cell_index"] = selected_cell_ids[0]
            details["selection"] = "native_outlet_series"
            return (float(values[0]),), details
        if selected_cell_ids:
            selected = _select_cell_values(
                series=series,
                values=values,
                cell_ids=selected_cell_ids,
            )
            details["selected_cell_index"] = selected_cell_ids[0]
        else:
            selected = values
        return _reduce(selected, reducer=observable.reducer, label=observable.name), details

    if observable.support in {"boundary", "cell_mask"}:
        if observable.cell_indices:
            selected = _select_cell_values(
                series=series,
                values=values,
                cell_ids=[int(item) for item in observable.cell_indices],
            )
            details["selected_cell_indices"] = ",".join(
                str(item) for item in observable.cell_indices
            )
            details["selection"] = "declared_cell_indices"
        else:
            selected = values
            details["selection"] = "domain_reducer_proxy"
        return _reduce(selected, reducer=observable.reducer, label=observable.name), details

    if observable.support == "map":
        details["selection"] = "map"
        return _reduce(values, reducer=observable.reducer, label=observable.name), details

    raise KeyError(f"Unsupported observable support: {observable.support}")


def _time_match_key(time_slice: TimeSlice) -> str:
    """Return a stable key used to align rows across variants."""
    if str(time_slice.time_key) == "reduced":
        return "reduced"
    if time_slice.elapsed_seconds is not None and np.isfinite(time_slice.elapsed_seconds):
        return f"elapsed_seconds:{time_slice.elapsed_seconds:.9g}"
    return f"time_index:{time_slice.time_index}"


def _fallback_time_key(
    *,
    observable: MethodComparisonObservable,
    time_slice: TimeSlice,
    selection_time_order: int,
    non_initial_time_order: int | None,
) -> str:
    """Return a semantic fallback key used when raw time keys differ across variants."""
    reducer_key = str(observable.time_reducer or "").strip().lower()
    if reducer_key:
        return f"time_reducer:{reducer_key}"

    selector_key = str(observable.time or "all").strip().lower()
    if selector_key in {"last", "first"}:
        return f"time_selector:{selector_key}"

    if observable.time_window is not None:
        if time_slice.is_initial_state:
            return "initial_state"
        if non_initial_time_order is not None:
            return f"time_window_non_initial_order:{non_initial_time_order}"
        return f"time_window_selection_order:{selection_time_order}"

    if selector_key in {"", "all"}:
        if time_slice.is_initial_state:
            return "initial_state"
        if non_initial_time_order is not None:
            return f"non_initial_order:{non_initial_time_order}"
        return f"selection_order:{selection_time_order}"

    return f"requested_time:{selector_key}"


def extract_observable_rows(
    *,
    comparison_id: str,
    variant: MethodComparisonVariant,
    run_folder: Path,
    observables: tuple[MethodComparisonObservable, ...],
    config_path: Path | None = None,
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract all observable rows for one completed/reused variant."""
    rows: list[dict[str, Any]] = []
    cells: CellCentroidTable | None = None
    for observable in observables:
        if observable.variants is not None and variant.id not in set(observable.variants):
            continue
        series = load_variable_series(
            run_folder=run_folder,
            variable=observable.variable,
            store=store,
            sim_id=sim_id,
        )
        series = mask_depth_series_from_head_nodata(
            run_folder=run_folder,
            series=series,
            store=store,
            sim_id=sim_id,
        )
        if cells is None:
            first_slice_size = int(series.slices[0].values.size) if series.slices else None
            cells = resolve_bundle_cells(
                run_folder,
                config_path=config_path,
                expected_size=(
                    None if first_slice_size is None or first_slice_size <= 1 else first_slice_size
                ),
                solver_name=variant.solver,
            )
        selected_slices = _select_time_slices(series, observable)

        per_time_values: list[tuple[TimeSlice, tuple[float, ...], dict[str, Any]]] = []
        for time_slice in selected_slices:
            values, details = _select_spatial_values(
                series=series,
                time_slice=time_slice,
                observable=observable,
                cells=cells,
            )
            per_time_values.append((time_slice, values, details))

        if observable.time_reducer is not None:
            flat = [value for _, values, _ in per_time_values for value in values]
            reducer_key = str(observable.time_reducer).strip().lower()
            reduced_values = _reduce(
                flat,
                reducer=observable.time_reducer,
                label=f"{observable.name} time series",
            )
            if reducer_key == "last":
                reduced_details = dict(per_time_values[-1][2])
            elif reducer_key == "first":
                reduced_details = dict(per_time_values[0][2])
            else:
                reduced_details = dict(per_time_values[-1][2])
            reduced_details["time_reducer"] = observable.time_reducer
            reduced_slice = TimeSlice(
                time_key="reduced",
                time_index=-1,
                values=np.asarray(reduced_values, dtype=float),
            )
            per_time_values = [(reduced_slice, reduced_values, reduced_details)]

        non_initial_counter = 0
        for selection_time_order, (time_slice, values, details) in enumerate(per_time_values):
            non_initial_time_order: int | None
            if time_slice.is_initial_state:
                non_initial_time_order = None
            else:
                non_initial_time_order = non_initial_counter
                non_initial_counter += 1
            fallback_time_key = _fallback_time_key(
                observable=observable,
                time_slice=time_slice,
                selection_time_order=selection_time_order,
                non_initial_time_order=non_initial_time_order,
            )
            for value_index, value in enumerate(values):
                normalized = normalize_observable_value(
                    observable=observable,
                    series=series,
                    value=float(value),
                    value_index=value_index,
                    details=details,
                    cells=cells,
                )
                surface_top_m, surface_bottom_m = _vertical_bounds_for_series_value(
                    series=series,
                    cells=cells,
                    value_index=value_index,
                    details=details,
                )
                is_nodata = is_nodata_value(normalized["value"])
                rows.append(
                    {
                        "comparison_id": comparison_id,
                        "variant_id": variant.id,
                        "variant_label": variant.label or variant.id,
                        "solver": variant.solver or "",
                        "mesh_label": variant.mesh_label or "",
                        "mesh_mode": variant.mesh_mode,
                        "observable": observable.name,
                        "variable": observable.variable,
                        "resolved_variable": series.variable_name,
                        "support": observable.support,
                        "time": str(time_slice.time_key),
                        "time_index": time_slice.time_index,
                        "elapsed_seconds": (
                            ""
                            if time_slice.elapsed_seconds is None
                            else float(time_slice.elapsed_seconds)
                        ),
                        "requested_time": (
                            "all" if observable.time is None else str(observable.time)
                        ),
                        "requested_time_reducer": (
                            "" if observable.time_reducer is None else str(observable.time_reducer)
                        ),
                        "selection_time_order": selection_time_order,
                        "non_initial_time_order": (
                            "" if non_initial_time_order is None else non_initial_time_order
                        ),
                        "is_initial_state": bool(time_slice.is_initial_state),
                        "comparison_time_key": _time_match_key(time_slice),
                        "match_fallback_key": fallback_time_key,
                        "value_index": value_index,
                        "value": normalized["value"],
                        "is_nodata": is_nodata,
                        "unit": normalized["unit"],
                        "configured_unit": observable.unit or "",
                        "native_unit": normalized["native_unit"],
                        "derived_from_variable": normalized["derived_from_variable"],
                        "conversion_applied": normalized["conversion_applied"],
                        "cell_area_m2": normalized["cell_area_m2"],
                        "surface_top_m": surface_top_m,
                        "surface_bottom_m": surface_bottom_m,
                        "source_path": str(series.source_path),
                        "run_folder": str(run_folder),
                        "selection": str(details.get("selection", "")),
                        "allow_domain_proxy": bool(observable.allow_domain_proxy),
                        "selected_cell_index": str(details.get("selected_cell_index", "")),
                        "selected_cell_indices": str(details.get("selected_cell_indices", "")),
                    }
                )
    return rows


def write_observables_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist long-format comparison observables."""
    fieldnames = [
        "comparison_id",
        "variant_id",
        "variant_label",
        "solver",
        "mesh_label",
        "mesh_mode",
        "observable",
        "variable",
        "resolved_variable",
        "support",
        "time",
        "time_index",
        "elapsed_seconds",
        "requested_time",
        "requested_time_reducer",
        "selection_time_order",
        "non_initial_time_order",
        "is_initial_state",
        "comparison_time_key",
        "match_fallback_key",
        "value_index",
        "value",
        "is_nodata",
        "unit",
        "configured_unit",
        "native_unit",
        "derived_from_variable",
        "conversion_applied",
        "cell_area_m2",
        "surface_top_m",
        "surface_bottom_m",
        "source_path",
        "run_folder",
        "selection",
        "allow_domain_proxy",
        "selected_cell_index",
        "selected_cell_indices",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


__all__ = (
    "extract_observable_rows",
    "normalize_observable_value",
    "select_time_slices",
    "write_observables_csv",
)
