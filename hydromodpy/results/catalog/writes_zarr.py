"""Zarr write concern for :class:`Catalog`.

Field/time/CRS/mesh and geographic raster writes are forwarded to the
per-simulation :class:`SimulationZarr` handle opened through
``LifecycleMixin.open_zarr``. Methods early-return when
``self._persistence.save_zarr`` is False so a single switch governs the
Zarr sink.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import numpy as np


class WritesMixinZarr:
    """Zarr-backed write operations for the catalog facade."""

    def write_geographic_raster(
        self,
        sim_id: str | UUID,
        name: str,
        data: np.ndarray,
        *,
        transform: tuple[float, ...],
        crs: str,
        nodata: float = -99999.0,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_geographic_raster(name, data, transform=transform, crs=crs, nodata=nodata)
        finally:
            sz.close()

    def write_lake_abacus(self, sim_id: str | UUID, lake_id: str, **arrays) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_lake_abacus(lake_id, **arrays)
        finally:
            sz.close()

    def write_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        subgroup: str | None = None,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_field(variable, timestep, values, n_timesteps=n_timesteps, subgroup=subgroup)
        finally:
            sz.close()

    def write_field_stack(
        self,
        sim_id: str | UUID,
        variable: str,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        timestep_offset: int = 0,
        subgroup: str | None = None,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_field_stack(
                variable,
                values,
                n_timesteps=n_timesteps,
                timestep_offset=timestep_offset,
                subgroup=subgroup,
            )
        finally:
            sz.close()

    def write_time(
        self,
        sim_id: str | UUID,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_time(values, epoch=epoch, calendar=calendar, units=units)
        finally:
            sz.close()

    def write_crs(
        self,
        sim_id: str | UUID,
        *,
        crs_wkt: str,
        grid_mapping_name: str = "latitude_longitude",
        epsg_code: int | None = None,
        semi_major_axis: float | None = None,
        inverse_flattening: float | None = None,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_crs(
                crs_wkt=crs_wkt,
                grid_mapping_name=grid_mapping_name,
                epsg_code=epsg_code,
                semi_major_axis=semi_major_axis,
                inverse_flattening=inverse_flattening,
            )
        finally:
            sz.close()

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_mesh(
                vertices,
                face_node_connectivity,
                z_interfaces,
                layer_indices=layer_indices,
                source_cell_indices=source_cell_indices,
            )
        finally:
            sz.close()


__all__ = ["WritesMixinZarr"]
