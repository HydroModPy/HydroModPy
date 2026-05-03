"""SimulationStore Protocol for result-catalog backends.

The default in-tree implementation is
:class:`hydromodpy.results.catalog.SimulationCatalog`, backed by DuckDB
for tabular state and Zarr / Parquet for field arrays and timeseries.

Conforming alternative backends (PostgreSQL, Parquet-only, in-memory for
tests, remote object storage) can be plugged behind this same contract
without changing the workflow steps that consume it. Implementations
conform structurally - no base class to inherit from.

The contract is the minimal write/read surface that workflow steps,
solver adapters, and post-run extractors actually call. Methods absent
from this Protocol stay implementation-specific to ``SimulationCatalog``
(``find``, ``rank``, ``training_split``, archive package_io ...).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from hydromodpy.results.catalog.registration import RegistrationResult
    from hydromodpy.results.run import Run
    from hydromodpy.results.zarr_store import SimulationZarr


@runtime_checkable
class SimulationStore(Protocol):
    """Minimal write/read contract for a simulation results catalog.

    The Protocol covers four concerns:

    - registration: ``register_simulation``;
    - per-simulation writes: ``write_parameters``, ``write_timeseries``,
      ``write_field``, ``write_time``, ``write_crs``, ``write_mesh``, ``write_provenance``,
      ``write_metric``, ``write_run_environment``, ``register_tracked_files``;
    - reads / queries: ``query_field``, ``query_timeseries``,
      ``list_simulations``, ``__getitem__``, ``open_zarr``;
    - lifecycle: ``finalize``, ``close`` (plus ``__enter__`` / ``__exit__``).

    Concrete backends are free to expose richer surfaces (discovery,
    ranking, ML splits, archive import/export). Workflow consumers must
    only depend on what is declared here.
    """

    workspace_path: Path

    def register_simulation(
        self,
        sim_id: str | UUID,
        project: str,
        solver: str,
        *,
        name: str | None = None,
        on_collision: str = "replace",
        **kwargs: Any,
    ) -> RegistrationResult:
        """Allocate a new simulation row and return its registration result."""

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

    def write_observations(
        self,
        station_id: str,
        variable_type: str,
        ts: Any,
        unit: str = "",
        quality: str | None = None,
    ) -> None:
        """Persist observed station timeseries in the workspace observation table."""

    def write_station(
        self,
        station_id: str,
        variable_type: str,
        *,
        name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        elevation: float | None = None,
        source: str | None = None,
        first_valid: Any = None,
        last_valid: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist station metadata for an observed timeseries."""

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
    ) -> None:
        """Persist the simulation mesh for ``sim_id``."""

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
        mf6_binary_path: Path | str | None = None,
    ) -> None:
        """Capture and persist host environment snapshot for ``sim_id``."""

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
        """Return one DataFrame row per simulation matching ``filters``."""

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        """Open the per-simulation Zarr store for ``sim_id``."""

    def finalize(
        self,
        sim_id: str | UUID,
        status: str = "completed",
        duration_s: float | None = None,
    ) -> None:
        """Mark ``sim_id`` final, set its status, and pack on-disk artefacts."""

    def close(self) -> None:
        """Release every open resource (DB connection, Zarr handles)."""

    def __getitem__(self, ref: str | UUID) -> Run:
        """Resolve ``ref`` to a :class:`Run` view bound to this store."""

    def __enter__(self) -> SimulationStore: ...

    def __exit__(self, *exc: object) -> None: ...
