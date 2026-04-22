# -*- coding: utf-8 -*-
# Intentional duplication with the MF6 flow_to_modflow_adapter: MODFLOW-NWT is
# scheduled for removal after the Lake (LAK) module lands on the MF6 side — not
# worth factoring the payload builders out. See docs/developers/nwt_sunset_plan.md.
"""
Flow -> MODFLOW-NWT adaptation layer.

Purpose
-------
Convert process-level objects into solver-level data structures:

- from ``Flow`` / ``Domain`` runtime objects,
- to MODFLOW-ready arrays and stress-period data dictionaries.

Main elements handled by this module
------------------------------------
Inputs (process/runtime side):
- ``flow.parameters``:
  process-level hydraulic properties (primarily K, Sy, Ss), potentially
  homogeneous or heterogeneous, that must be projected onto the MODFLOW grid.
- ``flow.initial_conditions.h``:
  startup head policy used to initialize ``strt`` (top, bottom, or custom
  scalar value), before transient simulation starts.
- ``flow.boundary_conditions``:
  boundary-condition objects keyed by id (for example ocean, side Dirichlet
  limits, drainage) that drive ``ibound`` updates and CHD/DRN package payloads.
- ``flow.sinks_sources``:
  source/sink definitions (wells and recharge) converted to period-wise
  WEL rows ``[lay, row, col, flux]`` and RCH/EVT stress-period dicts.
- ``domain`` + ``solver_mesh`` context:
  spatial support used to map process properties onto solver cells, including
  spatial supports (geology or other zonations) and structured-grid geometry.

Outputs (solver side):
- 3D arrays:
  ``ibound``, ``strt``, ``hk``, ``sy``, ``ss`` with shape
  ``(nlay, nrow, ncol)``; these are direct inputs for BAS/UPW-like solver
  packages.
- 2D arrays:
  ``drain_array``, ``hk_value``, ``sy_value``, ``ss_value`` with shape
  ``(nrow, ncol)``; used for drainage activation and diagnostic snapshots of
  mapped surface properties.
- stress-period payloads:
  ``chd_spd``, ``drn_spd``, ``wel_spd`` as MODFLOW stress-period dictionaries
  keyed by period index, ready to be passed to FLOPY package constructors.
- recharge payloads:
  ``rch_data`` as a period-indexed dict or a scalar (steady-state Mapping
  average), consumed by ``ModflowRch(rech=...)``.
  ``evt_spd`` as a per-period evapotranspiration dict built from negative
  recharge values routed to EVT, or ``None`` when not activated.

Glossary
--------
- ``payload``: the effective data content exchanged between layers
  (for example one boundary dict, one well dict, or one stress-period table).
- ``adapter``: a translation layer between two contracts with different
  semantics (here process contract -> MODFLOW contract).

Design philosophy
-----------------
This module is the strict boundary between:

1. process/runtime semantics (`Flow`, `Domain`, typed process payloads), and
2. solver payloads (dense arrays + stress-period dictionaries) expected by
   FLOPY MODFLOW-NWT packages.

The adapter is intentionally narrow and deterministic:

- it does not instantiate FLOPY packages;
- it does not mutate upstream process objects;
- it does not hide invalid inputs with implicit fallbacks;
- it fails fast with contextual errors when runtime payloads are inconsistent.

Why this separation matters
---------------------------
Keeping the transformation here prevents solver-specific conventions from
leaking into process models. Process schemas remain solver-agnostic, while
solver packages consume one explicit, normalized contract (`FlowModflowInputs`).

Initial conditions: ownership vs requirement
--------------------------------------------
One important rule in this module is easy to miss:

- initial conditions are **defined by the process** (`Flow`), using its own
  typed schema (`flow.initial_conditions.h`),
- initial conditions are **required by the solver** (MODFLOW startup needs
  `strt` everywhere).

The adapter enforces this contract by reading the process payload and building
the solver startup arrays. It does not define the IC schema itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow_common.grid_context import GridReference
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.core.units import (
    convert_payload_to_m,
    convert_payload_to_m_per_s,
    factor_to_m2_per_s,
    normalize_length_unit,
)
from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)

from .property_mapping import (
    resolve_required_flow_properties,
    resolve_flow_property_arrays,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow


def _discretize_heterogeneous_source(
    het_source: object,
    *,
    solver_mesh: SolverMesh,
    nper: int,
    simulation_window: object,
    method: str = "nearest",
    source_unit: str = "m/s",
) -> dict[int, np.ndarray]:
    """Dispatch heterogeneous discretization for fields or located points."""
    from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
        discretize_fields_on_sgrid,
        discretize_points_on_sgrid,
    )
    # SolverMesh exposes sgrid-compatible properties (nrow, ncol, delr, delc,
    # xoffset, yoffset, xvertices, yvertices) so it can be passed directly.

    # Prefer fields when available.
    if getattr(het_source, "has_fields", False):
        return discretize_fields_on_sgrid(
            load_result=het_source,
            sgrid=solver_mesh,
            nper=nper,
            simulation_window=simulation_window,
            method=method,
        )

    # Fall back to located points.
    if getattr(het_source, "has_points", False):
        return discretize_points_on_sgrid(
            load_result=het_source,
            sgrid=solver_mesh,
            nper=nper,
            simulation_window=simulation_window,
            method=method,
            source_unit=source_unit,
        )

    nrow = solver_mesh.nrow
    ncol = solver_mesh.ncol
    return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}


@dataclass(slots=True)
class FlowModflowInputs:
    """
    Solver-ready payloads produced from one validated ``Flow`` runtime object.

    Notes
    -----
    - Arrays use MODFLOW indexing conventions (`lay,row,col` for 3D arrays).
    - Stress-period dictionaries are keyed by zero-based period index.
    - Optional payloads are omitted as ``None`` when the corresponding process
      boundary/source is not defined.

    Array conventions
    -----------------
    - ``ibound``: shape ``(nlay, nrow, ncol)``; values follow MODFLOW
      conventions (`1` active, `0` inactive, `-1` constant-head).
    - ``strt``: shape ``(nlay, nrow, ncol)``; startup head used by BAS.
    - ``drain_array``: shape ``(nrow, ncol)``; binary drainage activation mask.
    - ``hk``, ``sy``, ``ss``: shape ``(nlay, nrow, ncol)``.
    - ``*_value``: shape ``(nrow, ncol)`` surface snapshot kept for diagnostics.
    - ``rch_data``: period-indexed dict ``{kper: value}`` consumed by
      ``ModflowRch(rech=...)``, or a scalar average for steady-state Mapping
      inputs.
    - ``evt_spd``: per-period evapotranspiration dict ``{kper: value}``
      produced when negative recharge values are routed to EVT, or ``None``
      when EVT routing is not activated.

    BAS contract reminder
    ---------------------
    ``ibound`` and ``strt`` are consumed together by MODFLOW BAS:
    - ``ibound > 0``: active cells where head is solved.
    - ``ibound = 0``: inactive/no-flow cells.
    - ``ibound < 0``: constant-head cells where head is imposed.
    - ``strt`` provides startup heads and, for constant-head cells, the
      imposed head values used by BAS.
    """

    ibound: np.ndarray
    strt: np.ndarray
    drain_array: np.ndarray
    hk: np.ndarray
    hk_value: np.ndarray
    sy: np.ndarray
    sy_value: np.ndarray
    ss: np.ndarray
    ss_value: np.ndarray
    chd_spd: dict[int, list[list[float]]] | None
    drn_spd: dict[int, np.ndarray] | None
    wel_spd: dict[int, list[list[float]]]
    rch_data: object | None
    evt_spd: dict[int, object] | None


class FlowToModflowAdapter:
    """
    Build MODFLOW-NWT arrays/stress-period structures from Flow + context.

    Scope
    -----
    This class only prepares solver data. FLOPY package construction is done
    by the caller (`Modflow`), after adaptation is complete.

    Input contract (high-level)
    ---------------------------
    Required process payloads:
    - ``flow.initial_conditions.h`` (with ``type`` in ``top|bottom|custom``),
    - ``flow.parameters`` for K/Sy/Ss mapping,
    - optional ``flow.boundary_conditions`` and ``flow.sinks_sources``.

    Required domain payloads:
    - one spatial support attached to ``domain.zones`` when mapping
      heterogeneous properties.

    The adapter assumes the caller already prepared the spatial/temporal
    context (grid dimensions, DEM/bottom arrays, stress-period count).
    """

    def __init__(
        self,
        *,
        flow: object,
        domain: object,
        solver_mesh: SolverMesh,
        nper: int,
        grid: GridReference | None = None,
        simulation_window: "ResolvedSimulationTimeWindow | None" = None,
        sink_fill: bool,
        sink=None,
        flow_runtime_overrides: Mapping[str, object] | None = None,
    ):
        """
        Store adaptation context and normalize primitive arrays/scalars.

        Parameters
        ----------
        flow : object
            Runtime flow-process instance carrying IC/BC/parameters.
        domain : object
            Runtime domain instance carrying spatial zones used by property mapping.
        solver_mesh : SolverMesh
            Unified solver mesh carrying planar geometry, top/botm elevations,
            and inactive mask. Must be structured for NWT.
        nper : int
            Number of stress periods.
        grid : GridReference | None
            Solver-grid geometry. When provided, conductance and cell-area
            calculations use ``dx``/``dy`` rather than a scalar proxy.
        sink_fill : bool
            If True, sink mask can deactivate drainage conductance locally.
        sink : array-like | None
            Optional sink/depression raster aligned with model rows/cols.
        """
        if not solver_mesh.is_structured:
            raise ValueError(
                "FlowToModflowAdapter requires a structured SolverMesh "
                "(MODFLOW NWT only supports structured grids)"
            )

        # Keep source objects by reference (read-only usage).
        self.flow = flow
        self.domain = domain
        self.solver_mesh = solver_mesh

        # Extract structured dimensions and elevation arrays from SolverMesh.
        self.nlay = solver_mesh.nlay
        self.nrow = solver_mesh.nrow
        self.ncol = solver_mesh.ncol
        self.dem = solver_mesh.reshape_to_grid(solver_mesh.top)
        self.bottom_layer = solver_mesh.reshape_to_grid(solver_mesh.botm[-1])

        self.nper = int(nper)
        self.grid = grid
        self.simulation_window = simulation_window
        if self.grid is None:
            self.cell_area = float(solver_mesh.characteristic_length) ** 2
            self.characteristic_length = float(solver_mesh.characteristic_length)
        else:
            self.cell_area = float(self.grid.cell_area)
            self.characteristic_length = float(self.grid.characteristic_length)
        self.resolution = float(self.characteristic_length)
        self.sink_fill = bool(sink_fill)
        self.sink = None if sink is None else np.asarray(sink, dtype=float)
        self.inactive_mask = solver_mesh.reshape_to_grid(solver_mesh.inactive_mask[0])
        self.flow_runtime_overrides = (
            None if flow_runtime_overrides is None else dict(flow_runtime_overrides)
        )

    @property
    def _boundary_conditions(self) -> Mapping[str, object]:
        """Return flow boundary-condition mapping with a strict runtime check."""
        boundary_conditions = getattr(self.flow, "boundary_conditions", {})
        if not isinstance(boundary_conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return boundary_conditions

    def _build_initial_heads_and_sides(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Build startup ``ibound`` and ``strt`` arrays from flow IC + side BCs.

        Returns
        -------
        tuple[np.ndarray, np.ndarray, np.ndarray]
            ``(ibound, strt, drain_array)``, where ``drain_array`` is a 2D
            active-drain mask initialized to ones and later refined by ocean BC.
        """
        ibound = np.ones((self.nlay, self.nrow, self.ncol), dtype=float)

        initial_conditions = getattr(self.flow, "initial_conditions", None)
        initial_condition = (
            None if initial_conditions is None else getattr(initial_conditions, "h", None)
        )
        if initial_condition is None:
            raise ValueError("flow.initial_conditions.h is required for MODFLOW startup")

        # MODFLOW startup heads are derived from one explicit process policy:
        # - "top": initialize with DEM elevation
        # - "bottom": initialize with bottom elevation
        # - "custom": initialize with one user scalar
        initial_type = str(getattr(initial_condition, "type", "")).strip().lower()
        if initial_type == "top":
            strt = np.ones((self.nlay, self.nrow, self.ncol), dtype=float) * self.dem
        elif initial_type == "bottom":
            strt = np.ones((self.nlay, self.nrow, self.ncol), dtype=float) * self.bottom_layer
        elif initial_type == "custom":
            strt = np.ones((self.nlay, self.nrow, self.ncol), dtype=float) * float(
                getattr(initial_condition, "value")
            )
        else:
            raise ValueError("flow.initial_conditions.h.type must be one of: top, bottom, custom")

        # Side Dirichlet boundaries are enforced by:
        # - setting ibound to -1 (constant-head cells),
        # - forcing startup heads on the same faces.
        west_side = (
            self._boundary_conditions.get("west_side") if self._is_bc_active("west_side") else None
        )
        if west_side is not None:
            west_series = self._resolve_side_boundary_series(boundary=west_side, bc_id="west_side")
            if self._side_boundary_is_static(west_side):
                ibound[:, :, 0] = -1
            strt[:, :, 0] = float(west_series[0])

        east_side = (
            self._boundary_conditions.get("east_side") if self._is_bc_active("east_side") else None
        )
        if east_side is not None:
            east_series = self._resolve_side_boundary_series(boundary=east_side, bc_id="east_side")
            if self._side_boundary_is_static(east_side):
                ibound[:, :, -1] = -1
            strt[:, :, -1] = float(east_series[0])

        north_side = (
            self._boundary_conditions.get("north_side")
            if self._is_bc_active("north_side")
            else None
        )
        if north_side is not None:
            north_series = self._resolve_side_boundary_series(
                boundary=north_side, bc_id="north_side"
            )
            if self._side_boundary_is_static(north_side):
                ibound[:, 0, :] = -1
            strt[:, 0, :] = float(north_series[0])

        south_side = (
            self._boundary_conditions.get("south_side")
            if self._is_bc_active("south_side")
            else None
        )
        if south_side is not None:
            south_series = self._resolve_side_boundary_series(
                boundary=south_side, bc_id="south_side"
            )
            if self._side_boundary_is_static(south_side):
                ibound[:, -1, :] = -1
            strt[:, -1, :] = float(south_series[0])

        # Cells under the DEM sentinel threshold, or undefined after resampling,
        # are treated as inactive everywhere in the stack.
        for ilay in range(self.nlay):
            ibound[ilay][self.inactive_mask] = 0
            strt[ilay][self.inactive_mask] = 0.0

        drain_array = np.ones((self.nrow, self.ncol), dtype=float)
        drain_array[self.inactive_mask] = 0.0
        return ibound, strt, drain_array

    @staticmethod
    def _is_scalar_number(value: object) -> bool:
        """Return True for numeric scalar values (excluding booleans)."""
        return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
            value, bool
        )

    def _is_constant_scalar_forcing(self, forcing: object) -> bool:
        """Return True when one forcing payload is a scalar constant."""
        if forcing is None:
            return False
        if getattr(forcing, "mode", None) != "constant":
            return False
        try:
            return self._is_scalar_number(forcing.as_constant().value)
        except Exception:
            return False

    def _normalize_boundary_series(
        self,
        *,
        value: object,
        label: str,
    ) -> np.ndarray | None:
        """Normalize one boundary value payload to an ``nper`` series when needed."""
        if self._is_scalar_number(value):
            return None
        if not isinstance(value, (np.ndarray, pd.Series, list, tuple)):
            raise TypeError(f"{label} must be numeric or a sequence of numeric values")

        series = np.asarray(value, dtype=float).reshape(-1)
        if series.size == 0:
            raise ValueError(f"{label} cannot be empty when using time series")
        if series.size == 1:
            return np.full(self.nper, float(series[0]), dtype=float)
        if series.size != self.nper:
            raise ValueError(
                f"{label} length ({series.size}) must be 1 or match nper ({self.nper})"
            )
        return series.astype(float)

    def _boundary_start_value(
        self,
        *,
        value: object,
        label: str,
    ) -> float:
        """Return the startup head used on one boundary face."""
        if self._is_scalar_number(value):
            return float(value)
        series = self._normalize_boundary_series(value=value, label=label)
        if series is None:
            raise ValueError(f"{label} must define a scalar or sequence value")
        return float(series[0])

    def _coerce_length_series_to_m(
        self,
        *,
        values: object,
        units: object,
        label: str,
    ) -> np.ndarray:
        source_units = normalize_length_unit(str(units).strip() or "m")
        return np.asarray(
            convert_payload_to_m(values, unit=source_units, label=label),
            dtype=float,
        )

    @staticmethod
    def _forcing_units(forcing: object, *, fallback: object) -> object:
        if isinstance(forcing, Mapping):
            return forcing.get("units", fallback)
        return getattr(forcing, "units", fallback)

    def _coerce_conductance_value_to_m2_per_s(
        self,
        *,
        value: object,
        units: object,
    ) -> float:
        factor = factor_to_m2_per_s(str(units).strip() or "m2/s")
        return float(value) * float(factor)

    def _resolve_side_boundary_series(
        self,
        *,
        boundary: object,
        bc_id: str,
    ) -> np.ndarray:
        """Resolve one lateral boundary payload to one value per stress period."""
        forcing = getattr(boundary, "forcing", None)
        label = f"flow.bc.{bc_id}.forcing"
        if forcing is not None:
            raw_values = resolve_period_values_from_forcing(
                forcing=forcing,
                simulation_window=self.simulation_window,
                nper=self.nper,
                label=label,
            )
            return self._coerce_length_series_to_m(
                values=raw_values,
                units=self._forcing_units(
                    forcing,
                    fallback=getattr(boundary, "units", "m"),
                ),
                label=label,
            )

        value = getattr(boundary, "value", None)
        value_label = f"flow.bc.{bc_id}.value"
        series = self._normalize_boundary_series(value=value, label=value_label)
        if series is None:
            series = np.full(self.nper, float(value), dtype=float)
        return self._coerce_length_series_to_m(
            values=series,
            units=getattr(boundary, "units", "m"),
            label=value_label,
        )

    def _side_boundary_is_static(self, boundary: object) -> bool:
        """Return True only for direct scalar ``value`` side boundaries.

        Constant side forcing declared via ``forcing.mode="constant"`` still
        travels through the CHD package path so it behaves like other forcing-
        resolved boundary series and stays consistent with the MF6 adapter.
        """
        return getattr(boundary, "forcing", None) is None and self._is_scalar_number(
            getattr(boundary, "value", None)
        )

    def _is_bc_active(self, bc_id: str) -> bool:
        """Return True when ``bc_id`` is explicitly declared in ``flow.active_bc``."""
        active = getattr(self.flow, "active_bc", [])
        return bc_id in active

    def _build_ocean_chd(
        self,
        *,
        ibound: np.ndarray,
        strt: np.ndarray,
        drain_array: np.ndarray,
    ) -> dict[int, list[list[float]]] | None:
        """
        Build CHD stress-period data for the ocean boundary when defined.

        Side effects
        ------------
        This method mutates ``ibound``, ``strt`` and ``drain_array`` in place:

        - ``ibound``: ocean-influenced cells can become constant-head (``-1``),
        - ``strt``: startup heads can be overwritten by ocean head,
        - ``drain_array``: CHD-supported cells are deactivated for drainage.

        Behavior
        --------
        - No ocean BC: returns ``None`` and leaves arrays unchanged.
        - Scalar ocean value: applies a static sea level directly on startup
          state (no per-period CHD payload returned).
        - Vector ocean value: builds CHD entries per stress period.
        - Cells covered by CHD support are removed from drainage activation.

        Notes
        -----
        For transient ocean forcing, CHD geometry support is fixed from the
        maximum sea level over the series. This keeps a stable active set
        through time and only changes imposed heads per period.
        """
        # 1) Resolve ocean BC payload — only when ocean is explicitly activated.
        if not self._is_bc_active("ocean"):
            return None
        ocean_boundary = self._boundary_conditions.get("ocean")
        if ocean_boundary is None:
            return None

        ocean_value = getattr(ocean_boundary, "value", None)
        if self._is_scalar_number(ocean_value):
            # Static sea level: mark submerged cells as constant-head for all
            # layers before package construction.
            ocean_head = self._coerce_length_series_to_m(
                values=ocean_value,
                units=getattr(ocean_boundary, "units", "m"),
                label="flow.bc.ocean.value",
            )
            ocean_head = float(np.asarray(ocean_head, dtype=float).reshape(-1)[0])
            for ilay in range(self.nlay):
                ibound[ilay][self.dem <= ocean_head] = -1
            strt[ibound == -1] = ocean_head

        # 2) CHD package data is only built for sequence-like inputs.
        # Scalar ocean forcing has already been fully applied in-place above.
        ocean_series = self._normalize_boundary_series(
            value=ocean_value,
            label="flow.bc.ocean.value",
        )
        if ocean_series is None:
            return None
        ocean_series = self._coerce_length_series_to_m(
            values=ocean_series,
            units=getattr(ocean_boundary, "units", "m"),
            label="flow.bc.ocean.value",
        )

        # 3) Geometry mask is fixed from the highest sea level; transient heads are
        # then assigned period-by-period on that stable support.
        sea_threshold = float(np.max(ocean_series))
        chd_spd: dict[int, list[list[float]]] = {}
        for kper in range(self.nper):
            chd_kper: list[list[float]] = []
            kper_head = float(ocean_series[kper])
            for i in range(self.nrow):
                for j in range(self.ncol):
                    # Keep inactive cells untouched (ibound==0).
                    # For active support cells below sea threshold:
                    # - disable drainage at this location,
                    # - add CHD entry with (shead=ehead=kper_head).
                    if self.dem[i, j] < sea_threshold and ibound[0, i, j] != 0:
                        drain_array[i, j] = 0
                        chd_kper.append([0, i, j, kper_head, kper_head])
            chd_spd[kper] = chd_kper
        return chd_spd

    def _iter_side_boundary_cells(self, bc_id: str):
        """Yield solver cells belonging to one lateral model face."""
        if bc_id == "west_side":
            for ilay in range(self.nlay):
                for i in range(self.nrow):
                    yield ilay, i, 0
            return
        if bc_id == "east_side":
            for ilay in range(self.nlay):
                for i in range(self.nrow):
                    yield ilay, i, self.ncol - 1
            return
        if bc_id == "north_side":
            for ilay in range(self.nlay):
                for j in range(self.ncol):
                    yield ilay, 0, j
            return
        if bc_id == "south_side":
            for ilay in range(self.nlay):
                for j in range(self.ncol):
                    yield ilay, self.nrow - 1, j
            return
        raise ValueError(f"Unsupported side boundary id: {bc_id}")

    def _build_side_chd(self) -> dict[int, list[list[float]]] | None:
        """Build CHD stress-period data for transient lateral Dirichlet boundaries."""
        per_period: dict[int, dict[tuple[int, int, int], list[float]]] = {
            kper: {} for kper in range(self.nper)
        }
        has_entries = False

        for bc_id in ("west_side", "east_side", "north_side", "south_side"):
            if not self._is_bc_active(bc_id):
                continue
            boundary = self._boundary_conditions.get(bc_id)
            if boundary is None:
                continue
            if self._side_boundary_is_static(boundary):
                continue
            series = self._resolve_side_boundary_series(boundary=boundary, bc_id=bc_id)

            for kper, head in enumerate(series):
                for ilay, row, col in self._iter_side_boundary_cells(bc_id):
                    if self.inactive_mask[row, col]:
                        continue
                    per_period[kper][(ilay, row, col)] = [
                        ilay,
                        row,
                        col,
                        float(head),
                        float(head),
                    ]
                    has_entries = True

        if not has_entries:
            return None
        return {kper: list(cell_map.values()) for kper, cell_map in per_period.items()}

    def _merge_chd_payloads(
        self,
        *payloads: dict[int, list[list[float]]] | None,
    ) -> dict[int, list[list[float]]] | None:
        """Merge CHD payloads with later inputs overriding earlier duplicate cells."""
        merged: dict[int, list[list[float]]] = {}
        has_entries = False

        for kper in range(self.nper):
            period_map: dict[tuple[int, int, int], list[float]] = {}
            for payload in payloads:
                if payload is None:
                    continue
                for row in payload.get(kper, []):
                    key = (int(row[0]), int(row[1]), int(row[2]))
                    period_map[key] = list(row)
            merged[kper] = list(period_map.values())
            if merged[kper]:
                has_entries = True

        if not has_entries:
            return None
        return merged

    def _validate_ibound_strt_contract(
        self,
        *,
        ibound: np.ndarray,
        strt: np.ndarray,
        drain_array: np.ndarray,
    ) -> None:
        """
        Validate BAS-facing ``ibound``/``strt`` arrays before package assembly.

        This enforces the adapter output contract expected by ``ModflowBas``:
        - ``ibound`` and ``strt`` are 3D arrays with shape
          ``(nlay, nrow, ncol)``.
        - ``drain_array`` is a 2D array with shape ``(nrow, ncol)``.
        - all arrays are finite.
        - ``drain_array`` only contains binary activation flags ``{0, 1}``.

        Note
        ----
        For ``ibound``, this check intentionally validates the sign-based
        contract (positive/zero/negative) used by MODFLOW, rather than
        restricting values to ``{-1, 0, 1}``.
        """
        expected_3d = (self.nlay, self.nrow, self.ncol)
        expected_2d = (self.nrow, self.ncol)

        if ibound.shape != expected_3d:
            raise ValueError(f"ibound shape mismatch: expected {expected_3d}, got {ibound.shape}")
        if strt.shape != expected_3d:
            raise ValueError(f"strt shape mismatch: expected {expected_3d}, got {strt.shape}")
        if drain_array.shape != expected_2d:
            raise ValueError(
                f"drain_array shape mismatch: expected {expected_2d}, got {drain_array.shape}"
            )

        if not np.isfinite(ibound).all():
            raise ValueError("ibound contains non-finite values")
        if not np.isfinite(strt).all():
            raise ValueError("strt contains non-finite values")
        if not np.isfinite(drain_array).all():
            raise ValueError("drain_array contains non-finite values")

        drain_unique = np.unique(drain_array)
        if not np.isin(drain_unique, [0.0, 1.0]).all():
            raise ValueError("drain_array must only contain binary activation values {0, 1}")

    def _build_drainage_spd(
        self,
        *,
        drain_array: np.ndarray,
        hk: np.ndarray,
    ) -> dict[int, np.ndarray] | None:
        """
        Build DRN stress-period data from drainage BC and activation mask.

        Conductance policy
        ------------------
        - If drainage BC value > 0: use this explicit conductance.
        - Otherwise: derive conductance from ``hk * cell_area``.
        - With ``sink_fill=True``: cells flagged as sink receive zero
          conductance (disabled drainage).

        Returns
        -------
        dict[int, np.ndarray] | None
            Stress-period dict ``{0: drn_data}`` where ``drn_data`` has shape
            ``(n_active_cells, 5)`` with columns
            ``[lay, row, col, elevation, conductance]``.
            Returns ``None`` when drainage is not activated.

        Notes
        -----
        The DRN payload is time-invariant: only period 0 is populated.
        MODFLOW inherits that geometry for all subsequent stress periods
        when no new entry is provided.
        """
        # Only assemble DRN payload when drainage BC is explicitly activated.
        if not self._is_bc_active("drainage"):
            return None
        drainage_boundary = self._boundary_conditions.get("drainage")
        if drainage_boundary is None:
            return None

        if self.sink_fill and self.sink is None:
            raise ValueError("sink_fill=True requires geographic.depressions_data (sink raster)")

        # MODFLOW DRN row format: [lay, row, col, elevation, conductance].
        # Only currently active drain cells are materialized.
        drn_data = np.zeros((int(np.sum(drain_array)), 5), dtype=float)
        drn_data[:, 0] = 0
        drainage_value = self._coerce_conductance_value_to_m2_per_s(
            value=drainage_boundary.value,
            units=getattr(drainage_boundary, "units", "m2/s"),
        )

        count = 0
        for i in range(self.nrow):
            for j in range(self.ncol):
                if drain_array[i, j] != 1:
                    continue

                # Fill geometry first, then assign conductance from policy.
                drn_data[count, 1] = i
                drn_data[count, 2] = j
                drn_data[count, 3] = self.dem[i, j]

                if not self.sink_fill:
                    # Either use user conductance or derive conductance from
                    # local permeability footprint: C = K * A.
                    if drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.cell_area
                else:
                    # Sink-filled cells should not drain.
                    if self.sink[i, j] > 0:
                        drn_data[count, 4] = 0.0
                    elif drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.cell_area
                count += 1

        return {0: drn_data}

    def _build_well_stress_period_data(self) -> dict[int, list[list[float]]]:
        """
        Normalize flow wells into MODFLOW WEL stress-period format.

        Returns
        -------
        dict[int, list[list[float]]]
            WEL package stress-period payload keyed by period index, with each
            row formatted as ``[lay, row, col, flux]``.

        Notes
        -----
        Wells absent from ``flow.active_sinks_sources``, or with an empty
        payload, result in an empty dict (no WEL rows), not an error.
        Cell and flux validation is delegated to ``FlowWellConfig`` (Pydantic);
        only the flux-vector length vs ``nper`` is enforced here, since
        ``nper`` is not known at config-validation time.
        """
        if self.nper <= 0:
            return {}

        # Only assemble the WEL payload when wells are explicitly activated.
        active = getattr(self.flow, "active_sinks_sources", [])
        if "wells" not in active:
            return {}

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
        if not wells:
            return {}

        grid = self.grid
        if grid is None:
            grid = GridReference.from_solver_mesh(self.solver_mesh)

        # Broadcast scalar / single-value flux to nper; reject length mismatches.
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
                    simulation_window=self.simulation_window,
                    nper=self.nper,
                    label=f"flow.sinks_sources.wells.{well_id}.forcing",
                )
                canonical_units = normalize_m3_per_s_unit(
                    self._forcing_units(
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
                if isinstance(flux, list):
                    flux_vector = np.asarray(flux, dtype=float)
                    if flux_vector.size == 1:
                        flux_vector = np.full(self.nper, float(flux_vector[0]), dtype=float)
                    elif flux_vector.size != self.nper:
                        raise ValueError(
                            f"flow.sinks_sources.wells.{well_id}.flux length ({flux_vector.size}) "
                            f"must be 1 or match nper ({self.nper})"
                        )
                else:
                    # Scalar flux: same rate for all stress periods.
                    flux_vector = np.full(self.nper, float(flux), dtype=float)
            normalized_wells.append((well_id, cell, flux_vector))

        # Convert normalized wells to period-indexed LRCQ payload.
        lrcq: dict[int, list[list[float]]] = {}
        for t in range(self.nper):
            lrcq[t] = [
                [cell[0], cell[1], cell[2], float(flux_vector[t])]
                for _, cell, flux_vector in normalized_wells
            ]
        return lrcq

    # ------------------------------------------------------------------
    # Recharge / EVT helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_payload(payload: object) -> object:
        """
        Return a defensive copy of a payload to prevent in-place mutations
        from propagating to the upstream process object.

        Mapping inputs are shallow-copied via ``dict()``. Array/Series inputs
        are copied via their own ``.copy()`` method when available. Objects
        that cannot be copied are returned as-is.
        """
        if isinstance(payload, Mapping):
            return dict(payload)
        if hasattr(payload, "copy"):
            try:
                return payload.copy()
            except Exception:
                return payload
        return payload

    @staticmethod
    def _has_negative_values(payload: object) -> bool:
        """
        Return True when ``payload`` contains at least one negative value.

        Uses a two-pass fallback strategy to handle heterogeneous containers:

        1. Direct comparison ``(payload < 0).any().any()`` — covers numpy
           arrays and pandas DataFrames/Series.
        2. Fallback via ``np.asarray`` and ``np.nanmin`` — covers plain
           Python lists and generic 1-D sequences.

        Returns ``False`` when neither strategy succeeds (conservative choice:
        no EVT routing attempted on unrecognised payloads).
        """
        try:
            return bool((payload < 0).any().any())
        except Exception:
            try:
                as_array = np.asarray(payload, dtype=float)
                return bool(np.nanmin(as_array) < 0)
            except Exception:
                return False

    @staticmethod
    def _series_value(payload: object, kper: int):
        """
        Read one stress-period value from a heterogeneous payload container.

        Handles two container families:

        - pandas Series / DataFrame (detected via ``iloc``): uses positional
          integer indexing; extracts a scalar from single-column DataFrames.
        - Generic sequences (list, numpy array, etc.): uses plain ``[]``.
        """
        if hasattr(payload, "iloc"):
            value = payload.iloc[kper]
            try:
                return value.values[0]
            except Exception:
                return value
        return payload[kper]

    def _resolve_flow_regime(self) -> str:
        """
        Resolve and validate the flow regime string from the flow object.

        Looks up the regime in two locations in priority order:

        1. ``flow.config.flow_regime`` — typed config sub-object (preferred).
        2. ``flow.flow_regime`` — direct attribute fallback.

        Returns
        -------
        str
            ``'steady'`` or ``'transient'`` (lower-cased and stripped).

        Raises
        ------
        ValueError
            When no regime attribute is found, or the resolved value is not
            one of the two accepted strings.
        """
        flow_cfg = getattr(self.flow, "config", None)
        regime = None
        if flow_cfg is not None:
            regime = getattr(flow_cfg, "flow_regime", None)
        if regime is None:
            regime = getattr(self.flow, "flow_regime", None)
        if regime is None:
            raise ValueError("flow.flow_regime is required to build recharge payloads.")
        flow_regime = str(regime).strip().lower()
        if flow_regime not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
        return flow_regime

    def _build_recharge_payload(self) -> tuple[object, dict[int, object] | None]:
        """
        Build RCH and EVT payloads from ``flow.sinks_sources["recharge"]``.

        Supports both homogeneous (scalar/series) and heterogeneous (2-D
        per-cell arrays from :class:`LoadResult` FieldRecords) recharge.

        Returns
        -------
        tuple[rch_data, evt_spd]
            ``rch_data`` is the payload passed to ``ModflowRch(rech=...)``.
            ``evt_spd`` is the EVT stress-period dict, or ``None`` when not activated.
        """
        active = getattr(self.flow, "active_sinks_sources", [])
        if "recharge" not in active:
            return None, None

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None
        if recharge_cfg is None:
            return None, None

        # Heterogeneous path: gridded FieldRecords or located points from data managers.
        het_source = getattr(recharge_cfg, "heterogeneous_source", None)
        if het_source is not None and (
            getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
        ):
            return self._build_heterogeneous_recharge_payload(recharge_cfg)

        # Homogeneous path (existing behavior).
        recharge_payload = self._copy_payload(recharge_cfg.values)
        recharge_payload = convert_payload_to_m_per_s(
            recharge_payload,
            unit=str(getattr(recharge_cfg, "units", "mm/day")),
            label="flow.sinks_sources.recharge.values",
        )
        recharge_payload, evt_spd = self._extract_evt_payload(
            recharge_payload, recharge_cfg.negative_to_evt
        )
        rch_data = self._assemble_rch_data(
            recharge_payload, recharge_cfg.first_clim, self._resolve_flow_regime()
        )
        return rch_data, evt_spd

    def _build_heterogeneous_recharge_payload(
        self,
        recharge_cfg: object,
    ) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray] | None]:
        """Discretize gridded FieldRecords onto the MODFLOW grid.

        Returns ``(rch_data, evt_spd)`` where ``rch_data`` is
        ``{kper: ndarray(nrow, ncol)}`` in solver time units.
        """
        het_source = recharge_cfg.heterogeneous_source
        interp_method = getattr(recharge_cfg, "interpolation_method", "nearest")
        # Heterogeneous data comes from data-managers (always mm/day).
        # recharge_cfg.units has been normalized to "m/s" by Flow init.
        source_unit = "mm/day"
        raw_arrays = _discretize_heterogeneous_source(
            het_source,
            solver_mesh=self.solver_mesh,
            nper=self.nper,
            simulation_window=self.simulation_window,
            method=interp_method,
            source_unit=source_unit,
        )

        # Apply first_clim policy.
        rch_data = self._apply_first_clim_2d(
            raw_arrays,
            getattr(recharge_cfg, "first_clim", "mean"),
            self._resolve_flow_regime(),
        )

        # Element-wise EVT routing for negative cells.
        rch_data, evt_spd = self._extract_evt_payload_2d(
            rch_data,
            getattr(recharge_cfg, "negative_to_evt", True),
        )

        return rch_data, evt_spd

    def _apply_first_clim_2d(
        self,
        raw_arrays: dict[int, np.ndarray],
        first_clim: object,
        flow_regime: str,
    ) -> dict[int, np.ndarray]:
        """Apply ``first_clim`` policy to period 0 of 2-D recharge arrays."""
        if flow_regime == "steady" or self.nper <= 1:
            if raw_arrays:
                all_vals = np.stack(list(raw_arrays.values()), axis=0)
                mean_arr = np.nanmean(all_vals, axis=0)
            else:
                mean_arr = np.zeros((self.nrow, self.ncol), dtype=float)
            return {0: mean_arr}

        result = dict(raw_arrays)
        if 0 not in result:
            return result

        if first_clim == "mean" and len(raw_arrays) > 0:
            all_vals = np.stack(list(raw_arrays.values()), axis=0)
            result[0] = np.nanmean(all_vals, axis=0)
        elif first_clim == "first":
            pass  # Keep period 0 as-is.
        elif self._is_scalar_number(first_clim):
            result[0] = np.full((self.nrow, self.ncol), float(first_clim), dtype=float)

        return result

    def _extract_evt_payload_2d(
        self,
        rch_data: dict[int, np.ndarray],
        negative_to_evt: bool,
    ) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray] | None]:
        """Element-wise EVT routing for 2-D recharge arrays.

        Negative cell values are moved to EVT; RCH cells clipped to 0.
        Period 0 EVT is always zero (warm-up convention).
        """
        if not negative_to_evt:
            return rch_data, None

        has_negative = any(np.any(arr < 0) for arr in rch_data.values())
        if not has_negative:
            return rch_data, None

        evt_data: dict[int, np.ndarray] = {}
        clipped_rch: dict[int, np.ndarray] = {}
        for kper, arr in rch_data.items():
            if kper == 0:
                evt_data[kper] = np.zeros_like(arr)
            else:
                evt_data[kper] = np.abs(np.minimum(arr, 0.0))
            clipped_rch[kper] = np.maximum(arr, 0.0)

        return clipped_rch, evt_data

    def _extract_evt_payload(
        self, payload: object, negative_to_evt: bool
    ) -> tuple[object, dict[int, object] | None]:
        """
        Route negative recharge values to an EVT stress-period dict and clip
        the recharge payload to non-negative values.

        In MODFLOW, EVT (EvapTranspiration) represents upward fluxes from the
        water table. When a recharge series contains negative values, those can
        optionally be routed to the EVT package instead of being zeroed out or
        left as negative RCH — which MODFLOW would otherwise reject.

        This method is a no-op (payload unchanged, ``None`` for EVT) when any
        of the following is true:

        - ``negative_to_evt`` is ``False``,
        - ``payload`` is a Mapping (period-keyed dict: per-value routing is
          not supported for this type),
        - ``payload`` is a scalar number,
        - ``payload`` contains no negative values.

        Parameters
        ----------
        payload : object
            Recharge series (numpy array, pandas Series, etc.). Negative values
            are clipped to 0 in place when EVT routing is triggered.
        negative_to_evt : bool
            Flag from ``recharge_cfg.negative_to_evt``.

        Returns
        -------
        tuple[object, dict[int, object] | None]
            ``(clipped_payload, evt_spd)`` where ``clipped_payload`` has all
            negative values set to 0 and ``evt_spd`` maps each stress period
            to the absolute value of the original negative recharge.

        Notes
        -----
        Period 0 always receives ``evt_spd[0] = 0``, regardless of the payload
        value. This mirrors the ``first_clim`` warm-up convention for RCH:
        the first climate step is excluded from EVT forcing.
        """
        if (
            not negative_to_evt
            or isinstance(payload, Mapping)
            or self._is_scalar_number(payload)
            or not self._has_negative_values(payload)
        ):
            return payload, None

        payload_for_rch = self._copy_payload(payload)
        evt_payload = self._copy_payload(payload)

        # Python lists do not support boolean masking (payload[payload < 0]).
        # Normalize sequence payloads to ndarrays before vectorized clipping.
        if isinstance(payload_for_rch, list):
            payload_for_rch = np.asarray(payload_for_rch, dtype=float)
        if isinstance(evt_payload, list):
            evt_payload = np.asarray(evt_payload, dtype=float)

        evt_payload[evt_payload >= 0] = 0
        evt_payload = np.abs(evt_payload)

        evt_spd: dict[int, object] = {
            kper: (0 if kper == 0 else self._series_value(evt_payload, kper))
            for kper in range(self.nper)
        }

        payload_for_rch[payload_for_rch < 0] = 0
        return payload_for_rch, evt_spd

    def _assemble_rch_data(self, payload: object, first_clim: object, flow_regime: str) -> object:
        """
        Convert a recharge payload into the period-indexed structure expected
        by ``ModflowRch(rech=...)``.

        Two assembly branches depending on ``payload`` type:

        **Mapping branch** (period-keyed dict supplied by the user):

        - Steady regime: collapses all values to a single scalar mean.
          An empty Mapping raises ``ValueError``.
        - Transient regime: returns a copy of the dict as-is (period keys
          are already explicit).

        **Sequence branch** (numpy array, pandas Series, or scalar):

        - Scalar payload: broadcast to the same constant for all ``nper``.
        - Period 0: handled by the ``first_clim`` policy (``'mean'``,
          ``'first'``, or a numeric override). Needed because climate series
          often start one index ahead of the first stress period.
        - Periods 1…nper-1: read directly from the series.

        Parameters
        ----------
        payload : object
            Recharge values after EVT clipping. May be a Mapping, a numpy
            array, a pandas Series, or a scalar number.
        first_clim : object
            Policy for period-0 when payload is a sequence.
            ``'mean'``: mean of the whole series (``np.nanmean``).
            ``'first'``: first element of the series.
            numeric: used as a constant override for period 0.
        flow_regime : str
            ``'steady'`` or ``'transient'``; controls the Mapping branch.

        Returns
        -------
        object
            ``dict[int, value]`` for transient runs, or a scalar for
            steady-state Mapping inputs.
        """
        if isinstance(payload, Mapping):
            if flow_regime == "steady":
                if len(payload) == 0:
                    raise ValueError(
                        "flow.sinks_sources.recharge.values mapping cannot be empty in steady regime."
                    )
                return sum(payload.values()) / len(payload)
            return dict(payload)

        rch_dict: dict[int, object] = {}
        for kper in range(self.nper):
            if self._is_scalar_number(payload):
                rch_dict[kper] = float(payload)
            elif kper == 0:
                if first_clim == "mean":
                    rch_dict[kper] = np.nanmean(payload)
                elif first_clim == "first":
                    rch_dict[kper] = self._series_value(payload, 0)
                elif self._is_scalar_number(first_clim):
                    rch_dict[kper] = float(first_clim)
                else:
                    raise ValueError(
                        "flow.sinks_sources.recharge.first_clim must be "
                        "'mean', 'first', or a numeric value."
                    )
            else:
                rch_dict[kper] = self._series_value(payload, kper)
        return rch_dict

    def build(self) -> FlowModflowInputs:
        """
        Build all solver-ready payloads in one deterministic pass.

        Pipeline
        --------
        1. startup heads + side boundaries,
        2. ocean CHD transformation,
        3. domain/property mapping,
        4. drainage package payload,
        5. well package payload,
        6. recharge (RCH) and evapotranspiration (EVT) payloads.

        Returns
        -------
        FlowModflowInputs
            One normalized container consumed by MODFLOW package assembly.
        """
        # Stage 1: startup states from IC + side BC.
        ibound, strt, drain_array = self._build_initial_heads_and_sides()

        # Stage 2: ocean BC may mutate startup arrays and produce CHD payload.
        ocean_chd_spd = self._build_ocean_chd(
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )
        side_chd_spd = self._build_side_chd()
        chd_spd = self._merge_chd_payloads(ocean_chd_spd, side_chd_spd)

        # Enforce BAS input contract before continuing package payload assembly.
        self._validate_ibound_strt_contract(
            ibound=np.asarray(ibound, dtype=float),
            strt=np.asarray(strt, dtype=float),
            drain_array=np.asarray(drain_array, dtype=float),
        )

        # Stage 3: resolve K/Sy/Ss arrays on solver support.
        required_properties = resolve_required_flow_properties(
            flow_regime=self._resolve_flow_regime(),
        )
        properties = resolve_flow_property_arrays(
            flow=self.flow,
            domain=self.domain,
            solver_mesh=self.solver_mesh,
            required_properties=required_properties,
            optional_fill_values={"Sy": 0.0, "Ss": 0.0},
            runtime_property_overrides=self.flow_runtime_overrides,
        )
        hk = properties["hk"]

        # Stage 4: derive drainage rows from refined drainage mask.
        drn_spd = self._build_drainage_spd(
            drain_array=drain_array,
            hk=hk,
        )

        # Stage 5: normalize wells to WEL stress-period structure.
        wel_spd = self._build_well_stress_period_data()

        # Stage 6: recharge and EVT payloads from flow.sinks_sources.recharge.
        rch_data, evt_spd = self._build_recharge_payload()

        # Final packaging of all solver-ready arrays and SPD payloads.
        return FlowModflowInputs(
            ibound=np.asarray(ibound, dtype=float),
            strt=np.asarray(strt, dtype=float),
            drain_array=np.asarray(drain_array, dtype=float),
            hk=np.asarray(properties["hk"], dtype=float),
            hk_value=np.asarray(properties["hk_value"], dtype=float),
            sy=np.asarray(properties["sy"], dtype=float),
            sy_value=np.asarray(properties["sy_value"], dtype=float),
            ss=np.asarray(properties["ss"], dtype=float),
            ss_value=np.asarray(properties["ss_value"], dtype=float),
            chd_spd=chd_spd,
            drn_spd=drn_spd,
            wel_spd=wel_spd,
            rch_data=rch_data,
            evt_spd=evt_spd,
        )
