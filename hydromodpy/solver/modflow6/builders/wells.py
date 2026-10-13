"""MF6 well stress-period data builder."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Any

import numpy as np

from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells


def well_cell_to_disv(*, ncol: int, lay: int, row: int, col: int) -> tuple[int, int]:
    """Convert (lay, row, col) well address to DISV (lay, cell_id)."""
    return (lay, row * int(ncol) + col)


def _validate_resolved_well_cell(model, *, well_id: str, lay: int, cell_id: int) -> None:
    """A WEL cell must exist in the grid and be active (idomain != 0).

    MODFLOW errors here are cryptic, so we fail early naming the well. Layers and
    cells are 0-based. The per-layer mask ``solver_mesh.inactive_mask`` (nlay,
    n_cells) tells which cells are inactive (True).
    """
    nlay = int(model.nlay)
    if lay < 0 or lay >= nlay:
        raise ValueError(
            f"flow.sinks_sources.wells.{well_id} layer {lay} is outside the grid: "
            f"valid layers are 0..{nlay - 1} (0-based)."
        )
    mask = np.asarray(model.solver_mesh.inactive_mask, dtype=bool)
    n_cells = int(mask.shape[1])
    if cell_id < 0 or cell_id >= n_cells:
        raise ValueError(
            f"flow.sinks_sources.wells.{well_id} cell {cell_id} is outside the grid "
            f"({n_cells} cells)."
        )
    if bool(mask[lay, cell_id]):
        raise ValueError(
            f"flow.sinks_sources.wells.{well_id} targets an inactive cell (layer {lay}, "
            f"cell {cell_id}); place the well inside the catchment."
        )


def _forcing_units(forcing: object, *, fallback: object) -> object:
    if isinstance(forcing, Mapping):
        return forcing.get("units", fallback)
    return getattr(forcing, "units", fallback)


def _resolve_well_location(well_id: str, well_cfg: object) -> tuple[str, dict[str, Any]]:
    """Return ``(kind, fields)`` for one well payload (config or raw mapping)."""
    if isinstance(well_cfg, Mapping):
        from hydromodpy.physics.flow.sinks_sources.wells import FlowWellConfig

        well_cfg = FlowWellConfig.model_validate(dict(well_cfg))
    location = getattr(well_cfg, "location", None)
    kind = getattr(location, "kind", None)
    if kind == "cell":
        return "cell", {"cell": tuple(location.cell)}
    if kind == "absolute_xy":
        return "absolute_xy", {
            "layer": int(location.layer),
            "x": float(location.x),
            "y": float(location.y),
        }
    if kind == "relative_xy":
        return "relative_xy", {
            "layer": int(location.layer),
            "x_rel": float(location.x_rel),
            "y_rel": float(location.y_rel),
        }
    raise ValueError(
        f"flow.sinks_sources.wells.{well_id} requires either cell=[lay,row,col] "
        "or coordinate-based location fields."
    )


def resolve_well_disv_cell(
    model,
    *,
    well_id: str,
    well_cfg: object,
) -> tuple[int, int]:
    """Resolve one well payload to one DISV (layer, cell_id) tuple.

    A ``[lay, row, col]`` address names a cell of a regular grid only, and the
    configuration refuses it on another mesh before any meshing. A coordinate
    is located in the cell mesh the solver was given: by floor arithmetic on a
    regular grid, by containment on any other mesh.
    """
    location_kind, fields = _resolve_well_location(well_id, well_cfg)
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            f"flow.sinks_sources.wells.{well_id} is placed on the cells of the solver mesh, "
            "but none is set."
        )
    cell_mesh = solver_mesh.cell_mesh

    if location_kind == "cell":
        cell_seq = fields["cell"]
        if len(cell_seq) != 3:
            raise ValueError(
                f"flow.sinks_sources.wells.{well_id}.cell must contain [lay, row, col]."
            )
        lay, row, col = int(cell_seq[0]), int(cell_seq[1]), int(cell_seq[2])
        shape = cell_mesh.structured_shape
        if shape is None:
            raise ValueError(
                f"flow.sinks_sources.wells.{well_id}.cell [lay, row, col] addressing needs a "
                "regular grid; use a coordinate-based location on a triangle or Voronoi mesh."
            )
        nrow, ncol = shape
        if row < 0 or row >= nrow:
            raise ValueError(f"flow.sinks_sources.wells.{well_id}.cell row is outside the grid.")
        if col < 0 or col >= ncol:
            raise ValueError(f"flow.sinks_sources.wells.{well_id}.cell col is outside the grid.")
        lay_cell = well_cell_to_disv(ncol=ncol, lay=lay, row=row, col=col)
        _validate_resolved_well_cell(model, well_id=well_id, lay=lay_cell[0], cell_id=lay_cell[1])
        return lay_cell

    layer = int(fields["layer"])
    if location_kind == "absolute_xy":
        x_m = float(fields["x"])
        y_m = float(fields["y"])
    elif location_kind == "relative_xy":
        xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
        x_m = xmin + float(fields["x_rel"]) * (xmax - xmin)
        y_m = ymin + float(fields["y_rel"]) * (ymax - ymin)
    else:
        raise ValueError(
            f"Unsupported well location mode for flow.sinks_sources.wells.{well_id}: "
            f"{location_kind!r}."
        )
    cell_id = int(locate_cells(cell_mesh, np.array([[x_m, y_m]]), allow_nearest=False)[0])
    if cell_id < 0:
        raise ValueError(
            f"flow.sinks_sources.wells.{well_id} coordinates ({x_m}, {y_m}) are outside "
            "the mesh domain."
        )
    _validate_resolved_well_cell(model, well_id=well_id, lay=layer, cell_id=cell_id)
    return (layer, cell_id)


def build_well_stress_period_data(
    model,
    n_stress_periods: int,
) -> dict[int, list[list[float]]]:
    """Build MF6 WEL stress-period data from the configured wells."""
    if n_stress_periods <= 0 or model.flow is None:
        return {}

    active = getattr(model.flow, "active_sinks_sources", [])
    if "wells" not in active:
        return {}

    sinks_sources = getattr(model.flow, "sinks_sources", {})
    if not isinstance(sinks_sources, Mapping):
        return {}

    wells = sinks_sources.get("wells", {})
    if wells is None:
        return {}
    if not isinstance(wells, Mapping):
        raise TypeError("flow.sinks_sources['wells'] must be a mapping of well ids to payloads.")
    if len(wells) == 0:
        return {}
    normalized_wells: list[tuple[tuple[int, int], np.ndarray]] = []
    for well_id, raw_well_payload in wells.items():
        flux_payload = getattr(raw_well_payload, "flux", None)
        forcing_payload = getattr(raw_well_payload, "forcing", None)
        if isinstance(raw_well_payload, Mapping):
            flux_payload = raw_well_payload.get("flux")
            forcing_payload = raw_well_payload.get("forcing")
        if flux_payload is None and forcing_payload is None:
            continue

        cell = resolve_well_disv_cell(
            model,
            well_id=well_id,
            well_cfg=raw_well_payload,
        )

        if forcing_payload is not None:
            raw_values = resolve_period_values_from_forcing(
                forcing=forcing_payload,
                simulation_window=None if model.time_grid is None else model.time_grid.window,
                nper=int(n_stress_periods),
                label=f"flow.sinks_sources.wells.{well_id}.forcing",
            )
            fallback_units = (
                raw_well_payload.get("units", "m3/s")
                if isinstance(raw_well_payload, Mapping)
                else getattr(raw_well_payload, "units", "m3/s")
            )
            canonical_units = normalize_m3_per_s_unit(
                _forcing_units(forcing_payload, fallback=fallback_units),
            )
            flux_vector = np.asarray(
                [
                    convert_to_m3_per_s(
                        value,
                        unit=canonical_units,
                        label=f"flow.sinks_sources.wells.{well_id}.forcing[{idx}]",
                    )
                    for idx, value in enumerate(raw_values)
                ],
                dtype=float,
            )
        elif isinstance(flux_payload, Real) and not isinstance(flux_payload, bool):
            flux_vector = np.full((n_stress_periods,), float(flux_payload), dtype=float)
        else:
            raw_flux_seq = list(flux_payload)
            parsed = np.asarray(raw_flux_seq, dtype=float)
            if parsed.size == 1:
                flux_vector = np.full((n_stress_periods,), float(parsed[0]), dtype=float)
            elif parsed.size == int(n_stress_periods):
                flux_vector = parsed.astype(float)
            elif int(n_stress_periods) == 1:
                # The steady spin-up collapses the transient window to one
                # period. Carry the time-mean well flux, like recharge/EVT,
                # instead of the first-period value.
                flux_vector = np.full((1,), float(np.mean(parsed)), dtype=float)
            else:
                raise ValueError(
                    f"flow.sinks_sources.wells.{well_id}.flux length ({parsed.size}) "
                    f"must be 1 or match nper ({int(n_stress_periods)})."
                )
        if not np.all(np.isfinite(flux_vector)):
            raise ValueError(f"flow.sinks_sources.wells.{well_id}.flux must be finite.")
        normalized_wells.append((cell, flux_vector))

    spd: dict[int, list[list[float]]] = {}
    for t in range(n_stress_periods):
        spd[t] = [
            [cell[0], cell[1], float(flux_vector[t])] for cell, flux_vector in normalized_wells
        ]
    return spd


__all__ = [
    "build_well_stress_period_data",
    "resolve_well_disv_cell",
    "well_cell_to_disv",
]
