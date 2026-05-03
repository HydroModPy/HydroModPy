"""WEL/DRN payload builders for the NWT flow-to-modflow adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units import factor_to_m2_per_s
from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow_grid.grid_context import grid_reference_from_solver_mesh
from hydromodpy.solver.modflow_nwt.nwt._chd_payloads import forcing_units

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import (
        FlowToModflowAdapter,
    )


def coerce_conductance_value_to_m2_per_s(
    *,
    value: object,
    units: object,
) -> float:
    """Convert one conductance scalar to m2/s."""
    factor = factor_to_m2_per_s(str(units).strip() or "m2/s")
    return float(value) * float(factor)


def build_drainage_spd(
    adapter: FlowToModflowAdapter,
    *,
    drain_array: np.ndarray,
    hk: np.ndarray,
) -> dict[int, np.ndarray] | None:
    """Build DRN stress-period data from drainage BC and activation mask.

    Conductance policy:
    - If drainage BC value > 0: use this explicit conductance.
    - Otherwise: derive conductance from ``hk * cell_area``.
    - With ``sink_fill=True``: cells flagged as sink receive zero conductance.

    Returns ``None`` when drainage is not activated.
    """
    if not adapter._is_bc_active("drainage"):
        return None
    drainage_boundary = adapter._boundary_conditions.get("drainage")
    if drainage_boundary is None:
        return None

    if adapter.sink_fill and adapter.sink is None:
        raise ValueError("sink_fill=True requires geographic.depressions_data (sink raster)")

    drn_data = np.zeros((int(np.sum(drain_array)), 5), dtype=float)
    drn_data[:, 0] = 0
    drainage_value = coerce_conductance_value_to_m2_per_s(
        value=drainage_boundary.value,
        units=getattr(drainage_boundary, "units", "m2/s"),
    )

    count = 0
    for i in range(adapter.nrow):
        for j in range(adapter.ncol):
            if drain_array[i, j] != 1:
                continue

            drn_data[count, 1] = i
            drn_data[count, 2] = j
            drn_data[count, 3] = adapter.dem[i, j]

            if not adapter.sink_fill:
                if drainage_value > 0:
                    drn_data[count, 4] = drainage_value
                else:
                    drn_data[count, 4] = hk[0, i, j] * adapter.cell_area
            else:
                if adapter.sink[i, j] > 0:
                    drn_data[count, 4] = 0.0
                elif drainage_value > 0:
                    drn_data[count, 4] = drainage_value
                else:
                    drn_data[count, 4] = hk[0, i, j] * adapter.cell_area
            count += 1

    return {0: drn_data}


def build_well_stress_period_data(
    adapter: FlowToModflowAdapter,
) -> dict[int, list[list[float]]]:
    """Normalize flow wells into MODFLOW WEL stress-period format."""
    if adapter.nper <= 0:
        return {}

    active = getattr(adapter.flow, "active_sinks_sources", [])
    if "wells" not in active:
        return {}

    sinks_sources = getattr(adapter.flow, "sinks_sources", {})
    wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
    if not wells:
        return {}

    grid = adapter.grid
    if grid is None:
        grid = grid_reference_from_solver_mesh(adapter.solver_mesh)

    normalized_wells: list[tuple[str, tuple[int, int, int], np.ndarray]] = []
    for well_id, well in wells.items():
        if getattr(well, "cell", None) is not None:
            cell = well.cell
        else:
            if grid is None:
                raise ValueError(
                    f"flow.sinks_sources.wells.{well_id} uses coordinate-based addressing "
                    "but solver grid geometry is unavailable"
                )
            cell = well.resolve_cell(grid)
        forcing = getattr(well, "forcing", None)
        if forcing is not None:
            raw_values = resolve_period_values_from_forcing(
                forcing=forcing,
                simulation_window=adapter.simulation_window,
                nper=adapter.nper,
                label=f"flow.sinks_sources.wells.{well_id}.forcing",
            )
            canonical_units = normalize_m3_per_s_unit(
                forcing_units(
                    forcing,
                    fallback=getattr(well, "units", "m3/s"),
                )
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
        else:
            flux = well.flux
            if isinstance(flux, (list, tuple)):
                flux_vector = np.asarray(list(flux), dtype=float)
                if flux_vector.size == 1:
                    flux_vector = np.full(adapter.nper, float(flux_vector[0]), dtype=float)
                elif flux_vector.size != adapter.nper:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.flux length ({flux_vector.size}) "
                        f"must be 1 or match nper ({adapter.nper})"
                    )
            else:
                flux_vector = np.full(adapter.nper, float(flux), dtype=float)
        if not np.all(np.isfinite(flux_vector)):
            raise ValueError(f"flow.sinks_sources.wells.{well_id}.flux must be finite.")
        normalized_wells.append((well_id, cell, flux_vector))

    lrcq: dict[int, list[list[float]]] = {}
    for t in range(adapter.nper):
        lrcq[t] = [
            [cell[0], cell[1], cell[2], float(flux_vector[t])]
            for _, cell, flux_vector in normalized_wells
        ]
    return lrcq


__all__ = [
    "build_drainage_spd",
    "build_well_stress_period_data",
    "coerce_conductance_value_to_m2_per_s",
]
