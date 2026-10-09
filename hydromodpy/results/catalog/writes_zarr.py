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

    @property
    def save_zarr(self) -> bool:
        """Whether Zarr artefact writes are enabled (read-only view of persistence).

        Lets a writer that opens the Zarr directly (e.g. the solver extractor
        persisting a lake's restart state) honour the same switch as the guarded
        ``write_*`` verbs without growing the facade's method surface.
        """
        return self._persistence.save_zarr

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
        """Store a raster of a run under ``geographic/<name>`` in its field store.

        The catchment rasters (the clipped DEM, the watershed mask) are kept
        this way, so a run carries the frame it was computed on.

        Parameters
        ----------
        sim_id
            Id of the run.
        name
            Raster name, for example ``"watershed_dem"``.
        data
            The 2D grid of values.
        transform
            Affine coefficients that place the grid, as the raster file gives
            them.
        crs
            CRS of the grid, as text (WKT or ``"EPSG:2154"``).
        nodata
            Value that marks a cell without data.
        """
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_geographic_raster(name, data, transform=transform, crs=crs, nodata=nodata)
        finally:
            sz.close()

    def write_lake_abacus(self, sim_id: str | UUID, lake_id: str, **arrays) -> None:
        """Store the stage-volume-area curves of one lake of a run.

        The reference curves of the bathymetry next to the ones the solver
        used, all sampled on one stage axis, under ``lake_abacus/<lake_id>``.

        Parameters
        ----------
        sim_id
            Id of the run.
        lake_id
            Lake the curves belong to.
        **arrays
            ``stage``, ``real_volume``, ``real_sarea``, ``sim_volume`` and
            ``sim_sarea``, all of one length; optional ``stage_unit``,
            ``volume_unit`` and ``area_unit``.

        Raises
        ------
        ValueError
            If the arrays differ in length.
        """
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
        """Store one period of a field of a run.

        Parameters
        ----------
        sim_id
            Id of the run.
        variable
            Field name, for example ``"head"``.
        timestep
            Index of the period, ``0`` for the first.
        values
            One value per cell (and per layer).
        n_timesteps
            Number of periods of the field. Required on the first write of
            ``variable``, which sizes the array.
        subgroup
            Group of the store to write under. ``None`` writes at the root.

        Notes
        -----
        To write every period at once, :meth:`write_field_stack` is faster.
        Nothing is written when the run keeps no field store.
        """
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
        """Store many periods of a field of a run in one write.

        Parameters
        ----------
        sim_id
            Id of the run.
        variable
            Field name, for example ``"head"``.
        values
            Array whose first axis is time: ``(periods, cells)`` or
            ``(periods, layers, cells)``.
        n_timesteps
            Total number of periods of the field. Defaults to
            ``timestep_offset`` plus the length of ``values``.
        timestep_offset
            Period index of ``values[0]``. With ``n_timesteps``, it writes a
            long field slab by slab without holding it whole in memory.
        subgroup
            Group of the store to write under. ``None`` writes at the root.
        """
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
        """Store the time axis of the fields of a run (CF convention).

        Parameters
        ----------
        sim_id
            Id of the run.
        values
            One time per stored period, counted in ``units`` from the epoch.
        epoch, calendar, units
            CF description of the axis. Only the 1970-01-01 epoch is
            accepted.

        Raises
        ------
        ValueError
            If ``epoch`` or ``units`` names another epoch.
        """
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
        """Store the CRS of the fields of a run (CF grid mapping).

        Parameters
        ----------
        sim_id
            Id of the run.
        crs_wkt
            The CRS as WKT.
        grid_mapping_name
            CF name of the projection, for example
            ``"lambert_conformal_conic"``.
        epsg_code, semi_major_axis, inverse_flattening
            Optional CF attributes, stored when given.
        """
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
        """Store the mesh of a run (UGRID 1.0) in its field store.

        Every field of the run is laid out on these faces, so a reader can map
        it without the solver files.

        Parameters
        ----------
        sim_id
            Id of the run.
        vertices
            Coordinates of the mesh nodes, one row per node (x, y and
            optionally z).
        face_node_connectivity
            ``(n_faces, max_nodes)`` node indexes of each face.
        z_interfaces
            Elevations of the layer interfaces of one reference cell.
        layer_indices
            Layer of each face, when faces span several layers.
        source_cell_indices
            Index of each face in the solver grid.
        """
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
