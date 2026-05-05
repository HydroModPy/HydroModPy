# Intentional duplication with the MF6 flow_to_modflow_adapter: MODFLOW-NWT is
# scheduled for removal after the Lake (LAK) module lands on the MF6 side - not
# worth factoring the payload builders out. See dev_notes/decisions/nwt_sunset_plan.md.
"""Flow -> MODFLOW-NWT adaptation layer.

Purpose
-------
Convert process-level objects into solver-level data structures:

- from ``Flow`` / ``Domain`` runtime objects,
- to MODFLOW-ready arrays and stress-period data dictionaries.

The class is a thin facade. Concerns are split across:

- ``_chd_payloads.py``: initial heads, side BC, ocean CHD, side CHD, BAS validation.
- ``_well_drainage_payloads.py``: WEL and DRN stress-period payloads.
- ``_recharge_etp_payloads.py``: RCH and EVT payloads (homogeneous and heterogeneous).

The adapter does not instantiate FLOPY packages. Package construction is done
by ``ModflowNwt`` after adaptation is complete.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.grid_reference import GridReference
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_flow_property_arrays,
    resolve_required_flow_properties,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt._chd_payloads import (
    build_initial_heads_and_sides,
    build_ocean_chd,
    build_side_chd,
    merge_chd_payloads,
    validate_ibound_strt_contract,
)
from hydromodpy.solver.modflow_nwt.nwt._recharge_etp_payloads import (
    build_etp_payload,
    build_recharge_payload,
    resolve_flow_regime,
)
from hydromodpy.solver.modflow_nwt.nwt._well_drainage_payloads import (
    build_drainage_spd,
    build_well_stress_period_data,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow


@dataclass(slots=True)
class FlowModflowInputs:
    """Solver-ready payloads produced from one validated ``Flow`` runtime object.

    Notes
    -----
    - Arrays use MODFLOW indexing conventions (`lay,row,col` for 3D arrays).
    - Stress-period dictionaries are keyed by zero-based period index.
    - Optional payloads are omitted as ``None`` when the corresponding process
      boundary/source is not defined.
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
    evt_surface_offset: float = 2.0
    evt_extinction_depth: float = 1.0


class FlowToModflowAdapter:
    """Build MODFLOW-NWT arrays/stress-period structures from Flow + context.

    Scope
    -----
    This class only prepares solver data. FLOPY package construction is done
    by the caller (`ModflowNwt`), after adaptation is complete.

    The class delegates concern-specific work to private modules in this
    package: see ``_chd_payloads``, ``_well_drainage_payloads``, and
    ``_recharge_etp_payloads``.
    """

    def __init__(
        self,
        *,
        flow: object,
        domain: object,
        solver_mesh: SolverMesh,
        nper: int,
        grid: GridReference | None = None,
        simulation_window: ResolvedSimulationTimeWindow | None = None,
        sink_fill: bool,
        sink=None,
        flow_runtime_overrides: Mapping[str, object] | None = None,
    ):
        """Store adaptation context and normalize primitive arrays/scalars."""
        if not solver_mesh.is_structured:
            raise ValueError(
                "FlowToModflowAdapter requires a structured SolverMesh "
                "(MODFLOW NWT only supports structured grids)"
            )

        self.flow = flow
        self.domain = domain
        self.solver_mesh = solver_mesh

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
        self._negative_recharge_evt_spd: dict[int, object] | None = None

    @property
    def _boundary_conditions(self) -> Mapping[str, object]:
        """Return flow boundary-condition mapping with a strict runtime check."""
        boundary_conditions = getattr(self.flow, "boundary_conditions", {})
        if not isinstance(boundary_conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return boundary_conditions

    def _is_bc_active(self, bc_id: str) -> bool:
        """Return True when ``bc_id`` is explicitly declared in ``flow.active_bc``."""
        active = getattr(self.flow, "active_bc", [])
        return bc_id in active

    def _build_initial_heads_and_sides(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Build startup ``ibound`` and ``strt`` arrays from flow IC + side BCs."""
        return build_initial_heads_and_sides(self)

    def _validate_ibound_strt_contract(
        self,
        *,
        ibound: np.ndarray,
        strt: np.ndarray,
        drain_array: np.ndarray,
    ) -> None:
        """Validate BAS-facing ``ibound``/``strt`` arrays before package assembly."""
        validate_ibound_strt_contract(
            nlay=self.nlay,
            nrow=self.nrow,
            ncol=self.ncol,
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )

    def _build_ocean_chd(
        self,
        *,
        ibound: np.ndarray,
        strt: np.ndarray,
        drain_array: np.ndarray,
    ) -> dict[int, list[list[float]]] | None:
        """Build CHD stress-period data for the ocean boundary."""
        return build_ocean_chd(
            self,
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )

    def _build_side_chd(self) -> dict[int, list[list[float]]] | None:
        """Build CHD stress-period data for transient lateral Dirichlet boundaries."""
        return build_side_chd(self)

    def _merge_chd_payloads(
        self,
        *payloads: dict[int, list[list[float]]] | None,
    ) -> dict[int, list[list[float]]] | None:
        """Merge CHD payloads with later inputs overriding earlier duplicate cells."""
        return merge_chd_payloads(self.nper, *payloads)

    def _build_drainage_spd(
        self,
        *,
        drain_array: np.ndarray,
        hk: np.ndarray,
    ) -> dict[int, np.ndarray] | None:
        """Build DRN stress-period data from drainage BC and activation mask."""
        return build_drainage_spd(self, drain_array=drain_array, hk=hk)

    def _build_well_stress_period_data(self) -> dict[int, list[list[float]]]:
        """Normalize flow wells into MODFLOW WEL stress-period format."""
        return build_well_stress_period_data(self)

    def _build_recharge_payload(self) -> object | None:
        """Build the RCH payload from ``flow.sinks_sources["recharge"]``."""
        return build_recharge_payload(self)

    def _build_etp_payload(self) -> tuple[dict[int, object] | None, float, float]:
        """Build the EVT payload from ``flow.sinks_sources["etp"]``."""
        return build_etp_payload(self)

    def build(self) -> FlowModflowInputs:
        """Build all solver-ready payloads in one deterministic pass."""
        ibound, strt, drain_array = self._build_initial_heads_and_sides()

        ocean_chd_spd = self._build_ocean_chd(
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )
        side_chd_spd = self._build_side_chd()
        chd_spd = merge_chd_payloads(self.nper, ocean_chd_spd, side_chd_spd)

        self._validate_ibound_strt_contract(
            ibound=np.asarray(ibound, dtype=float),
            strt=np.asarray(strt, dtype=float),
            drain_array=np.asarray(drain_array, dtype=float),
        )

        required_properties = resolve_required_flow_properties(
            flow_regime=resolve_flow_regime(self.flow),
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

        drn_spd = self._build_drainage_spd(
            drain_array=drain_array,
            hk=hk,
        )

        wel_spd = self._build_well_stress_period_data()
        rch_data = self._build_recharge_payload()
        evt_spd, evt_surface_offset, evt_extinction_depth = self._build_etp_payload()

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
            evt_surface_offset=evt_surface_offset,
            evt_extinction_depth=evt_extinction_depth,
        )


__all__ = ["FlowModflowInputs", "FlowToModflowAdapter"]
