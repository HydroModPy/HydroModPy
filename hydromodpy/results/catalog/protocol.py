"""SimulationStore Protocol: what a run writes and what a reader reads.

The writes are implemented by the run store of a run directory
(:mod:`hydromodpy.results.storage.run_store`), without any index; the reads
by :class:`hydromodpy.results.catalog.Catalog`, from the index. Workflow
steps, solver adapters and post-run extractors depend on this surface only.
Implementations conform structurally, there is no base class to inherit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from hydromodpy.results.run import Run
    from hydromodpy.results.zarr_store import SimulationZarr
    from hydromodpy.results.zarr_store.mesh_layout import MeshLayout


@runtime_checkable
class SimulationStore(Protocol):
    """Minimal write/read contract of a simulation results store.

    The Protocol covers three concerns:

    - per-simulation writes: ``write_parameters``, ``write_timeseries``,
      ``write_field``, ``write_time``, ``write_crs``, ``write_mesh``, ``write_provenance``,
      ``write_metric``, ``write_run_environment``, ``register_tracked_files``;
    - reads / queries: ``query_field``, ``query_timeseries``,
      ``list_simulations``, ``__getitem__``, ``open_zarr``;
    - lifetime: ``close`` (plus ``__enter__`` / ``__exit__``).

    Concrete stores are free to expose richer surfaces (discovery, ranking,
    ML splits). Workflow consumers depend only on what is declared here.
    """

    workspace_path: Path

    def write_parameters(
        self,
        sim_id: str | UUID,
        params: list[dict],
    ) -> None:
        """Persist solver parameters for ``sim_id``."""

    def write_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        ts: pd.Series,
        unit: str = "",
        qflag: str = "simulated",
    ) -> None:
        """Persist a per-station timeseries for ``sim_id``."""

    def write_budget(
        self,
        sim_id: str | UUID,
        timestep: int,
        zone_id: str,
        component: str,
        flux_in: float,
        flux_out: float,
        unit: str = "m3/s",
    ) -> None:
        """Persist one budget row for ``sim_id``."""

    def write_budgets(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        """Persist multiple budget rows for ``sim_id``."""

    def write_mass_balance(
        self,
        sim_id: str | UUID,
        timestep: int,
        total_in: float,
        total_out: float,
        percent_error: float,
        storage_in: float = 0.0,
        storage_out: float = 0.0,
    ) -> None:
        """Persist one mass-balance row for ``sim_id``."""

    def write_mass_balances(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        """Persist multiple mass-balance rows for ``sim_id``."""

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
        """Persist a 2D / 3D field array slice for ``sim_id`` at ``timestep``."""

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
        """Persist a full ``(time, ...)`` field stack for ``sim_id`` in one call."""

    def write_time(
        self,
        sim_id: str | UUID,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        """Persist the CF time coordinate for ``sim_id``."""

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
        """Persist the CF CRS grid mapping for ``sim_id``."""

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
        *,
        structured_shape: tuple[int, int] | None = None,
        layout: MeshLayout | None = None,
    ) -> None:
        """Persist the simulation mesh for ``sim_id``."""

    def write_view(
        self,
        sim_id: str | UUID,
        view_name: str,
        records: Sequence[Mapping[str, Any]],
    ) -> None:
        """Persist one declared Parquet view of ``sim_id`` into its run directory."""

    def write_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
        gdf: Any,
        *,
        geoparquet_path: str | None = None,
    ) -> None:
        """Persist one named vector feature of ``sim_id``."""

    def write_metric(
        self,
        sim_id: str | UUID,
        station_id: str,
        metric_name: str,
        value: float,
        *,
        variable: str = "head",
        n_samples: int | None = None,
        period_start: Any | None = None,
        period_end: Any | None = None,
    ) -> None:
        """Persist a scalar metric for ``sim_id`` at ``station_id``."""

    def write_provenance(
        self,
        sim_id: str | UUID,
        variable: str,
        source_ref: str,
        data: np.ndarray,
        *,
        source_type: str = "data_manager",
        source_sha256: str | None = None,
        loader_name: str | None = None,
        loader_version: str | None = None,
        fetched_at: Any = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        """Record fingerprint and source provenance for one variable."""

    def write_run_environment(
        self,
        sim_id: str | UUID,
        *,
        project_root: Path | str | None = None,
        solver_name: str | None = None,
        solver_binary_path: Path | str | None = None,
        solver_engine: str | None = None,
        solver_execution_mode: str | None = None,
        solver_version_text: str | None = None,
        rng_seed: int | None = None,
    ) -> None:
        """Capture and persist host environment snapshot for ``sim_id``."""

    def update_simulation_grid_metadata(
        self,
        sim_id: str | UUID,
        *,
        n_cells: int | None = None,
        n_layers: int | None = None,
        mesh_hash: str | None = None,
        mesh_topology: str | None = None,
        bbox: tuple[float, float, float, float] | list[float] | None = None,
    ) -> None:
        """Backfill grid metadata known only once the solver grid is built."""

    def update_run_environment_solver_binary(
        self,
        sim_id: str | UUID,
        *,
        solver_binary_path: Path | str | None,
    ) -> None:
        """Refine the recorded solver binary identity with the path that ran."""

    def register_tracked_files(
        self,
        sim_id: str | UUID,
        entries: list[Any],
    ) -> int:
        """Persist tracked-input file records for ``sim_id``."""

    def query_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        """Read a field array slice for ``sim_id`` at ``timestep``."""

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
    ) -> pd.Series:
        """Read a per-station simulated timeseries for ``sim_id``."""

    def list_simulations(self, **filters: Any) -> pd.DataFrame:
        """Return one DataFrame row per sealed run matching ``filters``."""

    def run_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the directory holding everything ``sim_id`` produced."""

    def fields_path_for(self, sim_id: str | UUID) -> Path:
        """Return the field-array store of ``sim_id``."""

    def tables_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the directory holding the tabular payloads of ``sim_id``."""

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        """Open the per-simulation Zarr store for ``sim_id``."""

    def close(self) -> None:
        """Release every open resource (DB connection, Zarr handles)."""

    def __getitem__(self, ref: str | UUID) -> Run:
        """Resolve ``ref`` to a :class:`Run` view bound to this store."""

    def __enter__(self) -> SimulationStore: ...

    def __exit__(self, *exc: object) -> None: ...
