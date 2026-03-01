# -*- coding: utf-8 -*-
"""
Flow -> MODFLOW-NWT adaptation layer.

This module isolates the transformation from process-level `Flow` inputs
(`parameters`, `initial_conditions`, `boundary_conditions`, `sinks_sources`)
to arrays and stress-period payloads directly consumable by MODFLOW-NWT.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real

import numpy as np
import pandas as pd

from hydromodpy.solver.modflow_nwt.modflow_utils import (
    build_flow_domain_property_snapshot,
)


@dataclass(slots=True)
class FlowModflowInputs:
    """Solver-ready payloads produced from one validated Flow object."""

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


@dataclass
class _PropertyMappingProxy:
    """Minimal object contract required by `build_flow_domain_property_snapshot`."""

    flow: object
    domain: object


class FlowToModflowAdapter:
    """
    Build MODFLOW-NWT arrays/stress-period structures from Flow + context.

    The adapter does not instantiate FLOPY packages. It only prepares data.
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
        self.flow = flow
        self.domain = domain
        self.sgrid = sgrid
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
        boundary_conditions = getattr(self.flow, "boundary_conditions", {})
        if not isinstance(boundary_conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return boundary_conditions

    def _side_boundary(self, canonical_id: str, legacy_id: str):
        boundary = self._boundary_conditions.get(canonical_id)
        if boundary is None:
            boundary = self._boundary_conditions.get(legacy_id)
        return boundary

    def _build_initial_heads_and_sides(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ibound = np.ones((self.nlay, self.nrow, self.ncol), dtype=float)

        initial_conditions = getattr(self.flow, "initial_conditions", None)
        initial_condition = None if initial_conditions is None else getattr(initial_conditions, "h", None)
        if initial_condition is None:
            raise ValueError("flow.initial_conditions.h is required for MODFLOW startup")

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

        west_boundary = self._side_boundary("west_side", "west_boundary")
        if west_boundary is not None:
            ibound[:, :, 0] = -1
            strt[:, :, 0] = float(west_boundary.value)

        east_boundary = self._side_boundary("east_side", "east_boundary")
        if east_boundary is not None:
            ibound[:, :, -1] = -1
            strt[:, :, -1] = float(east_boundary.value)

        north_boundary = self._side_boundary("north_side", "north_boundary")
        if north_boundary is not None:
            ibound[:, 0, :] = -1
            strt[:, 0, :] = float(north_boundary.value)

        south_boundary = self._side_boundary("south_side", "south_boundary")
        if south_boundary is not None:
            ibound[:, -1, :] = -1
            strt[:, -1, :] = float(south_boundary.value)

        for ilay in range(self.nlay):
            ibound[ilay][self.dem < -1000] = 0

        drain_array = np.ones((self.nrow, self.ncol), dtype=float)
        return ibound, strt, drain_array

    @staticmethod
    def _is_scalar_number(value: object) -> bool:
        return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
            value, bool
        )

    def _build_ocean_chd(
        self,
        *,
        ibound: np.ndarray,
        strt: np.ndarray,
        drain_array: np.ndarray,
    ) -> dict[int, list[list[float]]] | None:
        ocean_boundary = self._boundary_conditions.get("ocean")
        if ocean_boundary is None:
            return None

        ocean_value = getattr(ocean_boundary, "value", None)
        if self._is_scalar_number(ocean_value):
            ocean_head = float(ocean_value)
            for ilay in range(self.nlay):
                ibound[ilay][self.dem <= ocean_head] = -1
            strt[ibound == -1] = ocean_head

        if not isinstance(ocean_value, (int, float, np.ndarray, pd.Series, list, tuple)):
            return None
        if self._is_scalar_number(ocean_value):
            return None

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

        sea_threshold = float(np.max(ocean_series))
        chd_spd: dict[int, list[list[float]]] = {}
        for kper in range(self.nper):
            chd_kper: list[list[float]] = []
            kper_head = float(ocean_series[kper])
            for i in range(self.nrow):
                for j in range(self.ncol):
                    if self.dem[i, j] < sea_threshold and ibound[0, i, j] != 0:
                        drain_array[i, j] = 0
                        chd_kper.append([0, i, j, kper_head, kper_head])
            chd_spd[kper] = chd_kper
        return chd_spd

    def _build_property_arrays(self) -> dict[str, np.ndarray]:
        mapping_specs = [
            (("K", "k"), "hk", "hk_value", "Hydraulic conductivity"),
            (("Sy", "SY", "sy", "S", "s"), "sy", "sy_value", "Specific yield"),
            (("Ss", "SS", "ss"), "ss", "ss_value", "Specific storage"),
        ]
        proxy = _PropertyMappingProxy(flow=self.flow, domain=self.domain)
        flow_params = build_flow_domain_property_snapshot(
            model=proxy,
            sgrid=self.sgrid,
            mapping_specs=mapping_specs,
            strict=True,
        )

        out: dict[str, np.ndarray] = {}
        for _, target_3d_attr, target_surface_attr, label in mapping_specs:
            values_3d = flow_params.get(target_3d_attr)
            values_2d = flow_params.get(target_surface_attr)
            if values_3d is None or values_2d is None:
                raise ValueError(
                    f"Missing mapped values for {label} "
                    f"('{target_3d_attr}' / '{target_surface_attr}')."
                )
            out[target_3d_attr] = np.asarray(values_3d, dtype=float)
            out[target_surface_attr] = np.asarray(values_2d, dtype=float)
        return out

    def _build_drainage_spd(
        self,
        *,
        drain_array: np.ndarray,
        hk: np.ndarray,
    ) -> dict[int, np.ndarray] | None:
        drainage_boundary = self._boundary_conditions.get("drainage")
        if drainage_boundary is None:
            return None

        if self.sink_fill and self.sink is None:
            raise ValueError(
                "sink_fill=True requires geographic.depressions_data (sink raster)"
            )

        drn_data = np.zeros((int(np.sum(drain_array)), 5), dtype=float)
        drn_data[:, 0] = 0
        drainage_value = float(drainage_boundary.value)

        count = 0
        for i in range(self.nrow):
            for j in range(self.ncol):
                if drain_array[i, j] != 1:
                    continue

                drn_data[count, 1] = i
                drn_data[count, 2] = j
                drn_data[count, 3] = self.dem[i, j]

                if not self.sink_fill:
                    if drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.resolution**2
                else:
                    if self.sink[i, j] > 0:
                        drn_data[count, 4] = 0.0
                    elif drainage_value > 0:
                        drn_data[count, 4] = drainage_value
                    else:
                        drn_data[count, 4] = hk[0, i, j] * self.resolution**2
                count += 1

        return {0: drn_data}

    def _build_well_stress_period_data(self) -> dict[int, list[list[float]]]:
        if self.nper <= 0:
            return {}

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        if not isinstance(sinks_sources, Mapping):
            return {}

        wells = sinks_sources.get("wells", {})
        if wells is None:
            return {}
        if not isinstance(wells, Mapping):
            raise TypeError(
                "flow.sinks_sources['wells'] must be a mapping of well ids to payloads."
            )
        if len(wells) == 0:
            return {}

        normalized_wells: list[tuple[str, tuple[int, int, int], np.ndarray]] = []
        for raw_well_id, raw_well_payload in wells.items():
            well_id = str(raw_well_id).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty ids.")

            if isinstance(raw_well_payload, Mapping):
                cell_payload = raw_well_payload.get("cell")
                flux_payload = raw_well_payload.get("flux")
            else:
                cell_payload = getattr(raw_well_payload, "cell", None)
                flux_payload = getattr(raw_well_payload, "flux", None)

            if cell_payload is None:
                raise ValueError(f"flow.sinks_sources.wells.{well_id}.cell is required")
            if flux_payload is None:
                raise ValueError(f"flow.sinks_sources.wells.{well_id}.flux is required")

            if isinstance(cell_payload, Mapping):
                cell_seq = [
                    cell_payload.get("lay"),
                    cell_payload.get("row"),
                    cell_payload.get("col"),
                ]
            else:
                cell_seq = list(cell_payload)
            if len(cell_seq) != 3:
                raise ValueError(
                    f"flow.sinks_sources.wells.{well_id}.cell must contain 3 values: [lay,row,col]"
                )

            cell_parsed: list[int] = []
            for axis, raw_index in zip(("lay", "row", "col"), cell_seq):
                if isinstance(raw_index, bool) or not isinstance(raw_index, Real):
                    raise TypeError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be numeric"
                    )
                numeric_index = float(raw_index)
                if not numeric_index.is_integer():
                    raise TypeError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be an integer"
                    )
                int_index = int(numeric_index)
                if int_index < 0:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be >= 0"
                    )
                cell_parsed.append(int_index)
            cell = (cell_parsed[0], cell_parsed[1], cell_parsed[2])

            if isinstance(flux_payload, bool):
                raise TypeError(
                    f"flow.sinks_sources.wells.{well_id}.flux must be numeric or list of numeric values"
                )
            if isinstance(flux_payload, Real):
                flux_vector = np.full(self.nper, float(flux_payload), dtype=float)
            else:
                flux_vector = np.asarray(flux_payload, dtype=float).reshape(-1)
                if flux_vector.size == 0:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.flux cannot be empty"
                    )
                if flux_vector.size == 1:
                    flux_vector = np.full(self.nper, float(flux_vector[0]), dtype=float)
                elif flux_vector.size != self.nper:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.flux length ({flux_vector.size}) "
                        f"must be 1 or match nper ({self.nper})"
                    )

            normalized_wells.append((well_id, cell, flux_vector))

        lrcq: dict[int, list[list[float]]] = {}
        for t in range(self.nper):
            lrcq[t] = [
                [cell[0], cell[1], cell[2], float(flux_vector[t])]
                for _, cell, flux_vector in normalized_wells
            ]
        return lrcq

    def build(self) -> FlowModflowInputs:
        """Build all solver-ready Flow payloads in one pass."""
        ibound, strt, drain_array = self._build_initial_heads_and_sides()
        chd_spd = self._build_ocean_chd(
            ibound=ibound,
            strt=strt,
            drain_array=drain_array,
        )

        properties = self._build_property_arrays()
        hk = properties["hk"]
        drn_spd = self._build_drainage_spd(
            drain_array=drain_array,
            hk=hk,
        )
        wel_spd = self._build_well_stress_period_data()

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
        )
