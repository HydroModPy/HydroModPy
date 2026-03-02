# -*- coding: utf-8 -*-
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
- ``domain`` + ``sgrid`` context:
  spatial support used to map process properties onto solver cells, including
  geological zoning and structured-grid geometry.

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
from numbers import Real

import numpy as np
import pandas as pd

from .property_mapping import (
    resolve_flow_property_arrays,
)


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
    - ``domain.zones["geology"]`` when mapping heterogeneous properties.

    The adapter assumes the caller already prepared the spatial/temporal
    context (grid dimensions, DEM/bottom arrays, stress-period count).
    """

    def __init__(
        self,
        *,
        flow: object,
        domain: object,
        sgrid: object,
        dem,
        bottom_layer,
        nlay: int,
        nrow: int,
        ncol: int,
        nper: int,
        resolution: float,
        sink_fill: bool,
        sink=None,
    ):
        """
        Store adaptation context and normalize primitive arrays/scalars.

        Parameters
        ----------
        flow : object
            Runtime flow-process instance carrying IC/BC/parameters.
        domain : object
            Runtime domain instance carrying spatial zones (including geology).
        sgrid : object
            Structured grid used for parameter discretization.
        dem : array-like
            Topographic surface array on model support (2D).
        bottom_layer : array-like
            Bottom elevation array of the deepest layer (2D).
        nlay, nrow, ncol : int
            MODFLOW grid dimensions.
        nper : int
            Number of stress periods.
        resolution : float
            Horizontal cell-size proxy used in default DRN conductance formula.
        sink_fill : bool
            If True, sink mask can deactivate drainage conductance locally.
        sink : array-like | None
            Optional sink/depression raster aligned with model rows/cols.
        """
        # Keep source objects by reference (read-only usage).
        self.flow = flow
        self.domain = domain
        self.sgrid = sgrid

        # Normalize numeric contexts once so all downstream branches operate on
        # consistent dtypes and shapes.
        self.dem = np.asarray(dem, dtype=float)
        self.bottom_layer = np.asarray(bottom_layer, dtype=float)
        self.nlay = int(nlay)
        self.nrow = int(nrow)
        self.ncol = int(ncol)
        self.nper = int(nper)
        self.resolution = float(resolution)
        self.sink_fill = bool(sink_fill)
        self.sink = None if sink is None else np.asarray(sink, dtype=float)

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
        initial_condition = None if initial_conditions is None else getattr(initial_conditions, "h", None)
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
            strt = (
                np.ones((self.nlay, self.nrow, self.ncol), dtype=float)
                * float(getattr(initial_condition, "value"))
            )
        else:
            raise ValueError(
                "flow.initial_conditions.h.type must be one of: top, bottom, custom"
            )

        # Side Dirichlet boundaries are enforced by:
        # - setting ibound to -1 (constant-head cells),
        # - forcing startup heads on the same faces.
        west_side = self._boundary_conditions.get("west_side") if self._is_bc_active("west_side") else None
        if west_side is not None:
            ibound[:, :, 0] = -1
            strt[:, :, 0] = float(west_side.value)

        east_side = self._boundary_conditions.get("east_side") if self._is_bc_active("east_side") else None
        if east_side is not None:
            ibound[:, :, -1] = -1
            strt[:, :, -1] = float(east_side.value)

        north_side = self._boundary_conditions.get("north_side") if self._is_bc_active("north_side") else None
        if north_side is not None:
            ibound[:, 0, :] = -1
            strt[:, 0, :] = float(north_side.value)

        south_side = self._boundary_conditions.get("south_side") if self._is_bc_active("south_side") else None
        if south_side is not None:
            ibound[:, -1, :] = -1
            strt[:, -1, :] = float(south_side.value)

        # Cells under the DEM sentinel threshold are set inactive.
        for ilay in range(self.nlay):
            ibound[ilay][self.dem < -1000] = 0

        drain_array = np.ones((self.nrow, self.ncol), dtype=float)
        return ibound, strt, drain_array

    @staticmethod
    def _is_scalar_number(value: object) -> bool:
        """Return True for numeric scalar values (excluding booleans)."""
        return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
            value, bool
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
            ocean_head = float(ocean_value)
            for ilay in range(self.nlay):
                ibound[ilay][self.dem <= ocean_head] = -1
            strt[ibound == -1] = ocean_head

        # 2) CHD package data is only built for sequence-like inputs.
        # Scalar ocean forcing has already been fully applied in-place above.
        if not isinstance(ocean_value, (int, float, np.ndarray, pd.Series, list, tuple)):
            return None
        if self._is_scalar_number(ocean_value):
            return None

        # 3) Normalize the ocean forcing vector to nper.
        ocean_series = np.asarray(ocean_value, dtype=float).reshape(-1)
        if ocean_series.size == 0:
            raise ValueError("flow.bc.ocean.value cannot be empty when using time series")
        if ocean_series.size == 1:
            ocean_series = np.full(self.nper, float(ocean_series[0]), dtype=float)
        elif ocean_series.size != self.nper:
            raise ValueError(
                f"flow.bc.ocean.value length ({ocean_series.size}) "
                f"must be 1 or match nper ({self.nper})"
            )

        # Geometry mask is fixed from the highest sea level; transient heads are
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
            raise ValueError(
                f"ibound shape mismatch: expected {expected_3d}, got {ibound.shape}"
            )
        if strt.shape != expected_3d:
            raise ValueError(
                f"strt shape mismatch: expected {expected_3d}, got {strt.shape}"
            )
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
            raise ValueError(
                "drain_array must only contain binary activation values {0, 1}"
            )

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
        - Otherwise: derive conductance from ``hk * resolution^2``.
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
            raise ValueError(
                "sink_fill=True requires geographic.depressions_data (sink raster)"
            )

        # MODFLOW DRN row format: [lay, row, col, elevation, conductance].
        # Only currently active drain cells are materialized.
        drn_data = np.zeros((int(np.sum(drain_array)), 5), dtype=float)
        drn_data[:, 0] = 0
        drainage_value = float(drainage_boundary.value)

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
                    # local permeability footprint.
                    if drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.resolution**2
                else:
                    # Sink-filled cells should not drain.
                    if self.sink[i, j] > 0:
                        drn_data[count, 4] = 0.0
                    elif drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.resolution**2
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

        # Broadcast scalar / single-value flux to nper; reject length mismatches.
        normalized_wells: list[tuple[str, tuple[int, int, int], np.ndarray]] = []
        for well_id, well in wells.items():
            cell: tuple[int, int, int] = well.cell
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
            raise ValueError(
                "flow.flow_regime is required to build recharge payloads."
            )
        flow_regime = str(regime).strip().lower()
        if flow_regime not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
        return flow_regime

    def _build_recharge_payload(self) -> tuple[object, dict[int, object] | None]:
        """
        Build RCH and EVT payloads from ``flow.sinks_sources["recharge"]``.

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

        recharge_payload = self._copy_payload(recharge_cfg.values)
        recharge_payload, evt_spd = self._extract_evt_payload(recharge_payload, recharge_cfg.negative_to_evt)
        rch_data = self._assemble_rch_data(recharge_payload, recharge_cfg.first_clim, self._resolve_flow_regime())
        return rch_data, evt_spd

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

        evt_payload = self._copy_payload(payload)
        evt_payload[evt_payload >= 0] = 0
        evt_payload = abs(evt_payload)

        evt_spd: dict[int, object] = {
            kper: (0 if kper == 0 else self._series_value(evt_payload, kper))
            for kper in range(self.nper)
        }

        payload[payload < 0] = 0
        return payload, evt_spd

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
        chd_spd = self._build_ocean_chd(
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )

        # Enforce BAS input contract before continuing package payload assembly.
        self._validate_ibound_strt_contract(
            ibound=np.asarray(ibound, dtype=float),
            strt=np.asarray(strt, dtype=float),
            drain_array=np.asarray(drain_array, dtype=float),
        )

        # Stage 3: resolve K/Sy/Ss arrays on solver support.
        properties = resolve_flow_property_arrays(
            flow=self.flow,
            domain=self.domain,
            sgrid=self.sgrid,
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
